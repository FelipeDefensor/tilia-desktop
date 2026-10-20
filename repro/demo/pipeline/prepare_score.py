"""Turn Verovio's SVG pages into a PDF and a Cartographer-style MEI of measure zones.

- PDF: Qt's SVG renderer is SVG Tiny 1.2 and skips nested <svg>, which Verovio
  uses for its coordinate system. The inner <svg viewBox> is replaced by an
  equivalent <g transform="scale(..)">, then every page is drawn (as vectors)
  onto one A4 page of a QPdfWriter.
- Zones: computed from Verovio's geometry, not from the renderer. A measure's
  box spans its staff lines horizontally and runs from the top line of its
  top staff to the bottom line of its bottom staff, plus padding, i.e. what a
  Cartographer user draws around a measure of a system.

Usage: python -I prepare_score.py RENDER_DIR OUT.pdf OUT-zones.mei
"""

import json
import re
import sys
from pathlib import Path

from lxml import etree
from PySide6.QtCore import QByteArray, QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
)
from PySide6.QtSvg import QSvgRenderer

SVG = "{http://www.w3.org/2000/svg}"
# Zones are written in the pixels of an imagined A4 scan at 300 dpi, as
# Cartographer would for a scanned page.
IMAGE_WIDTH, IMAGE_HEIGHT = 2480, 3508
LINE = re.compile(
    r"M(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) L(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)"
)
PADDING_STAFF_SPACES = 1.5

app = QGuiApplication(sys.argv)
render_dir, pdf_path, mei_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
score = json.loads((render_dir / "score.json").read_text())
parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)


def flatten(root: etree._Element) -> tuple[float, float, float, float]:
    """Replace the inner <svg viewBox> by a scaled <g>. Returns the inner
    viewBox width/height and the page-margin translation, in inner units."""
    outer_w = float(root.get("width").removesuffix("px"))
    outer_h = float(root.get("height").removesuffix("px"))
    inner = root.find(f"{SVG}svg")
    _, _, vb_w, vb_h = (float(v) for v in inner.get("viewBox").split())
    inner.tag = f"{SVG}g"
    for attr in ("viewBox", "width", "height", "overflow"):
        inner.attrib.pop(attr, None)
    inner.set("transform", f"scale({outer_w / vb_w},{outer_h / vb_h})")
    # Qt doesn't resolve CSS-style font lists; name one font that exists.
    inner.set("font-family", "Times New Roman")

    margin = inner.find(f"{SVG}g[@class='page-margin']")
    tx, ty = (float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", margin.get("transform")))
    return vb_w, vb_h, tx, ty


TEXT_STYLE_ATTRS = ("font-size", "font-style", "font-weight", "font-family")


def flatten_text(root: etree._Element) -> None:
    """Verovio nests <tspan>s (<text font-size=0><tspan><tspan font-size=..>),
    which SVG Tiny can't hold. Collapse every <text> into a single run,
    keeping the innermost style and the first x/y given by any tspan."""
    for text in root.iter(f"{SVG}text"):
        tspans = list(text.iter(f"{SVG}tspan"))
        if not tspans:
            continue
        content = "".join(text.itertext()).strip()
        for tspan in tspans:
            for attr in TEXT_STYLE_ATTRS:
                if tspan.get(attr) and attr != "font-family":
                    text.set(attr, tspan.get(attr))
            for attr in ("x", "y"):
                if tspan.get(attr) and not text.get(attr):
                    text.set(attr, tspan.get(attr))
        for child in list(text):
            text.remove(child)
        text.text = content


def measure_boxes(root, vb_w, vb_h, tx, ty) -> dict[str, list[float]]:
    boxes = {}
    for measure in root.iter(f"{SVG}g"):
        if measure.get("class") != "measure":
            continue
        xs, ys = [], []
        line_gaps = []
        for staff in measure.findall(f"{SVG}g[@class='staff']"):
            staff_ys = []
            for path in staff.findall(f"{SVG}path"):
                match = LINE.fullmatch(path.get("d", "").strip())
                if not match:
                    continue
                x1, y1, x2, y2 = (float(v) for v in match.groups())
                if y1 != y2:
                    continue  # not a staff line
                xs += [x1, x2]
                staff_ys.append(y1)
            if len(staff_ys) >= 2:
                staff_ys.sort()
                line_gaps.append(staff_ys[1] - staff_ys[0])
            ys += staff_ys
        if not xs:
            continue
        pad = PADDING_STAFF_SPACES * (min(line_gaps) if line_gaps else 0)
        x0, x1 = min(xs) + tx, max(xs) + tx
        y0, y1 = min(ys) + ty - pad, max(ys) + ty + pad
        boxes[measure.get("id")] = [
            max(x0 / vb_w, 0),
            max(y0 / vb_h, 0),
            min(x1 / vb_w, 1) - max(x0 / vb_w, 0),
            min(y1 / vb_h, 1) - max(y0 / vb_h, 0),
        ]
    return boxes


def draw_heading(painter: QPainter, page: QRectF, page_number: int) -> None:
    """Title block on page 1, running head on the others, in the top margin."""
    painter.save()
    painter.setPen(QColor("black"))
    if page_number == 1:
        painter.setFont(QFont("Times New Roman", 22))
        painter.drawText(
            QRectF(0, page.height() * 0.022, page.width(), page.height() * 0.035),
            Qt.AlignmentFlag.AlignCenter,
            "Maple Leaf Rag",
        )
        painter.setFont(QFont("Times New Roman", 11))
        painter.drawText(
            QRectF(0, page.height() * 0.055, page.width() * 0.96, page.height() * 0.02),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "Scott Joplin (1899)",
        )
    else:
        painter.setFont(QFont("Times New Roman", 10, italic=True))
        painter.drawText(
            QRectF(0, page.height() * 0.03, page.width() * 0.96, page.height() * 0.02),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"Maple Leaf Rag — {page_number}",
        )
    painter.restore()


writer = QPdfWriter(str(pdf_path))
writer.setPageLayout(
    QPageLayout(
        QPageSize(QPageSize.PageSizeId.A4),
        QPageLayout.Orientation.Portrait,
        QMarginsF(0, 0, 0, 0),
    )
)
writer.setResolution(300)
writer.setTitle("Scott Joplin — Maple Leaf Rag (engraved with Verovio)")
painter = QPainter(writer)

boxes_by_page: list[dict[str, list[float]]] = []
for page in range(1, score["pages"] + 1):
    root = etree.parse(str(render_dir / f"page-{page}.svg"), parser).getroot()
    vb_w, vb_h, tx, ty = flatten(root)
    flatten_text(root)
    boxes_by_page.append(measure_boxes(root, vb_w, vb_h, tx, ty))

    renderer = QSvgRenderer(QByteArray(etree.tostring(root)))
    assert renderer.isValid(), f"page {page} did not parse"
    if page > 1:
        writer.newPage()
    page_rect = QRectF(0, 0, writer.width(), writer.height())
    renderer.render(painter, page_rect)
    draw_heading(painter, page_rect, page)
painter.end()

# One zone per measure, on the page Verovio put it on.
surfaces, body = [], []
missing = []
for page, boxes in enumerate(boxes_by_page, start=1):
    zones = []
    for m in score["measures"]:
        if m["page"] != page:
            continue
        box = boxes.get(m["id"])
        if box is None:
            missing.append(m["index"])
            continue
        x, y, w, h = box
        ulx, uly = round(x * IMAGE_WIDTH), round(y * IMAGE_HEIGHT)
        lrx, lry = round((x + w) * IMAGE_WIDTH), round((y + h) * IMAGE_HEIGHT)
        zones.append(
            f'        <zone xml:id="z{m["index"]}" type="measure" '
            f'ulx="{ulx}" uly="{uly}" lrx="{lrx}" lry="{lry}"/>'
        )
        body.append(f'<measure n="{m["index"]}" facs="#z{m["index"]}"/>')
    surfaces.append(
        f'      <surface xml:id="s{page}" n="{page}" ulx="0" uly="0" '
        f'lrx="{IMAGE_WIDTH}" lry="{IMAGE_HEIGHT}">\n'
        f'        <graphic target="maple-leaf-rag-{page}.png" type="facsimile" '
        f'width="{IMAGE_WIDTH}" height="{IMAGE_HEIGHT}"/>\n'
        + "\n".join(zones)
        + "\n      </surface>"
    )

assert not missing, f"no box for measures {missing}"
mei_path.write_text(
    f"""<?xml version="1.0" encoding="UTF-8"?>
<mei xmlns="http://www.music-encoding.org/ns/mei" meiversion="5.0.0-dev">
  <meiHead><fileDesc><titleStmt><title>Maple Leaf Rag — measure zones</title>
    <composer>Scott Joplin</composer></titleStmt><pubStmt/></fileDesc></meiHead>
  <music>
    <facsimile>
{chr(10).join(surfaces)}
    </facsimile>
    <body><mdiv label="Maple Leaf Rag" n="1"><score><section>
      {"".join(body)}
    </section></score></mdiv></body>
  </music>
</mei>
"""
)
print(
    f"PDF: {score['pages']} pages; zones: {sum(len(b) for b in boxes_by_page)} measures"
)
