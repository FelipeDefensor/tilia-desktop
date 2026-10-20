from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import tilia.errors
from tilia.parsers import get_import_function
from tilia.parsers.mei.pdf import import_by_measure as mei_to_pdf_by_measure
from tilia.requests import Get, get
from tilia.timelines.base.timeline import Timeline
from tilia.timelines.beat.timeline import BeatTimeline
from tilia.timelines.pdf.timeline import PdfTimeline
from tilia.timelines.range.timeline import RangeTimeline
from tilia.timelines.score.timeline import ScoreTimeline
from tilia.ui.dialogs.by_time_or_by_measure import ByTimeOrByMeasure
from tilia.ui.strings import UTF8_DECODE_FAILED

if TYPE_CHECKING:
    from tilia.ui.timelines.collection.collection import TimelineUIs


def _on_import_to_timeline(
    timeline_uis: TimelineUIs, tl_type: type[Timeline]
) -> tuple[bool, list[str]]:
    if not _validate_timeline_type_on_import(timeline_uis, tl_type):
        return False, [f"No timeline of type {tl_type} found."]

    tls_of_type = timeline_uis.get_timeline_uis_by_type(tl_type)
    if len(tls_of_type) == 1:
        timeline_ui = tls_of_type[0]
    else:
        timeline_ui = timeline_uis.ask_choose_timeline(
            "Import components from CSV",
            "Choose timeline where components will be created",
            tl_type,
        )

    if not timeline_ui:
        return False, ["User cancelled when choosing timeline."]

    timeline = get(Get.TIMELINE, timeline_ui.id)
    if not timeline.is_empty and not _confirm_timeline_overwrite_on_import():
        return False, ["User rejected components overwrite."]

    if tl_type == ScoreTimeline:
        time_or_measure = "measure"
        beat_tlui = _get_beat_timeline_ui_for_import_from_csv(timeline_uis)
        if not beat_tlui:
            return False, ["A beat timeline is required to import a score timeline."]

        beat_tl = get(Get.TIMELINE, beat_tlui.id)
        success, path = get(
            Get.FROM_USER_FILE_PATH,
            "Import components",
            ["musicXML files (*.musicxml *.mxl *.xml)"],
        )

    else:
        if tl_type == BeatTimeline:
            time_or_measure = "time"
        else:
            success, time_or_measure = _get_by_time_or_by_measure_from_user()
            if not success:
                return False, ["User cancelled when choosing by time or by measure."]

        if time_or_measure == "measure":
            beat_tlui = _get_beat_timeline_ui_for_import_from_csv(timeline_uis)
            if not beat_tlui:
                return False, ["A beat timeline is required to import by measure."]

            beat_tl = get(Get.TIMELINE, beat_tlui.id)
        else:
            beat_tl = None

        success, path = get(
            Get.FROM_USER_FILE_PATH, "Import components", ["CSV files (*.csv)"]
        )

    if not success:
        return False, ["User cancelled when choosing file to import."]

    timeline.clear()
    if isinstance(timeline, RangeTimeline):
        # Range rows are part of the timeline state. On import-with-replace,
        # drop them too so the resulting state is fully derived from the
        # imported file (no orphan rows from the previous state).
        timeline.clear_rows()

    func = get_import_function(tl_type, time_or_measure)
    if time_or_measure == "time":
        args = (timeline, path)
    elif time_or_measure == "measure":
        args = (timeline, beat_tl, path)
    else:
        raise ValueError("Invalid time_or_measure value.")  # pragma: no cover

    try:
        success, errors = func(*args)
    except UnicodeDecodeError:
        file_type = "musicXML" if tl_type == ScoreTimeline else "CSV"
        return False, [UTF8_DECODE_FAILED.format(path, file_type)]

    if isinstance(timeline, RangeTimeline) and not timeline.rows:
        # Restore the >=1-row invariant if the import yielded zero rows
        # (e.g. every CSV row failed validation, or the file was empty).
        timeline.setup_blank_timeline()

    return success, errors


def _on_import_mei_to_pdf_timeline(
    timeline_uis: TimelineUIs, path: str | None = None
) -> tuple[bool, list[str]]:
    """
    Replaces a PDF timeline's markers with one per measure of an MEI file
    (e.g. exported by the Cartographer App), timed by a beat timeline and
    pointing to each measure's zone.
    """
    if not _validate_timeline_type_on_import(timeline_uis, PdfTimeline):
        return False, ["No PDF timeline found."]

    pdf_tluis = timeline_uis.get_timeline_uis_by_type(PdfTimeline)
    if len(pdf_tluis) == 1:
        pdf_tlui = pdf_tluis[0]
    else:
        pdf_tlui = timeline_uis.ask_choose_timeline(
            "Import measure regions from MEI",
            "Choose PDF timeline where markers will be created",
            PdfTimeline,
        )
    if not pdf_tlui:
        return False, ["User cancelled when choosing timeline."]

    beat_tlui = _get_beat_timeline_ui_for_import_from_csv(
        timeline_uis, "Import measure regions from MEI"
    )
    if not beat_tlui:
        return False, ["A beat timeline is required to import measure regions."]

    pdf_tl = get(Get.TIMELINE, pdf_tlui.id)
    if not pdf_tl.is_empty and not _confirm_timeline_overwrite_on_import():
        return False, ["User rejected components overwrite."]

    if path is None:
        success, path = get(
            Get.FROM_USER_FILE_PATH,
            "Import measure regions",
            ["MEI files (*.mei *.xml)"],
        )
        if not success:
            return False, ["User cancelled when choosing file to import."]

    pdf_tl.clear()
    return mei_to_pdf_by_measure(pdf_tl, get(Get.TIMELINE, beat_tlui.id), Path(path))


def _get_by_time_or_by_measure_from_user():
    dialog = ByTimeOrByMeasure()
    return (True, dialog.get_option()) if dialog.exec() else (False, None)


def _validate_timeline_type_on_import(
    timeline_uis: TimelineUIs, tl_type: type[Timeline]
):
    if not timeline_uis.get_timeline_uis_by_type(tl_type):
        tilia.errors.display(
            tilia.errors.IMPORT_FAILED,
            f"No timelines of type '{tl_type}' found.",
        )
        return False
    return True


def _confirm_timeline_overwrite_on_import():
    return get(
        Get.FROM_USER_YES_OR_NO,
        "Import",
        "Selected timeline is not empty. Existing components will be deleted when importing. Are you sure you want to continue?",
    )


def _get_beat_timeline_ui_for_import_from_csv(
    timeline_uis: TimelineUIs, title: str = "Import components from CSV"
):
    beat_tls = timeline_uis.get_timeline_uis_by_type(BeatTimeline)
    if not beat_tls:
        return
    elif len(beat_tls) == 1:
        return beat_tls[0]
    else:
        return timeline_uis.ask_choose_timeline(
            title,
            "Choose timeline with measures to be used when importing",
            BeatTimeline,
        )


def _display_import_from_csv_errors(success: bool, errors: list[str]):
    errors_str = "\n".join(errors)
    if success:
        tilia.errors.display(tilia.errors.IMPORT_SUCCESS_ERRORS, errors_str)
    else:
        tilia.errors.display(tilia.errors.IMPORT_FAILED, errors_str)
