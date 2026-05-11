from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import pandas as pd


ALLOWED_ZOHO_HOST_FRAGMENTS = (
    "analytics.zoho.com",
    "analytics.zoho.eu",
    "analytics.zoho.in",
    "analytics.zoho.com.au",
    "analytics.zoho.jp",
    "analytics.zoho.ca",
)


@dataclass
class ScrapeOptions:
    wait_seconds: int = 5
    timeout_ms: int = 60000
    scan_scripts: bool = True
    scan_iframes: bool = True
    max_script_chars: int = 800_000


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
            "This app only scrapes Zoho Analytics URLs. "
            "Use a link like https://analytics.zoho.com/open-view/..."
        )

    return url


def ensure_chromium_installed() -> Optional[str]:
    """
    Verify Playwright Chromium can launch.
    If not, attempt to install Chromium.

    Returns None if OK, otherwise returns a warning/error message.
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
                timeout=240,
            )
            if result.returncode != 0:
                return (
                    "Could not auto-install Playwright Chromium. "
                    f"Original error: {first_error}. "
                    f"Install output: {result.stderr[-1000:]}"
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


def extract_ids_from_text(text: str) -> List[Dict[str, str]]:
    """
    Extract likely Zoho report/view/chart IDs from a string.

    Returns dicts with candidate_id and pattern.
    """
    if not text:
        return []

    patterns = [
        ("open_view_url", r"/open-view/(\d{8,})"),
        ("view_id_key", r"(?:viewId|viewID|view_id|view-id|viewid)\D{0,10}(\d{8,})"),
        ("report_id_key", r"(?:reportId|reportID|report_id|report-id|reportid)\D{0,10}(\d{8,})"),
        ("chart_id_key", r"(?:chartId|chartID|chart_id|chart-id|chartid)\D{0,10}(\d{8,})"),
        ("dashboard_id_key", r"(?:dashboardId|dashboardID|dashboard_id|dashboard-id|dashboardid)\D{0,10}(\d{8,})"),
        ("workspace_id_key", r"(?:workspaceId|workspaceID|workspace_id|workspace-id|workspaceid)\D{0,10}(\d{8,})"),
        ("generic_long_number", r"\b(\d{12,})\b"),
    ]

    found: List[Dict[str, str]] = []
    for pattern_name, pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            candidate = match.group(1)
            found.append({"candidate_id": candidate, "pattern": pattern_name})

    return found


def _score_candidate(row: Dict[str, Any]) -> int:
    score = 0

    blob = " ".join(
        str(row.get(k, "") or "")
        for k in [
            "pattern",
            "attribute_name",
            "attribute_value",
            "tag",
            "selector",
            "source_type",
            "source_url",
            "nearby_heading",
            "text",
        ]
    ).lower()

    if "open-view" in blob:
        score += 30
    if "viewid" in blob or "view_id" in blob or "view-id" in blob or "view id" in blob:
        score += 25
    if "reportid" in blob or "report_id" in blob or "report-id" in blob:
        score += 18
    if "chartid" in blob or "chart_id" in blob or "chart-id" in blob:
        score += 14
    if "dashboardid" in blob or "dashboard_id" in blob or "dashboard-id" in blob:
        score += 10
    if "iframe" in blob:
        score += 8
    if "network" in blob:
        score += 6
    if "restapi" in blob or "/views/" in blob:
        score += 15
    if "script" in blob:
        score += 3

    candidate = str(row.get("candidate_id", ""))
    if len(candidate) >= 12:
        score += 5
    if len(candidate) >= 16:
        score += 5

    return score


def _classify_candidate(row: Dict[str, Any]) -> str:
    blob = " ".join(
        str(row.get(k, "") or "")
        for k in ["pattern", "attribute_name", "attribute_value", "source_url", "source_type"]
    ).lower()

    if "open-view" in blob:
        return "open_view_or_view_id"
    if "viewid" in blob or "view_id" in blob or "view-id" in blob or "/views/" in blob:
        return "likely_view_id"
    if "reportid" in blob or "report_id" in blob or "report-id" in blob:
        return "likely_report_id"
    if "chartid" in blob or "chart_id" in blob or "chart-id" in blob:
        return "chart_or_widget_id"
    if "dashboardid" in blob or "dashboard_id" in blob or "dashboard-id" in blob:
        return "dashboard_id"
    if "workspace" in blob:
        return "workspace_id"
    return "numeric_id_candidate"


def _dedupe_candidates(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "selected",
                "candidate_id",
                "candidate_kind",
                "confidence_score",
                "evidence_count",
                "pattern",
                "source_type",
                "source_url",
                "tag",
                "attribute_name",
                "nearby_heading",
                "text",
                "selector",
            ]
        )

    enriched = []
    for row in rows:
        row = dict(row)
        row["confidence_score"] = _score_candidate(row)
        row["candidate_kind"] = _classify_candidate(row)
        enriched.append(row)

    grouped: Dict[str, Dict[str, Any]] = {}
    for row in enriched:
        key = str(row["candidate_id"])
        existing = grouped.get(key)
        if existing is None or row["confidence_score"] > existing["confidence_score"]:
            grouped[key] = dict(row)
            grouped[key]["evidence_count"] = 1
            grouped[key]["all_patterns"] = {row.get("pattern", "")}
            grouped[key]["all_source_types"] = {row.get("source_type", "")}
        else:
            existing["evidence_count"] += 1
            existing["confidence_score"] = max(existing["confidence_score"], row["confidence_score"])
            existing.setdefault("all_patterns", set()).add(row.get("pattern", ""))
            existing.setdefault("all_source_types", set()).add(row.get("source_type", ""))

    final_rows = []
    for row in grouped.values():
        row["pattern"] = ", ".join(sorted(p for p in row.get("all_patterns", set()) if p))
        row["source_type"] = ", ".join(sorted(s for s in row.get("all_source_types", set()) if s))
        row.pop("all_patterns", None)
        row.pop("all_source_types", None)
        row["selected"] = row["candidate_kind"] in {
            "likely_view_id",
            "open_view_or_view_id",
            "likely_report_id",
        }
        final_rows.append(row)

    df = pd.DataFrame(final_rows)
    preferred_cols = [
        "selected",
        "candidate_id",
        "candidate_kind",
        "confidence_score",
        "evidence_count",
        "pattern",
        "source_type",
        "source_url",
        "tag",
        "attribute_name",
        "nearby_heading",
        "text",
        "selector",
        "attribute_value",
    ]

    for col in preferred_cols:
        if col not in df.columns:
            df[col] = ""

    return (
        df[preferred_cols]
        .sort_values(["confidence_score", "evidence_count"], ascending=False)
        .reset_index(drop=True)
    )


DOM_SCAN_JS = r"""
(args) => {
  const scanScripts = args.scanScripts;
  const maxScriptChars = args.maxScriptChars;

  function truncate(value, limit = 220) {
    if (value === null || value === undefined) return "";
    const text = String(value).replace(/\s+/g, " ").trim();
    return text.length > limit ? text.slice(0, limit) + "..." : text;
  }

  function extractIds(text) {
    if (!text) return [];
    const results = [];
    const patterns = [
      ["open_view_url", /\/open-view\/(\d{8,})/gi],
      ["view_id_key", /(?:viewId|viewID|view_id|view-id|viewid)\D{0,10}(\d{8,})/gi],
      ["report_id_key", /(?:reportId|reportID|report_id|report-id|reportid)\D{0,10}(\d{8,})/gi],
      ["chart_id_key", /(?:chartId|chartID|chart_id|chart-id|chartid)\D{0,10}(\d{8,})/gi],
      ["dashboard_id_key", /(?:dashboardId|dashboardID|dashboard_id|dashboard-id|dashboardid)\D{0,10}(\d{8,})/gi],
      ["workspace_id_key", /(?:workspaceId|workspaceID|workspace_id|workspace-id|workspaceid)\D{0,10}(\d{8,})/gi],
      ["generic_long_number", /\b(\d{12,})\b/g]
    ];

    for (const [name, pattern] of patterns) {
      let match;
      while ((match = pattern.exec(text)) !== null) {
        results.push({ candidate_id: match[1], pattern: name });
      }
    }
    return results;
  }

  function cssPath(el) {
    if (!el || !el.tagName) return "";
    const parts = [];
    let current = el;
    while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 6) {
      let part = current.tagName.toLowerCase();
      if (current.id) {
        part += "#" + CSS.escape(current.id);
        parts.unshift(part);
        break;
      }
      const cls = Array.from(current.classList || []).slice(0, 2);
      if (cls.length) part += "." + cls.map(c => CSS.escape(c)).join(".");
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
      const heading = current.querySelector && current.querySelector("h1,h2,h3,h4,h5,h6,[role='heading'],.title,.heading");
      if (heading && heading.textContent) return truncate(heading.textContent, 160);
      current = current.parentElement;
    }
    return "";
  }

  const rows = [];
  const interestingAttrNames = /(id|view|report|chart|dashboard|workspace|widget|zanalytics|zuid|src|href|name|data)/i;
  const interestingTags = new Set(["IFRAME", "CANVAS", "SVG", "TABLE"]);

  const elements = Array.from(document.querySelectorAll("*"));
  for (const el of elements) {
    const tag = el.tagName;
    const selector = cssPath(el);
    const text = truncate(el.innerText || el.textContent || "", 180);
    const heading = nearbyHeading(el);

    let attrNames = [];
    try { attrNames = el.getAttributeNames ? el.getAttributeNames() : []; } catch (_) {}

    for (const attrName of attrNames) {
      const attrValue = el.getAttribute(attrName) || "";
      if (!interestingAttrNames.test(attrName) && !/open-view|viewId|reportId|chartId|\d{12,}/i.test(attrValue)) {
        continue;
      }

      for (const hit of extractIds(attrValue)) {
        rows.push({
          ...hit,
          source_type: "dom_attribute",
          source_url: window.location.href,
          tag,
          attribute_name: attrName,
          attribute_value: truncate(attrValue, 300),
          selector,
          nearby_heading: heading,
          text
        });
      }
    }

    const classAndId = `${el.id || ""} ${el.className || ""}`;
    if (interestingTags.has(tag) || /(chart|report|view|widget|dashboard|pivot|table)/i.test(classAndId)) {
      const outer = truncate(el.outerHTML || "", 2500);
      for (const hit of extractIds(outer)) {
        rows.push({
          ...hit,
          source_type: "dom_element",
          source_url: window.location.href,
          tag,
          attribute_name: "",
          attribute_value: "",
          selector,
          nearby_heading: heading,
          text
        });
      }
    }
  }

  if (scanScripts) {
    let seenChars = 0;
    const scripts = Array.from(document.querySelectorAll("script"));
    for (const script of scripts) {
      const scriptText = script.textContent || "";
      if (!scriptText) continue;
      if (seenChars > maxScriptChars) break;
      const chunk = scriptText.slice(0, Math.max(0, maxScriptChars - seenChars));
      seenChars += chunk.length;

      for (const hit of extractIds(chunk)) {
        rows.push({
          ...hit,
          source_type: "script",
          source_url: window.location.href,
          tag: "SCRIPT",
          attribute_name: "",
          attribute_value: "",
          selector: "script",
          nearby_heading: "",
          text: ""
        });
      }
    }
  }

  return rows;
}
"""


def scrape_zoho_candidate_ids(url: str, options: Optional[ScrapeOptions] = None) -> pd.DataFrame:
    """
    Scrape candidate Zoho view/report/chart IDs from a rendered Zoho Analytics page.

    This does not bypass permissions. It can only read what the page/browser can load.
    """
    options = options or ScrapeOptions()
    url = validate_zoho_url(url)

    warning = ensure_chromium_installed()
    if warning:
        raise RuntimeError(warning)

    from playwright.sync_api import sync_playwright

    network_urls: List[str] = []
    rows: List[Dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1600, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        def remember_url(request_or_response: Any) -> None:
            try:
                request_url = request_or_response.url
                if request_url and "zoho" in request_url.lower():
                    network_urls.append(request_url)
            except Exception:
                pass

        page.on("request", remember_url)
        page.on("response", remember_url)

        page.goto(url, wait_until="domcontentloaded", timeout=options.timeout_ms)

        try:
            page.wait_for_load_state("networkidle", timeout=options.timeout_ms)
        except Exception:
            pass

        if options.wait_seconds > 0:
            page.wait_for_timeout(options.wait_seconds * 1000)

        # Scroll through the page to force lazy-loaded charts/widgets to render.
        try:
            page.evaluate(
                """
                async () => {
                  await new Promise(resolve => {
                    let totalHeight = 0;
                    const distance = 600;
                    const timer = setInterval(() => {
                      const scrollHeight = document.body.scrollHeight || document.documentElement.scrollHeight;
                      window.scrollBy(0, distance);
                      totalHeight += distance;
                      if(totalHeight >= scrollHeight + 1200){
                        clearInterval(timer);
                        window.scrollTo(0, 0);
                        resolve();
                      }
                    }, 150);
                  });
                }
                """
            )
            page.wait_for_timeout(1200)
        except Exception:
            pass

        frames = page.frames if options.scan_iframes else [page.main_frame]
        for frame in frames:
            try:
                frame_rows = frame.evaluate(
                    DOM_SCAN_JS,
                    {
                        "scanScripts": options.scan_scripts,
                        "maxScriptChars": options.max_script_chars,
                    },
                )
                rows.extend(frame_rows)
            except Exception:
                continue

        # Also scan final HTML and network URLs from Python.
        try:
            content = page.content()
            for hit in extract_ids_from_text(content):
                rows.append(
                    {
                        **hit,
                        "source_type": "page_html",
                        "source_url": page.url,
                        "tag": "HTML",
                        "attribute_name": "",
                        "attribute_value": "",
                        "selector": "",
                        "nearby_heading": "",
                        "text": "",
                    }
                )
        except Exception:
            pass

        browser.close()

    for network_url in network_urls:
        for hit in extract_ids_from_text(network_url):
            rows.append(
                {
                    **hit,
                    "source_type": "network_url",
                    "source_url": network_url[:500],
                    "tag": "",
                    "attribute_name": "",
                    "attribute_value": network_url[:500],
                    "selector": "",
                    "nearby_heading": "",
                    "text": "",
                }
            )

    return _dedupe_candidates(rows)
