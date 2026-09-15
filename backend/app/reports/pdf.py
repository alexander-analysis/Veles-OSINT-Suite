"""PDF intelligence reports (reportlab).

One generic builder renders a report made of sections; each section is a
heading plus a paragraph, a key/value block or a table.  Every page carries
the classification marking top and bottom, the report title, generation
time and page numbers - the layout agencies expect from a printed brief.
"""

from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app import __version__
from app.utils.time import utcnow

CLASSIFICATION_COLORS = {"UNCLASSIFIED": colors.HexColor("#15803d"), "CONFIDENTIAL": colors.HexColor("#1d4ed8"), "SECRET": colors.HexColor("#b91c1c")}
STEEL = colors.HexColor("#2f4a6b")
GRID = colors.HexColor("#d1d5db")
ZEBRA = colors.HexColor("#f3f4f6")


@dataclass
class Section:
    title: str
    text: str | None = None
    items: list[tuple[str, Any]] = field(default_factory=list)  # key/value block
    table: list[list[Any]] | None = None  # first row = header
    column_widths: list[float] | None = None
    page_break_before: bool = False


@dataclass
class Report:
    title: str
    subtitle: str
    classification: str = "UNCLASSIFIED"
    period: str | None = None
    prepared_by: str = "VELES automated analysis"
    sections: list[Section] = field(default_factory=list)


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], fontSize=20, textColor=STEEL, spaceAfter=4, alignment=TA_CENTER),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=11, textColor=colors.HexColor("#4b5563"), alignment=TA_CENTER, spaceAfter=14),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, textColor=STEEL, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("body", parent=base["Normal"], fontSize=9.5, leading=13),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontSize=8, leading=10),
        "cell_head": ParagraphStyle("cell_head", parent=base["Normal"], fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold"),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontSize=8, textColor=colors.HexColor("#6b7280")),
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, float):
        return f"{value:,.2f}" if abs(value) >= 10 else f"{value:.3f}".rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_fmt(v)}" for k, v in value.items())
    return str(value)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_pdf(report: Report) -> bytes:
    styles = _styles()
    marking = report.classification.upper()
    color = CLASSIFICATION_COLORS.get(marking, colors.HexColor("#374151"))
    generated = utcnow()

    def decorate(canvas, doc) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(color)
        canvas.rect(0, height - 8 * mm, width, 8 * mm, stroke=0, fill=1)
        canvas.rect(0, 0, width, 8 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(width / 2, height - 5.5 * mm, marking)
        canvas.drawCentredString(width / 2, 2.5 * mm, marking)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(15 * mm, 10 * mm, f"{report.title} - generated {generated:%Y-%m-%d %H:%M} UTC by VELES {__version__}")
        canvas.drawRightString(width - 15 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=report.title, author="VELES")
    story = [Paragraph(_escape(report.title), styles["title"]), Paragraph(_escape(report.subtitle), styles["subtitle"])]
    meta = [("Classification", marking), ("Generated", generated), ("Prepared by", report.prepared_by)]
    if report.period:
        meta.insert(1, ("Period", report.period))
    story.append(_kv_table(meta, styles))
    story.append(Spacer(1, 6 * mm))

    for section in report.sections:
        if section.page_break_before:
            story.append(PageBreak())
        heading = Paragraph(_escape(section.title), styles["h2"])
        parts = []
        if section.text:
            parts.append(Paragraph(_escape(section.text), styles["body"]))
        if section.items:
            parts.append(_kv_table(section.items, styles))
        if section.table:
            parts.append(_data_table(section.table, styles, section.column_widths))
        # keep the heading with its first element so a title never dangles at a page bottom
        story.append(KeepTogether([heading, parts[0]]) if parts else heading)
        story.extend(parts[1:])
        story.append(Spacer(1, 3 * mm))

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _kv_table(items: list[tuple[str, Any]], styles) -> Table:
    rows = [[Paragraph(_escape(str(k)), styles["cell"]), Paragraph(_escape(_fmt(v)), styles["cell"])] for k, v in items]
    table = Table(rows, colWidths=[45 * mm, 125 * mm])
    table.setStyle(TableStyle([("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#6b7280")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2)]))
    return table


def _data_table(rows: list[list[Any]], styles, column_widths: list[float] | None) -> Table:
    header, body = rows[0], rows[1:]
    data = [[Paragraph(_escape(str(h)), styles["cell_head"]) for h in header]]
    for row in body:
        data.append([Paragraph(_escape(_fmt(cell)), styles["cell"]) for cell in row])
    if not body:
        data.append([Paragraph("none", styles["cell"])] + [""] * (len(header) - 1))
    widths = [w * mm for w in column_widths] if column_widths else None
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), STEEL),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    for index in range(1, len(data)):
        if index % 2 == 0:
            style.append(("BACKGROUND", (0, index), (-1, index), ZEBRA))
    table.setStyle(TableStyle(style))
    return table
