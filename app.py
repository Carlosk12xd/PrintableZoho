from __future__ import annotations

import base64
import io
import zipfile
from typing import Dict, List

import pandas as pd
import streamlit as st

from corporate_pdf import PdfVisual, build_corporate_pdf
from zoho_capture import CaptureOptions, VisualCapture, capture_visuals_from_url


st.set_page_config(
    page_title="Zoho Corporate Report Builder",
    page_icon="📊",
    layout="wide",
)


st.markdown(
    """
    <style>
      .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1500px;
      }

      .hero-card {
        padding: 2rem;
        border-radius: 26px;
        background: linear-gradient(135deg, #eff6ff 0%, #ffffff 45%, #f8fafc 100%);
        border: 1px solid #dbeafe;
        box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
        margin-bottom: 1.25rem;
      }

      .hero-card h1 {
        margin: 0;
        font-size: 2.5rem;
        letter-spacing: -0.05em;
        color: #0f172a;
      }

      .hero-card p {
        color: #475467;
        font-size: 1.05rem;
        max-width: 1000px;
        line-height: 1.62;
      }

      .visual-card {
        border: 1px solid #e5e7eb;
        border-radius: 20px;
        background: #ffffff;
        padding: 1rem;
        box-shadow: 0 12px 32px rgba(15, 23, 42, 0.06);
        margin-bottom: 1rem;
      }

      .small-muted {
        color: #667085;
        font-size: 0.9rem;
      }

      .step-badge {
        display: inline-block;
        border-radius: 999px;
        padding: 0.25rem 0.7rem;
        background: #dbeafe;
        color: #1e40af;
        font-size: 0.8rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
      }

      @media print {
        header, footer, [data-testid="stSidebar"], [data-testid="stToolbar"],
        [data-testid="stDecoration"], [data-testid="stStatusWidget"], .stButton,
        .stDownloadButton, .stTabs, .stExpander, .stAlert {
          display: none !important;
        }

        .main .block-container {
          max-width: 100% !important;
          padding: 0 !important;
        }

        .visual-card {
          page-break-inside: avoid;
          break-inside: avoid;
          box-shadow: none !important;
          border: 1px solid #d0d5dd;
        }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_links_from_text(text: str) -> List[str]:
    links = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        links.append(line)
    return links


def visual_metadata_dataframe(visuals: List[VisualCapture]) -> pd.DataFrame:
    rows = []
    for index, visual in enumerate(visuals, start=1):
        rows.append(
            {
                "selected": True,
                "order": index,
                "visual_id": visual.visual_id,
                "title": visual.title,
                "kind": visual.kind,
                "source_url": visual.source_url,
                "width": visual.width,
                "height": visual.height,
                "confidence_score": visual.confidence_score,
                "notes": "",
            }
        )
    return pd.DataFrame(rows)


def create_images_zip(visuals: List[VisualCapture], selected_ids: List[str]) -> bytes:
    selected_set = set(selected_ids)
    output = io.BytesIO()

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for visual in visuals:
            if visual.visual_id not in selected_set:
                continue
            safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in visual.title)[:60]
            filename = f"{visual.visual_index:02d}_{safe_title or visual.visual_id}.png"
            z.writestr(filename, visual.image_bytes)

    output.seek(0)
    return output.getvalue()


def image_download_link(image_bytes: bytes, filename: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f'<a href="data:image/png;base64,{encoded}" download="{filename}">Download PNG</a>'


# Sidebar settings

st.sidebar.header("Corporate PDF Settings")
report_title = st.sidebar.text_input("Report title", value="Zoho Analytics Corporate Report")
client_name = st.sidebar.text_input("Client / corporation name", value="")
company_name = st.sidebar.text_input("Your company / department", value="")
prepared_by = st.sidebar.text_input("Prepared by", value="")
paper = st.sidebar.selectbox("Paper size", ["Letter", "A4"], index=0)
orientation = st.sidebar.selectbox("Orientation", ["Landscape", "Portrait"], index=0)
layout = st.sidebar.selectbox("PDF layout", ["One visual per page", "Two visuals per page"], index=0)
include_source_links = st.sidebar.checkbox("Include source links in PDF", value=True)

logo_file = st.sidebar.file_uploader("Optional logo", type=["png", "jpg", "jpeg"])
logo_bytes = logo_file.read() if logo_file is not None else None

executive_summary = st.sidebar.text_area(
    "Executive summary / cover notes",
    value="",
    height=120,
    placeholder="Optional summary that appears on the PDF cover page.",
)

st.sidebar.markdown("---")
st.sidebar.header("Capture Settings")
wait_seconds = st.sidebar.slider("Wait after page load", 2, 25, 7)
timeout_seconds = st.sidebar.slider("Page timeout", 30, 180, 90)
max_visuals_per_link = st.sidebar.slider("Max visuals per link", 3, 60, 24)
min_width = st.sidebar.slider("Minimum visual width", 120, 600, 220)
min_height = st.sidebar.slider("Minimum visual height", 80, 400, 120)
include_full_page_fallback = st.sidebar.checkbox("Use full-page fallback", value=True)
full_page_if_less_than = st.sidebar.slider("Fallback if fewer visuals than", 0, 5, 1)
crop_whitespace = st.sidebar.checkbox("Try to crop whitespace", value=False)


# Header

st.markdown(
    """
    <div class="hero-card">
      <div class="step-badge">Zoho Analytics → Corporate PDF</div>
      <h1>Build client-ready reports from Zoho Analytics links</h1>
      <p>
        Paste public or authorized Zoho Analytics links. The app renders each page,
        captures charts, tables, KPI cards, and dashboard widgets as images,
        then compiles them into a polished PDF you can present to corporations.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.info(
    "This version focuses on importing the graphics/visualizations exactly as they appear in Zoho. "
    "It does not bypass Zoho permissions. If a link requires login, use a public/open-view link or add an authenticated capture workflow later."
)


tab_capture, tab_review, tab_export, tab_help = st.tabs(
    ["1. Capture Zoho visuals", "2. Review and organize", "3. Export corporate PDF", "How it works"]
)


with tab_capture:
    st.subheader("Paste Zoho Analytics links")

    default_link = "https://analytics.zoho.com/open-view/3251149000000069172"
    links_text = st.text_area(
        "One Zoho Analytics link per line",
        value=default_link,
        height=140,
    )

    links = get_links_from_text(links_text)

    col1, col2 = st.columns([1, 3])
    with col1:
        capture_clicked = st.button("Capture visualizations", type="primary", use_container_width=True)
    with col2:
        st.caption(
            "The app will render every link, scroll the page to trigger lazy-loaded charts, detect visual elements, "
            "and screenshot each visualization/card/table it can find."
        )

    if capture_clicked:
        if not links:
            st.error("Paste at least one Zoho Analytics link.")
        else:
            options = CaptureOptions(
                wait_seconds=wait_seconds,
                timeout_ms=timeout_seconds * 1000,
                max_visuals_per_link=max_visuals_per_link,
                min_width=min_width,
                min_height=min_height,
                include_full_page_fallback=include_full_page_fallback,
                full_page_if_less_than=full_page_if_less_than,
                crop_whitespace=crop_whitespace,
            )

            all_visuals: List[VisualCapture] = []
            progress = st.progress(0)

            for page_index, link in enumerate(links, start=1):
                with st.spinner(f"Capturing visuals from link {page_index} of {len(links)}..."):
                    try:
                        captures = capture_visuals_from_url(
                            link,
                            page_index=page_index,
                            options=options,
                        )
                        all_visuals.extend(captures)
                        st.success(f"Captured {len(captures)} visual(s) from link {page_index}.")
                    except Exception as exc:
                        st.error(f"Could not capture link {page_index}: {exc}")

                progress.progress(page_index / len(links))

            if all_visuals:
                st.session_state["visuals"] = all_visuals
                st.session_state["visual_metadata"] = visual_metadata_dataframe(all_visuals)
                st.success(f"Total captured visuals: {len(all_visuals)}")
            else:
                st.error("No visuals were captured. Try increasing wait time, enabling full-page fallback, or using a public/open Zoho link.")

    visuals = st.session_state.get("visuals", [])
    if visuals:
        st.markdown("### Latest capture preview")
        preview_cols = st.columns(3)
        for idx, visual in enumerate(visuals[:6]):
            with preview_cols[idx % 3]:
                st.image(visual.image_bytes, caption=f"{visual.title} ({visual.kind})", use_container_width=True)


with tab_review:
    st.subheader("Review, rename, select, and reorder visuals")

    visuals: List[VisualCapture] = st.session_state.get("visuals", [])
    metadata = st.session_state.get("visual_metadata")

    if not visuals or metadata is None:
        st.warning("Capture visuals first.")
    else:
        edited = st.data_editor(
            metadata,
            use_container_width=True,
            height=420,
            num_rows="fixed",
            column_config={
                "selected": st.column_config.CheckboxColumn("Include"),
                "order": st.column_config.NumberColumn("Order", min_value=1, step=1),
                "title": st.column_config.TextColumn("PDF section title"),
                "notes": st.column_config.TextColumn("Optional notes"),
            },
            disabled=["visual_id", "kind", "source_url", "width", "height", "confidence_score"],
            key="visual_review_editor",
        )

        st.session_state["visual_metadata"] = edited

        selected_count = int((edited["selected"] == True).sum())
        st.success(f"{selected_count} visual(s) selected for the PDF.")

        visual_map: Dict[str, VisualCapture] = {visual.visual_id: visual for visual in visuals}

        st.markdown("### Visual preview")
        for _, row in edited.sort_values("order").iterrows():
            if not row.get("selected", True):
                continue
            visual = visual_map.get(row["visual_id"])
            if not visual:
                continue

            st.markdown('<div class="visual-card">', unsafe_allow_html=True)
            st.markdown(f"#### {int(row['order'])}. {row['title']}")
            st.caption(f"{row['kind']} • {row['width']}×{row['height']} • score {row['confidence_score']}")
            st.image(visual.image_bytes, use_container_width=True)
            if row.get("notes"):
                st.write(row["notes"])
            st.markdown(
                image_download_link(visual.image_bytes, f"{visual.visual_id}.png"),
                unsafe_allow_html=True,
            )
            st.markdown("</div>", unsafe_allow_html=True)


with tab_export:
    st.subheader("Export corporate-ready files")

    visuals: List[VisualCapture] = st.session_state.get("visuals", [])
    metadata = st.session_state.get("visual_metadata")

    if not visuals or metadata is None:
        st.warning("Capture and review visuals first.")
    else:
        visual_map: Dict[str, VisualCapture] = {visual.visual_id: visual for visual in visuals}
        selected_rows = metadata[metadata["selected"] == True].sort_values("order")

        if selected_rows.empty:
            st.error("No visuals selected.")
        else:
            pdf_visuals: List[PdfVisual] = []

            for _, row in selected_rows.iterrows():
                visual = visual_map.get(row["visual_id"])
                if not visual:
                    continue

                pdf_visuals.append(
                    PdfVisual(
                        title=str(row["title"]).strip() or visual.title,
                        source_url=visual.source_url,
                        kind=visual.kind,
                        image_bytes=visual.image_bytes,
                        notes=str(row.get("notes", "") or ""),
                    )
                )

            col1, col2 = st.columns(2)

            with col1:
                if st.button("Generate corporate PDF", type="primary", use_container_width=True):
                    try:
                        pdf_bytes = build_corporate_pdf(
                            visuals=pdf_visuals,
                            report_title=report_title,
                            client_name=client_name,
                            company_name=company_name,
                            prepared_by=prepared_by,
                            executive_summary=executive_summary,
                            logo_bytes=logo_bytes,
                            paper=paper,
                            orientation=orientation,
                            layout=layout,
                            include_source_links=include_source_links,
                        )
                        st.session_state["latest_pdf"] = pdf_bytes
                        st.success("Corporate PDF generated.")
                    except Exception as exc:
                        st.error(f"PDF generation failed: {exc}")

            with col2:
                selected_ids = [row["visual_id"] for _, row in selected_rows.iterrows()]
                images_zip = create_images_zip(visuals, selected_ids)
                st.download_button(
                    "Download selected visuals as PNG zip",
                    data=images_zip,
                    file_name="zoho_captured_visuals.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

            latest_pdf = st.session_state.get("latest_pdf")
            if latest_pdf:
                st.download_button(
                    "Download corporate PDF",
                    data=latest_pdf,
                    file_name="zoho_corporate_report.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )

            st.markdown("### Selected visuals going into PDF")
            st.dataframe(
                selected_rows[["order", "title", "kind", "source_url", "width", "height", "confidence_score"]],
                use_container_width=True,
            )


with tab_help:
    st.subheader("Recommended architecture for your goal")

    st.markdown(
        """
        Your stated goal is to turn Zoho Analytics links into a readable, corporate-ready PDF.
        That means the app should focus on visual capture first.

        **Best flow:**

        1. Render each Zoho Analytics link with Playwright.
        2. Detect charts, tables, KPI cards, canvases, SVGs, and iframes.
        3. Screenshot each visual element individually.
        4. Let the user rename and organize the visuals.
        5. Build a clean PDF with cover page, captions, source links, and one visual per page.
        6. Add a fallback full-page screenshot when Zoho hides charts inside containers that are hard to isolate.

        **Why not only webscrape IDs?**

        Scraped IDs are useful, but they do not guarantee access to the rendered visualization or raw data.
        Zoho pages can include dashboard IDs, widget IDs, view IDs, internal component IDs, cache IDs, and workspace IDs.
        Screenshots are more reliable for producing presentation-ready PDFs.

        **Future upgrade path:**

        Add Zoho OAuth login and official API export. Then the app can combine:
        - original Zoho graphics from screenshots
        - raw data tables from API exports
        - automatically generated summaries
        - branded corporate PDF templates
        """
    )
