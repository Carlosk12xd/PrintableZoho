from __future__ import annotations

import io
from typing import List

import pandas as pd
import streamlit as st

from report_builder import (
    ReportData,
    build_html_report,
    build_pdf_report,
    normalize_dataframe,
    safe_filename,
)
from scraper import ScrapeOptions, scrape_zoho_candidate_ids
from zoho_api import ZohoApiConfig, export_dashboard_as_pdf, export_view_as_csv


st.set_page_config(
    page_title="Zoho Analytics Report Builder",
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
        border-radius: 24px;
        background: linear-gradient(135deg, #eff6ff 0%, #ffffff 48%, #f8fafc 100%);
        border: 1px solid #dbeafe;
        box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
        margin-bottom: 1.3rem;
      }
      .hero-card h1 {
        margin: 0;
        font-size: 2.4rem;
        letter-spacing: -0.04em;
      }
      .hero-card p {
        color: #475467;
        font-size: 1.03rem;
        max-width: 980px;
        line-height: 1.6;
      }
      .small-muted {
        color: #667085;
        font-size: 0.9rem;
      }
      .report-section {
        border: 1px solid #e5e7eb;
        border-radius: 20px;
        padding: 1.1rem 1.2rem;
        background: #ffffff;
        margin-bottom: 1rem;
        box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
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
        .report-section {
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


def get_api_config() -> ZohoApiConfig:
    return ZohoApiConfig(
        server_uri=st.session_state.get("server_uri", "").strip(),
        org_id=st.session_state.get("org_id", "").strip(),
        workspace_id=st.session_state.get("workspace_id", "").strip(),
        access_token=st.session_state.get("access_token", "").strip(),
    )


def missing_api_fields(config: ZohoApiConfig) -> List[str]:
    missing = []
    if not config.server_uri:
        missing.append("Zoho Analytics API server URI")
    if not config.org_id:
        missing.append("Organization ID")
    if not config.workspace_id:
        missing.append("Workspace ID")
    if not config.access_token:
        missing.append("OAuth access token")
    return missing


def dataframe_to_excel_bytes(dfs: dict[str, pd.DataFrame]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name, df in dfs.items():
            sheet_name = safe_filename(name, "Sheet")[:31]
            df.to_excel(writer, index=False, sheet_name=sheet_name)
    output.seek(0)
    return output.getvalue()


# Sidebar

st.sidebar.header("Zoho API Credentials")
st.sidebar.text_input("Zoho Analytics API server URI", value="analyticsapi.zoho.com", key="server_uri")
st.sidebar.text_input("Organization ID", value="", key="org_id")
st.sidebar.text_input("Workspace ID", value="", key="workspace_id")
st.sidebar.text_input("OAuth access token", value="", type="password", key="access_token")

st.sidebar.markdown("---")
st.sidebar.header("Report Output")
report_title = st.sidebar.text_input("Report title", value="Zoho Analytics Printable Report")
paper = st.sidebar.selectbox("PDF paper size", ["Letter", "A4"], index=0)
orientation = st.sidebar.selectbox("PDF orientation", ["Landscape", "Portrait"], index=0)


# Header

st.markdown(
    """
    <div class="hero-card">
      <h1>Zoho Analytics Report Builder</h1>
      <p>
        Paste a Zoho Analytics open-view page, scrape candidate chart/report/view IDs,
        export selected IDs through the Zoho API, and rebuild a clean printable report
        with separate sections.
      </p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.warning(
    "The scraper finds candidate IDs from the rendered page. Some IDs may be internal dashboard/widget IDs, "
    "not valid API view IDs. The app lets you select IDs and test them through the Zoho Analytics API."
)


# Tabs

tab_scrape, tab_export, tab_upload, tab_native_pdf = st.tabs(
    [
        "1. Scrape chart/view IDs",
        "2. Export selected IDs as report data",
        "3. Upload exported data instead",
        "4. Native Zoho dashboard PDF",
    ]
)


with tab_scrape:
    st.subheader("Scrape candidate IDs from Zoho Analytics")

    url = st.text_input(
        "Zoho Analytics open-view URL",
        value="https://analytics.zoho.com/open-view/3251149000000069172",
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        wait_seconds = st.slider("Wait after page load", 1, 20, 5)
    with col2:
        timeout_seconds = st.slider("Page timeout", 15, 180, 60)
    with col3:
        scan_scripts = st.checkbox("Scan scripts", value=True)
    with col4:
        scan_iframes = st.checkbox("Scan iframes", value=True)

    st.caption(
        "Use a public/open Zoho Analytics link. For private reports, the official Zoho API path is more reliable than scraping."
    )

    if st.button("Scrape candidate IDs", type="primary"):
        with st.spinner("Opening the Zoho page with Playwright and scanning DOM, iframes, scripts, and network URLs..."):
            try:
                df = scrape_zoho_candidate_ids(
                    url,
                    ScrapeOptions(
                        wait_seconds=wait_seconds,
                        timeout_ms=timeout_seconds * 1000,
                        scan_scripts=scan_scripts,
                        scan_iframes=scan_iframes,
                    ),
                )
                st.session_state["candidate_ids"] = df
                if df.empty:
                    st.error("No candidate IDs were found.")
                else:
                    st.success(f"Found {len(df):,} unique candidate ID(s).")
            except Exception as exc:
                st.error(f"Scrape failed: {exc}")

    candidate_df = st.session_state.get("candidate_ids")
    if candidate_df is not None and not candidate_df.empty:
        st.markdown("### Review scraped IDs")
        st.write(
            "Keep the IDs that look like actual Zoho report/view IDs. "
            "High-confidence rows usually come from `open-view`, `viewId`, `/views/`, iframe sources, or network URLs."
        )

        edited = st.data_editor(
            candidate_df,
            use_container_width=True,
            height=520,
            num_rows="fixed",
            disabled=[
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
            ],
            key="candidate_editor",
        )

        st.session_state["candidate_ids"] = edited

        selected = edited[edited["selected"] == True].copy()
        st.info(f"{len(selected):,} ID(s) selected.")

        st.download_button(
            "Download scraped IDs CSV",
            data=edited.to_csv(index=False).encode("utf-8"),
            file_name="scraped_zoho_candidate_ids.csv",
            mime="text/csv",
        )


with tab_export:
    st.subheader("Export selected scraped IDs using the Zoho Analytics API")

    candidate_df = st.session_state.get("candidate_ids")
    if candidate_df is None or candidate_df.empty:
        st.warning("Scrape IDs first, or use the upload tab.")
    else:
        selected = candidate_df[candidate_df["selected"] == True].copy()
        if selected.empty:
            st.warning("No IDs selected. Go back to the scrape tab and select at least one candidate.")
        else:
            st.write("Selected IDs:")
            st.dataframe(
                selected[["candidate_id", "candidate_kind", "confidence_score", "pattern", "source_type"]],
                use_container_width=True,
            )

            criteria = st.text_input(
                "Optional Zoho criteria for all selected views",
                value="",
                help="Example: \"Date\" >= '2026-01-01'. Leave blank unless you know the Zoho criteria syntax you need.",
            )

            if st.button("Export selected IDs as data", type="primary"):
                config = get_api_config()
                missing = missing_api_fields(config)
                if missing:
                    st.error("Missing: " + ", ".join(missing))
                else:
                    reports: List[ReportData] = []
                    progress = st.progress(0)

                    for index, (_, row) in enumerate(selected.iterrows(), start=1):
                        view_id = str(row["candidate_id"]).strip()
                        label = f"Zoho View {view_id}"

                        try:
                            df = export_view_as_csv(
                                config,
                                view_id,
                                criteria=criteria.strip() or None,
                            )
                            reports.append(
                                ReportData(
                                    name=label,
                                    source=f"Zoho Analytics API view {view_id}",
                                    dataframe=df,
                                    notes=(
                                        f"Candidate kind: {row.get('candidate_kind', '')}. "
                                        f"Confidence score: {row.get('confidence_score', '')}. "
                                        f"Evidence: {row.get('pattern', '')}."
                                    ),
                                )
                            )
                            st.success(f"Exported {label}: {len(df):,} rows")
                        except Exception as exc:
                            st.error(f"Could not export ID {view_id}: {exc}")

                        progress.progress(index / max(1, len(selected)))

                    if reports:
                        st.session_state["reports"] = reports
                        st.success(f"Loaded {len(reports):,} report section(s).")


with tab_upload:
    st.subheader("Upload Zoho-exported CSV/XLSX files instead")
    st.write(
        "Use this path if the scraped IDs are not valid API view IDs yet. "
        "Export each chart/table from Zoho as CSV/XLSX, upload them here, and this app will build the printable report."
    )

    uploaded_files = st.file_uploader(
        "Upload CSV, XLSX, or XLS files",
        type=["csv", "xlsx", "xls"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        reports: List[ReportData] = []
        for uploaded in uploaded_files:
            try:
                if uploaded.name.lower().endswith(".csv"):
                    df = pd.read_csv(uploaded)
                else:
                    df = pd.read_excel(uploaded)

                df = normalize_dataframe(df)
                reports.append(
                    ReportData(
                        name=uploaded.name.rsplit(".", 1)[0],
                        source=uploaded.name,
                        dataframe=df,
                        notes="Uploaded Zoho export file.",
                    )
                )
            except Exception as exc:
                st.error(f"Could not read {uploaded.name}: {exc}")

        if reports:
            st.session_state["reports"] = reports
            st.success(f"Loaded {len(reports):,} uploaded report section(s).")


with tab_native_pdf:
    st.subheader("Ask Zoho to export the whole dashboard as a native PDF")
    st.write(
        "This does not rebuild the data section-by-section. It uses Zoho's own PDF export endpoint for a dashboard/view ID."
    )

    dashboard_id = st.text_input(
        "Dashboard/open-view ID",
        value="3251149000000069172",
        help="Paste only the numeric ID, or copy it from the open-view URL.",
    )
    each_report_new_page = st.checkbox("Each report in a new page", value=True)

    if st.button("Export native Zoho dashboard PDF"):
        config = get_api_config()
        missing = missing_api_fields(config)
        if missing:
            st.error("Missing: " + ", ".join(missing))
        else:
            try:
                pdf_bytes = export_dashboard_as_pdf(
                    config,
                    dashboard_id,
                    each_report_new_page=each_report_new_page,
                )
                st.download_button(
                    "Download Zoho native PDF",
                    data=pdf_bytes,
                    file_name="zoho_native_dashboard_export.pdf",
                    mime="application/pdf",
                    type="primary",
                )
            except Exception as exc:
                st.error(f"Native Zoho PDF export failed: {exc}")


# Report preview and downloads

st.markdown("---")
st.header("Printable Report Preview")

reports = st.session_state.get("reports", [])

if not reports:
    st.info("Export selected IDs through the API or upload CSV/XLSX files to generate the report.")
else:
    st.success(f"{len(reports):,} report section(s) ready.")

    all_dfs = {}
    for idx, report in enumerate(reports, start=1):
        st.markdown('<div class="report-section">', unsafe_allow_html=True)
        st.subheader(f"{idx}. {report.name}")
        st.caption(report.source)
        if report.notes:
            st.write(report.notes)

        summary = {
            "Rows": f"{len(report.dataframe):,}",
            "Columns": f"{len(report.dataframe.columns):,}",
        }
        metric_cols = st.columns(len(summary))
        for col, (key, value) in zip(metric_cols, summary.items()):
            col.metric(key, value)

        st.dataframe(report.dataframe, use_container_width=True, height=360)
        all_dfs[report.name] = report.dataframe

        st.download_button(
            f"Download {report.name} CSV",
            data=report.dataframe.to_csv(index=False).encode("utf-8"),
            file_name=f"{safe_filename(report.name)}.csv",
            mime="text/csv",
            key=f"download_section_csv_{idx}",
        )

        st.markdown("</div>", unsafe_allow_html=True)

    html_report = build_html_report(reports, report_title)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.download_button(
            "Download printable HTML report",
            data=html_report.encode("utf-8"),
            file_name="zoho_printable_report.html",
            mime="text/html",
            type="primary",
        )

    with col2:
        try:
            pdf_report = build_pdf_report(
                reports,
                report_title,
                paper=paper,
                orientation=orientation,
            )
            st.download_button(
                "Download PDF report",
                data=pdf_report,
                file_name="zoho_printable_report.pdf",
                mime="application/pdf",
                type="primary",
            )
        except Exception as exc:
            st.error(f"PDF generation failed: {exc}")

    with col3:
        excel_bytes = dataframe_to_excel_bytes(all_dfs)
        st.download_button(
            "Download all data as Excel",
            data=excel_bytes,
            file_name="zoho_report_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with st.expander("Generated printable HTML"):
        st.code(html_report, language="html")
