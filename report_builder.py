from __future__ import annotations

import base64
import io
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4, letter, landscape, portrait
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
except Exception:
    colors = None


@dataclass
class ReportData:
    name: str
    source: str
    dataframe: pd.DataFrame
    notes: str = ""


def safe_filename(name: str, fallback: str = "report") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", name or "").strip("_")
    return cleaned or fallback


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    for col in df.columns:
        if df[col].dtype == "object":
            cleaned = (
                df[col]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )
            numeric = pd.to_numeric(cleaned, errors="coerce")
            if numeric.notna().sum() >= max(1, len(df) * 0.65):
                df[col] = numeric

    return df


def infer_numeric_columns(df: pd.DataFrame) -> List[str]:
    numeric_cols = []
    for col in df.columns:
        converted = pd.to_numeric(df[col], errors="coerce")
        if converted.notna().sum() > 0 and converted.notna().sum() >= max(1, len(df) * 0.5):
            numeric_cols.append(col)
    return numeric_cols


def infer_dimension_columns(df: pd.DataFrame) -> List[str]:
    numeric = set(infer_numeric_columns(df))
    dimensions = []
    for col in df.columns:
        if col not in numeric:
            unique_count = df[col].nunique(dropna=True)
            if 1 <= unique_count <= 60:
                dimensions.append(col)
    return dimensions


def dataframe_summary(df: pd.DataFrame) -> Dict[str, str]:
    summary = {
        "Rows": f"{len(df):,}",
        "Columns": f"{len(df.columns):,}",
    }

    numeric_cols = infer_numeric_columns(df)
    for numeric_col in numeric_cols[:2]:
        numeric_series = pd.to_numeric(df[numeric_col], errors="coerce")
        summary[f"Total {numeric_col}"] = f"{numeric_series.sum():,.2f}"
        summary[f"Avg {numeric_col}"] = f"{numeric_series.mean():,.2f}"

    return summary


def make_chart(df: pd.DataFrame, title: str, max_rows: int = 15) -> Optional[bytes]:
    if plt is None or df.empty:
        return None

    numeric_cols = infer_numeric_columns(df)
    dimension_cols = infer_dimension_columns(df)

    if not numeric_cols or not dimension_cols:
        return None

    dim = dimension_cols[0]
    metric = numeric_cols[0]

    plot_df = df[[dim, metric]].copy()
    plot_df[metric] = pd.to_numeric(plot_df[metric], errors="coerce")
    plot_df = plot_df.dropna(subset=[metric])

    if plot_df.empty:
        return None

    plot_df = plot_df.groupby(dim, dropna=False)[metric].sum().sort_values(ascending=False).head(max_rows)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    plot_df.sort_values().plot(kind="barh", ax=ax)
    ax.set_title(title)
    ax.set_xlabel(metric)
    ax.set_ylabel(dim)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


def build_html_report(reports: List[ReportData], report_title: str) -> str:
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    sections = []
    for idx, report in enumerate(reports, start=1):
        df = report.dataframe.copy()
        preview_df = df.head(100)
        summary = dataframe_summary(df)
        chart_bytes = make_chart(df, report.name)

        metric_html = "".join(
            f"""
            <div class="metric">
              <div class="metric-label">{key}</div>
              <div class="metric-value">{value}</div>
            </div>
            """
            for key, value in summary.items()
        )

        chart_html = ""
        if chart_bytes:
            chart_b64 = base64.b64encode(chart_bytes).decode("utf-8")
            chart_html = f'<img class="chart" src="data:image/png;base64,{chart_b64}" alt="Chart for {report.name}" />'

        table_html = preview_df.to_html(index=False, classes="data-table", border=0)
        notes_html = f"<p class='notes'>{report.notes}</p>" if report.notes else ""

        sections.append(
            f"""
            <section class="section">
              <p class="section-number">Section {idx}</p>
              <h2>{report.name}</h2>
              <p class="source">Source: {report.source}</p>
              {notes_html}
              <div class="metrics">{metric_html}</div>
              {chart_html}
              <h3>Data Preview</h3>
              {table_html}
              <p class="small">Showing first {len(preview_df):,} of {len(df):,} rows.</p>
            </section>
            """
        )

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>{report_title}</title>
      <style>
        @page {{ size: Letter landscape; margin: 0.35in; }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          font-family: Arial, Helvetica, sans-serif;
          color: #101828;
          background: #f8fafc;
        }}
        .cover {{
          background: linear-gradient(135deg, #1d4ed8, #0f172a);
          color: white;
          padding: 42px;
          min-height: 260px;
          display: flex;
          flex-direction: column;
          justify-content: center;
        }}
        .cover h1 {{
          font-size: 44px;
          margin: 0 0 12px;
          letter-spacing: -0.04em;
        }}
        .cover p {{
          font-size: 16px;
          opacity: 0.9;
          margin: 0;
        }}
        .content {{ padding: 24px; }}
        .section {{
          background: white;
          border: 1px solid #e5e7eb;
          border-radius: 18px;
          padding: 22px;
          margin-bottom: 22px;
          page-break-inside: avoid;
          break-inside: avoid;
        }}
        .section-number {{
          color: #2563eb;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          font-size: 12px;
          margin: 0 0 5px;
        }}
        h2 {{ margin: 0; font-size: 26px; }}
        h3 {{ margin-top: 20px; }}
        .source, .notes, .small {{ color: #667085; font-size: 13px; }}
        .metrics {{
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 12px;
          margin: 18px 0;
        }}
        .metric {{
          background: #f9fafb;
          border: 1px solid #e5e7eb;
          border-radius: 14px;
          padding: 12px;
        }}
        .metric-label {{ color: #667085; font-size: 12px; margin-bottom: 4px; }}
        .metric-value {{ font-size: 20px; font-weight: 800; }}
        .chart {{
          display: block;
          max-width: 100%;
          margin: 12px 0 18px;
          border: 1px solid #e5e7eb;
          border-radius: 14px;
        }}
        table.data-table {{
          width: 100%;
          border-collapse: collapse;
          font-size: 11px;
        }}
        table.data-table th {{
          background: #eff6ff;
          color: #1e3a8a;
          text-align: left;
          padding: 7px;
          border: 1px solid #dbeafe;
        }}
        table.data-table td {{
          padding: 6px 7px;
          border: 1px solid #e5e7eb;
          vertical-align: top;
        }}
        table.data-table tr:nth-child(even) td {{ background: #f9fafb; }}
        @media print {{
          body {{ background: white; }}
          .section {{ box-shadow: none; }}
        }}
      </style>
    </head>
    <body>
      <div class="cover">
        <h1>{report_title}</h1>
        <p>Generated {generated_at}</p>
      </div>
      <main class="content">
        {''.join(sections)}
      </main>
    </body>
    </html>
    """


def build_pdf_report(
    reports: List[ReportData],
    report_title: str,
    *,
    paper: str = "Letter",
    orientation: str = "Landscape",
) -> bytes:
    if colors is None:
        raise RuntimeError("ReportLab is not installed. Add reportlab to requirements.txt.")

    buffer = io.BytesIO()
    page_size = letter if paper == "Letter" else A4
    page_size = landscape(page_size) if orientation == "Landscape" else portrait(page_size)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.35 * inch,
        bottomMargin=0.35 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=28,
        leading=34,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#101828"),
        spaceAfter=18,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#667085"),
        spaceAfter=22,
    )
    heading_style = ParagraphStyle(
        "Heading",
        parent=styles["Heading2"],
        fontSize=17,
        leading=21,
        textColor=colors.HexColor("#1d4ed8"),
        spaceBefore=8,
        spaceAfter=8,
    )
    normal_style = ParagraphStyle(
        "NormalCustom",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#344054"),
        alignment=TA_LEFT,
    )

    story = [
        Spacer(1, 0.7 * inch),
        Paragraph(report_title, title_style),
        Paragraph(f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", subtitle_style),
        PageBreak(),
    ]

    available_width = page_size[0] - doc.leftMargin - doc.rightMargin

    for idx, report in enumerate(reports, start=1):
        df = report.dataframe.copy()
        story.append(Paragraph(f"Section {idx}: {report.name}", heading_style))
        story.append(Paragraph(f"Source: {report.source}", normal_style))
        if report.notes:
            story.append(Paragraph(report.notes, normal_style))
        story.append(Spacer(1, 0.12 * inch))

        summary = dataframe_summary(df)
        metric_rows = [[Paragraph(k, normal_style), Paragraph(v, normal_style)] for k, v in summary.items()]
        metric_table = Table(metric_rows, colWidths=[available_width * 0.3, available_width * 0.25])
        metric_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f9fafb")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d0d5dd")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(metric_table)
        story.append(Spacer(1, 0.18 * inch))

        chart_bytes = make_chart(df, report.name)
        if chart_bytes:
            chart_buffer = io.BytesIO(chart_bytes)
            img = Image(chart_buffer)
            img._restrictSize(available_width, 3.6 * inch)
            story.append(img)
            story.append(Spacer(1, 0.12 * inch))

        preview_df = df.head(35).fillna("")
        max_cols = min(8, len(preview_df.columns))
        preview_df = preview_df.iloc[:, :max_cols]

        table_data = [list(preview_df.columns)] + preview_df.astype(str).values.tolist()
        if table_data:
            col_width = available_width / max(1, len(table_data[0]))
            table = Table(table_data, repeatRows=1, colWidths=[col_width] * len(table_data[0]))
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d0d5dd")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9fafb")]),
                        ("PADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(table)
            story.append(Paragraph(f"Showing first {len(preview_df):,} rows and first {max_cols:,} columns.", normal_style))

        if idx < len(reports):
            story.append(PageBreak())

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()
