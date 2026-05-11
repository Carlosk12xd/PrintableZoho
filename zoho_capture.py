from __future__ import annotations

import base64
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from PIL import Image


ALLOWED_ZOHO_HOST_FRAGMENTS = (
    "analytics.zoho.com",
    "analytics.zoho.eu",
    "analytics.zoho.in",
    "analytics.zoho.com.au",
    "analytics.zoho.jp",
    "analytics.zoho.ca",
)


@dataclass
class CaptureOptions:
    wait_seconds: int = 6
    timeout_ms: int = 90_000
    max_visuals_per_link: int = 24
    min_width: int = 220
    min_height: int = 120
    include_full_page_fallback: bool = True
    full_page_if_less_than: int = 1
    crop_whitespace: bool = False


@dataclass
class VisualCapture:
    visual_id: str
    source_url: str
    title: str
    kind: str
    width: int
    height: int
    page_index: int
    visual_index: int
    confidence_score: int
    selector: str
    frame_url: str
    image_bytes: bytes
    captured_at: str

    def to_metadata(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("image_bytes", None)
        return data


def validate_zoho_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValueError("Paste a Zoho Analytics URL first.")

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("Use an https:// Zoho Analytics URL.")

    host = parsed.netloc.lower()
    if not any(fragment in host for fragment in ALLOWED_ZOHO_HOST_FRAGMENTS):
        raise ValueError(
            "This app only accepts Zoho Analytics links, like "
            "https://analytics.zoho.com/open-view/..."
        )

    return url


def ensure_chromium_installed() -> Optional[str]:
    """
    Verify Playwright Chromium can launch. If missing, try installing it.
    Returns None if ready, otherwise an error message.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return None
    except Exception as first_error:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                return (
                    "Could not auto-install Playwright Chromium. "
                    f"Original error: {first_error}. "
                    f"Install output: {result.stderr[-1200:]}"
                )

            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()

            return None
        except Exception as second_error:
            return (
                "Playwright Chromium is not available. "
                f"First error: {first_error}. Second error: {second_error}."
            )


def _image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    from io import BytesIO

    with Image.open(BytesIO(image_bytes)) as img:
        return img.size


def _trim_whitespace(image_bytes: bytes) -> bytes:
    """
    Conservative whitespace crop. Kept optional because some dashboards use light backgrounds
    where aggressive cropping could remove important context.
    """
    from io import BytesIO
    from PIL import ImageChops

    with Image.open(BytesIO(image_bytes)).convert("RGB") as img:
        background = Image.new(img.mode, img.size, img.getpixel((0, 0)))
        diff = ImageChops.difference(img, background)
        bbox = diff.getbbox()
        if not bbox:
            return image_bytes

        left, top, right, bottom = bbox
        pad = 12
        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(img.width, right + pad)
        bottom = min(img.height, bottom + pad)

        cropped = img.crop((left, top, right, bottom))
        out = BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue()


def _short_title(value: str, fallback: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if not value:
        return fallback
    if len(value) > 90:
        return value[:87].rstrip() + "..."
    return value


def _hash_image(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()[:16]


CANDIDATE_JS = r"""
(args) => {
  const minWidth = args.minWidth;
  const minHeight = args.minHeight;
  const maxCandidates = args.maxCandidates;

  function cleanText(text, maxLength = 120) {
    if (!text) return "";
    const cleaned = String(text).replace(/\s+/g, " ").trim();
    return cleaned.length > maxLength ? cleaned.slice(0, maxLength - 3) + "..." : cleaned;
  }

  function cssPath(el) {
    if (!el || !el.tagName) return "";
    const parts = [];
    let current = el;

    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 7) {
      let part = current.tagName.toLowerCase();

      if (current.getAttribute("data-corporate-capture-id")) {
        part += `[data-corporate-capture-id="${current.getAttribute("data-corporate-capture-id")}"]`;
        parts.unshift(part);
        break;
      }

      if (current.id) {
        part += "#" + CSS.escape(current.id);
        parts.unshift(part);
        break;
      }

      const classes = Array.from(current.classList || []).slice(0, 2);
      if (classes.length) {
        part += "." + classes.map(c => CSS.escape(c)).join(".");
      }

      const parent = current.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter(x => x.tagName === current.tagName);
        if (siblings.length > 1) {
          part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
        }
      }

      parts.unshift(part);
      current = current.parentElement;
    }

    return parts.join(" > ");
  }

  function nearbyHeading(el) {
    let current = el;

    for (let depth = 0; depth < 5 && current; depth++) {
      const heading = current.querySelector && current.querySelector("h1,h2,h3,h4,h5,h6,[role='heading'],.title,.heading,.zc-title,.zanalytics-title");
      if (heading && heading.textContent) return cleanText(heading.textContent, 90);

      let previous = current.previousElementSibling;
      let checked = 0;
      while (previous && checked < 4) {
        if (/H[1-6]/.test(previous.tagName || "") || /title|heading/i.test(previous.className || "")) {
          const text = cleanText(previous.textContent, 90);
          if (text) return text;
        }
        previous = previous.previousElementSibling;
        checked++;
      }

      current = current.parentElement;
    }

    return "";
  }

  function elementKind(el) {
    const tag = (el.tagName || "").toLowerCase();
    const blob = `${tag} ${el.id || ""} ${el.className || ""} ${Array.from(el.getAttributeNames ? el.getAttributeNames() : []).join(" ")}`.toLowerCase();

    if (tag === "iframe") return "iframe";
    if (tag === "canvas") return "canvas_chart";
    if (tag === "svg") return "svg_chart";
    if (tag === "table") return "table";
    if (/pivot/.test(blob)) return "pivot_table";
    if (/kpi|metric|scorecard|card/.test(blob)) return "kpi_card";
    if (/chart|graph|visual|plot/.test(blob)) return "chart";
    if (/dashboard|widget|report|view/.test(blob)) return "report_widget";
    return "visual_candidate";
  }

  function scoreElement(el, rect) {
    const tag = (el.tagName || "").toLowerCase();
    const className = String(el.className || "");
    const id = String(el.id || "");
    const role = String(el.getAttribute("role") || "");
    const blob = `${tag} ${id} ${className} ${role}`.toLowerCase();
    let score = 0;

    if (tag === "iframe") score += 45;
    if (tag === "canvas") score += 45;
    if (tag === "svg") score += 35;
    if (tag === "table") score += 35;
    if (/chart|graph|plot|visual/.test(blob)) score += 35;
    if (/dashboard|widget|report|view/.test(blob)) score += 25;
    if (/pivot|table/.test(blob)) score += 25;
    if (/kpi|metric|scorecard|card/.test(blob)) score += 20;
    if (el.querySelector && el.querySelector("canvas,svg,table")) score += 25;
    if (el.querySelectorAll && el.querySelectorAll("canvas,svg").length > 0) score += 15;
    if (rect.width >= 450 && rect.height >= 250) score += 15;
    if (rect.width >= 700 && rect.height >= 350) score += 10;
    if (el.innerText && el.innerText.trim().length > 10) score += 5;

    // Avoid huge page containers unless they clearly look like a report widget.
    const viewportArea = window.innerWidth * window.innerHeight;
    const area = rect.width * rect.height;
    if (area > viewportArea * 1.6 && !/chart|widget|report|dashboard|view|iframe/.test(blob)) {
      score -= 35;
    }

    return score;
  }

  function isBadElement(el) {
    const tag = (el.tagName || "").toLowerCase();
    if (["html", "body", "script", "style", "meta", "link", "noscript"].includes(tag)) return true;
    const blob = `${tag} ${el.id || ""} ${el.className || ""}`.toLowerCase();
    if (/menu|navbar|sidebar|header|footer|toolbar|button|dropdown|modal|cookie|toast/.test(blob)) return true;
    return false;
  }

  const all = Array.from(document.querySelectorAll("*"));
  const raw = [];

  for (const el of all) {
    if (isBadElement(el)) continue;

    const rect = el.getBoundingClientRect();
    if (!rect || rect.width < minWidth || rect.height < minHeight) continue;
    if (rect.bottom < -100 || rect.right < -100) continue;

    const tag = (el.tagName || "").toLowerCase();
    const blob = `${tag} ${el.id || ""} ${el.className || ""} ${el.getAttribute("role") || ""}`.toLowerCase();

    const hasVisualChild = !!(el.querySelector && el.querySelector("canvas,svg,table,iframe"));
    const isDirectVisual = ["iframe", "canvas", "svg", "table"].includes(tag);
    const nameLooksVisual = /chart|graph|visual|dashboard|widget|report|view|pivot|table|kpi|metric|scorecard|card|zc|zanalytics/.test(blob);

    if (!isDirectVisual && !hasVisualChild && !nameLooksVisual) continue;

    const score = scoreElement(el, rect);
    if (score < 25) continue;

    raw.push({
      el,
      score,
      area: rect.width * rect.height,
      rect: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      },
      title: nearbyHeading(el),
      kind: elementKind(el),
      text: cleanText(el.innerText || el.textContent || "", 160)
    });
  }

  // Prefer meaningful children over giant duplicate parents.
  raw.sort((a, b) => b.score - a.score || b.area - a.area);

  const chosen = [];
  function overlaps(a, b) {
    const ax1 = a.rect.x, ay1 = a.rect.y, ax2 = a.rect.x + a.rect.width, ay2 = a.rect.y + a.rect.height;
    const bx1 = b.rect.x, by1 = b.rect.y, bx2 = b.rect.x + b.rect.width, by2 = b.rect.y + b.rect.height;
    const ix = Math.max(0, Math.min(ax2, bx2) - Math.max(ax1, bx1));
    const iy = Math.max(0, Math.min(ay2, by2) - Math.max(ay1, by1));
    const intersection = ix * iy;
    const minArea = Math.min(a.area, b.area);
    return minArea > 0 && intersection / minArea > 0.82;
  }

  for (const item of raw) {
    if (chosen.some(existing => overlaps(item, existing))) continue;
    chosen.push(item);
    if (chosen.length >= maxCandidates) break;
  }

  return chosen.map((item, index) => {
    const captureId = `corp-capture-${Date.now()}-${index}`;
    item.el.setAttribute("data-corporate-capture-id", captureId);

    return {
      capture_id: captureId,
      selector: `[data-corporate-capture-id="${captureId}"]`,
      kind: item.kind,
      confidence_score: item.score,
      title: item.title || item.text || "",
      width: item.rect.width,
      height: item.rect.height,
      x: item.rect.x,
      y: item.rect.y,
      text: item.text,
      tag: item.el.tagName
    };
  });
}
"""


def _scroll_page(page: Any) -> None:
    page.evaluate(
        """
        async () => {
          await new Promise(resolve => {
            let totalHeight = 0;
            const distance = 650;
            const delay = 130;

            const timer = setInterval(() => {
              const scrollHeight = Math.max(
                document.body.scrollHeight || 0,
                document.documentElement.scrollHeight || 0
              );

              window.scrollBy(0, distance);
              totalHeight += distance;

              if (totalHeight >= scrollHeight + 1500) {
                clearInterval(timer);
                window.scrollTo(0, 0);
                resolve();
              }
            }, delay);
          });
        }
        """
    )


def capture_visuals_from_url(
    url: str,
    *,
    page_index: int = 1,
    options: Optional[CaptureOptions] = None,
) -> List[VisualCapture]:
    """
    Render a Zoho Analytics link and screenshot likely visualizations/widgets/tables.

    This captures visible rendered output. It does not bypass Zoho authentication.
    """
    options = options or CaptureOptions()
    url = validate_zoho_url(url)

    warning = ensure_chromium_installed()
    if warning:
        raise RuntimeError(warning)

    from playwright.sync_api import sync_playwright

    captured: List[VisualCapture] = []
    seen_hashes: set[str] = set()
    captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--font-render-hinting=medium",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1600, "height": 1200},
            device_scale_factor=1.5,
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=options.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=options.timeout_ms)
        except Exception:
            pass

        if options.wait_seconds > 0:
            page.wait_for_timeout(options.wait_seconds * 1000)

        try:
            _scroll_page(page)
            page.wait_for_timeout(1500)
        except Exception:
            pass

        frames = page.frames

        for frame in frames:
            if len(captured) >= options.max_visuals_per_link:
                break

            try:
                candidates = frame.evaluate(
                    CANDIDATE_JS,
                    {
                        "minWidth": options.min_width,
                        "minHeight": options.min_height,
                        "maxCandidates": max(1, options.max_visuals_per_link - len(captured)),
                    },
                )
            except Exception:
                continue

            for candidate in candidates:
                if len(captured) >= options.max_visuals_per_link:
                    break

                selector = candidate.get("selector", "")
                if not selector:
                    continue

                try:
                    locator = frame.locator(selector).first
                    locator.scroll_into_view_if_needed(timeout=10_000)
                    image_bytes = locator.screenshot(type="png", timeout=30_000)
                    if options.crop_whitespace:
                        image_bytes = _trim_whitespace(image_bytes)

                    width, height = _image_dimensions(image_bytes)
                    if width < options.min_width or height < options.min_height:
                        continue

                    image_hash = _hash_image(image_bytes)
                    if image_hash in seen_hashes:
                        continue
                    seen_hashes.add(image_hash)

                    visual_index = len(captured) + 1
                    title = _short_title(
                        candidate.get("title", ""),
                        fallback=f"Visualization {visual_index}",
                    )

                    visual_id = f"p{page_index}_v{visual_index}_{image_hash}"

                    captured.append(
                        VisualCapture(
                            visual_id=visual_id,
                            source_url=url,
                            title=title,
                            kind=candidate.get("kind", "visual_candidate"),
                            width=width,
                            height=height,
                            page_index=page_index,
                            visual_index=visual_index,
                            confidence_score=int(candidate.get("confidence_score", 0)),
                            selector=selector,
                            frame_url=frame.url,
                            image_bytes=image_bytes,
                            captured_at=captured_at,
                        )
                    )

                except Exception:
                    continue

        if options.include_full_page_fallback and len(captured) < options.full_page_if_less_than:
            try:
                image_bytes = page.screenshot(full_page=True, type="png", timeout=60_000)
                if options.crop_whitespace:
                    image_bytes = _trim_whitespace(image_bytes)

                width, height = _image_dimensions(image_bytes)
                image_hash = _hash_image(image_bytes)
                visual_id = f"p{page_index}_full_{image_hash}"

                captured.append(
                    VisualCapture(
                        visual_id=visual_id,
                        source_url=url,
                        title=f"Full Page Capture {page_index}",
                        kind="full_page_fallback",
                        width=width,
                        height=height,
                        page_index=page_index,
                        visual_index=len(captured) + 1,
                        confidence_score=1,
                        selector="full_page",
                        frame_url=page.url,
                        image_bytes=image_bytes,
                        captured_at=captured_at,
                    )
                )
            except Exception:
                pass

        browser.close()

    return captured
