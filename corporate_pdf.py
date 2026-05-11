from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, letter, landscape, portrait
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


@dataclass
class PdfVisual:
    title: str
    source_url: str
    kind: str
    image_bytes: bytes
    notes: str = ""


def _page_size(paper: str, orientation: str):
    base = letter if paper == "Letter" else A4
    return landscape(base) if orientation == "Landscape" else portrait(base)


def _image_size(image_bytes: bytes) -> tuple[int, int]:
    with PILImage.open(io.BytesIO(image_bytes)) as img:
        return img.size


def _fit_dimensions(image_bytes: bytes, max_width: float, max_height: float) -> tuple[float, float]:
    width_px, height_px = _image_size(image_bytes)
    ratio = min(max_width / width_px, max_height / height_px)
    ratio = min(ratio, 1.0)
    return width_px * ratio, height_px * ratio


def _footer(canvas, doc, report_title: str):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawString(doc.leftMargin, 0.25 * inch, report_title[:90])
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.25 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_corporate_pdf(
    *,
    visuals: List[PdfVisual],
    report_title: str,
    client_name: str = "",
    company_name: str = "",
    prepared_by: str = "",
    executive_summary: str = "",
    logo_bytes: Optional[bytes] = None,
    paper: str = "Letter",
    orientation: str = "Landscape",
    layout: str = "One visual per page",
    include_source_links: bool = True,
) -> bytes:
    buffer = io.BytesIO()
    page_size = _page_size(paper, orientation)

    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        rightMargin=0.45 * inch,
        leftMargin=0.45 * inch,
        topMargin=0.42 * inch,
        bottomMargin=0.45 * inch,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CorporateTitle",
        parent=styles["Title"],
        fontSize=30,
        leading=36,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=16,
    )

    subtitle_style = ParagraphStyle(
        "CorporateSubtitle",
        parent=styles["Normal"],
        fontSize=12,
        leading=16,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#475467"),
        spaceAfter=10,
    )

    section_title_style = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontSize=17,
        leading=21,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )

    meta_style = ParagraphStyle(
        "Meta",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#667085"),
        spaceAfter=8,
    )

    summary_style = ParagraphStyle(
        "Summary",
        parent=styles["Normal"],
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#344054"),
        alignment=TA_LEFT,
        spaceAfter=12,
    )

    story = []

    # Cover page
    story.append(Spacer(1, 0.35 * inch))

    if logo_bytes:
        try:
            logo = Image(io.BytesIO(logo_bytes))
            logo._restrictSize(2.2 * inch, 0.9 * inch)
            logo.hAlign = "CENTER"
            story.append(logo)
            story.append(Spacer(1, 0.22 * inch))
        except Exception:
            pass

    story.append(Paragraph(report_title, title_style))

    subtitle_bits = []
    if client_name:
        subtitle_bits.append(f"Prepared for {client_name}")
    if company_name:
        subtitle_bits.append(company_name)
    if prepared_by:
        subtitle_bits.append(f"Prepared by {prepared_by}")

    subtitle_bits.append(f"Generated {datetime.now().strftime('%B %d, %Y')}")
    story.append(Paragraph(" • ".join(subtitle_bits), subtitle_style))

    story.append(Spacer(1, 0.15 * inch))
    story.append(HRFlowable(width="72%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceBefore=10, spaceAfter=18))

    if executive_summary.strip():
        story.append(Paragraph("Executive Summary", section_title_style))
        for paragraph in executive_summary.strip().split("\n"):
            if paragraph.strip():
                story.append(Paragraph(paragraph.strip(), summary_style))

    story.append(Spacer(1, 0.22 * inch))

    overview_data = [
        ["Report Detail", "Value"],
        ["Visualizations captured", str(len(visuals))],
        ["Paper format", f"{paper} {orientation}"],
        ["Layout", layout],
    ]

    overview_table = Table(overview_data, colWidths=[2.3 * inch, 4.2 * inch])
    overview_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DBEAFE")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F8FAFC")),
                ("PADDING", (0, 0), (-1, -1), 7),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    overview_table.hAlign = "CENTER"
    story.append(overview_table)

    story.append(PageBreak())

    usable_width = page_size[0] - doc.leftMargin - doc.rightMargin
    usable_height = page_size[1] - doc.topMargin - doc.bottomMargin

    if layout == "Two visuals per page":
        # Two stacked visual blocks per page
        block_height = usable_height / 2 - 0.18 * inch
        for idx, visual in enumerate(visuals, start=1):
            story.append(Paragraph(f"{idx}. {visual.title}", section_title_style))
            meta = f"Type: {visual.kind}"
            if include_source_links and visual.source_url:
                meta += f" | Source: {visual.source_url}"
            story.append(Paragraph(meta, meta_style))

            image_width, image_height = _fit_dimensions(
                visual.image_bytes,
                usable_width,
                block_height - 0.45 * inch,
            )
            img = Image(io.BytesIO(visual.image_bytes), width=image_width, height=image_height)
            img.hAlign = "CENTER"
            story.append(img)

            if visual.notes:
                story.append(Paragraph(visual.notes, meta_style))

            if idx % 2 == 0 and idx < len(visuals):
                story.append(PageBreak())
            else:
                story.append(Spacer(1, 0.18 * inch))
    else:
        # One visual per page
        for idx, visual in enumerate(visuals, start=1):
            story.append(Paragraph(f"{idx}. {visual.title}", section_title_style))

            meta = f"Type: {visual.kind}"
            if include_source_links and visual.source_url:
                meta += f" | Source: {visual.source_url}"
            story.append(Paragraph(meta, meta_style))

            image_width, image_height = _fit_dimensions(
                visual.image_bytes,
                usable_width,
                usable_height - 0.9 * inch,
            )
            img = Image(io.BytesIO(visual.image_bytes), width=image_width, height=image_height)
            img.hAlign = "CENTER"
            story.append(img)

            if visual.notes:
                story.append(Spacer(1, 0.06 * inch))
                story.append(Paragraph(visual.notes, meta_style))

            if idx < len(visuals):
                story.append(PageBreak())

    doc.build(
        story,
        onFirstPage=lambda canvas, doc_: _footer(canvas, doc_, report_title),
        onLaterPages=lambda canvas, doc_: _footer(canvas, doc_, report_title),
    )

    buffer.seek(0)
    return buffer.getvalue()
