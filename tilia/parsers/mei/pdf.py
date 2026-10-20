"""
Import measure regions from an MEI facsimile into a PDF timeline.

Targets the MEI written by the Cartographer App (Edirom/ZenMEM), the usual
tool for drawing measure bounding boxes on score images:

    <facsimile>
      <surface n="1">                      one per page image
        <graphic width="4316" height="5532"/>
        <zone xml:id="z1" type="measure" ulx=".." uly=".." lrx=".." lry=".."/>
      </surface>
    </facsimile>
    <body><mdiv><score><section>
      <measure n="1" facs="#z1"/>
    </section></score></mdiv></body>

Every measure becomes one PDF marker per time the beat timeline gives for its
number (so repeated measures get a marker per pass), pointing to the page of
its zone's surface and to the zone itself as a region.

Assumes the n-th surface is the n-th page of the timeline's PDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from tilia.timelines.beat.timeline import BeatTimeline
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.pdf.timeline import PdfTimeline

MEI_NS = "http://www.music-encoding.org/ns/mei"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
NS = {"mei": MEI_NS}


@dataclass
class _Zone:
    page_number: int  # 1-based position of its surface
    bbox: list[float]  # relative to the surface's image size


def _parse_file(path: Path) -> etree._ElementTree:
    # MEI files come from elsewhere: don't resolve entities or fetch DTDs.
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    return etree.parse(str(path), parser)


def _surface_size(surface: etree._Element) -> tuple[float, float] | None:
    graphic = surface.find("mei:graphic", NS)
    for element, width_attr, height_attr in [
        (graphic, "width", "height"),
        (surface, "lrx", "lry"),
    ]:
        if element is None:
            continue
        try:
            width = float(element.get(width_attr))
            height = float(element.get(height_attr))
        except (TypeError, ValueError):
            continue
        if width > 0 and height > 0:
            return width, height
    return None


def _zone_bbox(zone: etree._Element, width: float, height: float) -> list[float]:
    ulx, uly, lrx, lry = (
        float(zone.get(attr)) for attr in ("ulx", "uly", "lrx", "lry")
    )
    x0 = min(max(ulx / width, 0.0), 1.0)
    y0 = min(max(uly / height, 0.0), 1.0)
    x1 = min(max(lrx / width, 0.0), 1.0)
    y1 = min(max(lry / height, 0.0), 1.0)
    return [x0, y0, x1 - x0, y1 - y0]


def _parse_zones(root: etree._Element) -> tuple[dict[str, _Zone], list[str]]:
    zones = {}
    errors = []
    surfaces = root.findall(".//mei:facsimile/mei:surface", NS)
    for page_number, surface in enumerate(surfaces, start=1):
        size = _surface_size(surface)
        surface_zones = surface.findall("mei:zone", NS)
        if not size:
            if surface_zones:
                errors.append(
                    f"Page {page_number}: image size is missing, skipped its zones."
                )
            continue
        for zone in surface_zones:
            zone_id = zone.get(XML_ID)
            try:
                bbox = _zone_bbox(zone, *size)
            except (TypeError, ValueError):
                errors.append(f"Zone '{zone_id}': invalid coordinates.")
                continue
            if bbox[2] <= 0 or bbox[3] <= 0:
                errors.append(f"Zone '{zone_id}': empty after clipping to the page.")
                continue
            zones[zone_id] = _Zone(page_number, bbox)
    return zones, errors


def import_by_measure(
    pdf_tl: PdfTimeline,
    beat_tl: BeatTimeline,
    path: Path,
) -> tuple[bool, list[str]]:
    """
    Create PDF markers with regions from the measure zones of an MEI file.
    Returns a boolean indicating if the process was successful and
    an array with descriptions of any errors during the process.
    """
    if not beat_tl.measure_count:
        return False, ["The beat timeline has no measures."]

    try:
        root = _parse_file(path).getroot()
    except (OSError, etree.XMLSyntaxError) as e:
        return False, [f"Can't read MEI file: {e}"]

    if root.tag != f"{{{MEI_NS}}}mei":
        return False, ["Not an MEI file: the root element must be <mei>."]

    zones, errors = _parse_zones(root)
    if not zones:
        return False, errors + ["The file has no measure zones."]

    mdivs = root.findall(".//mei:body//mei:mdiv", NS)
    if len(mdivs) > 1:
        # Measure numbers usually restart in every movement, but the beat
        # timeline numbers measures once for the whole file.
        label = mdivs[0].get("label") or mdivs[0].get("n") or "1"
        errors.append(
            f"The file has {len(mdivs)} movements; only the first ('{label}') "
            f"was imported."
        )
        measures = mdivs[0].findall(".//mei:measure", NS)
    else:
        measures = root.findall(".//mei:body//mei:measure", NS)

    if not measures:
        return False, errors + ["The file has no measures."]

    page_total = pdf_tl.get_data("page_total")
    for measure in measures:
        number = measure.get("n")
        facs = (measure.get("facs") or "").split()
        if not facs:
            errors.append(f"Measure {number}: no zone, skipped.")
            continue

        # A measure broken across systems has one zone per part; the first is
        # where it starts, which is where playback reaches it.
        zone = zones.get(facs[0].removeprefix("#"))
        if zone is None:
            errors.append(f"Measure {number}: zone '{facs[0]}' not found, skipped.")
            continue

        if page_total and zone.page_number > page_total:
            errors.append(
                f"Measure {number}: on page {zone.page_number}, "
                f"but the PDF has {page_total} pages."
            )
            continue

        try:
            measure_number = int(number)
        except (TypeError, ValueError):
            errors.append(f"Measure '{number}': number is not an integer, skipped.")
            continue

        times = beat_tl.get_time_by_measure(measure_number)
        if not times:
            errors.append(f"No measure with number {measure_number}")
            continue

        for time in times:
            component, fail_reason = pdf_tl.create_component(
                ComponentKind.PDF_MARKER, time, zone.page_number, bbox=zone.bbox
            )
            if not component:
                errors.append(f"Measure {measure_number}: {fail_reason}")

    return True, errors
