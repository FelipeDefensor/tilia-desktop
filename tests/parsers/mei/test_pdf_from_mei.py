import pytest

from tests.mock import Serve
from tests.utils import get_command_action, get_main_window_menu, get_submenu, undoable
from tilia.requests import Get
from tilia.ui import commands

MEI_NS = "http://www.music-encoding.org/ns/mei"

# A zone of 100,200 → 600,450 on a 1000 × 1000 image.
ZONE = (100, 200, 600, 450)
ZONE_BBOX = [0.1, 0.2, 0.5, 0.25]


def zone_xml(zone_id, ulx, uly, lrx, lry):
    return (
        f'<zone xml:id="{zone_id}" type="measure" '
        f'ulx="{ulx}" uly="{uly}" lrx="{lrx}" lry="{lry}"/>'
    )


def surface_xml(zones="", width=1000, height=1000, graphic=True):
    graphic_xml = (
        f'<graphic target="page.jpg" width="{width}" height="{height}"/>'
        if graphic
        else ""
    )
    return (
        f'<surface ulx="0" uly="0" lrx="{width}" lry="{height}">'
        f"{graphic_xml}{zones}</surface>"
    )


def measure_xml(n, facs):
    return f'<measure n="{n}" facs="{facs}"/>'


def mdiv_xml(measures, label="Movement 1"):
    return f'<mdiv label="{label}"><score><section>{measures}</section></score></mdiv>'


def write_mei(tmp_path, surfaces, mdivs, name="regions.mei"):
    path = tmp_path / name
    path.write_text(
        f'<mei xmlns="{MEI_NS}" meiversion="5.0.0-dev">'
        f"<music><facsimile>{''.join(surfaces)}</facsimile>"
        f"<body>{''.join(mdivs)}</body></music></mei>"
    )
    return path


def simple_mei(tmp_path, measure_count=2):
    """One zone per measure on page 1, all the same box."""
    zones = "".join(zone_xml(f"z{i}", *ZONE) for i in range(1, measure_count + 1))
    measures = "".join(measure_xml(i, f"#z{i}") for i in range(1, measure_count + 1))
    return write_mei(tmp_path, [surface_xml(zones)], [mdiv_xml(measures)])


@pytest.fixture
def measures(beat_tl, beat_tlui):
    """Beat timeline with one beat per measure: measure n starts at (n - 1) * 10 s."""
    beat_tl.set_data("beat_pattern", [1])
    for time in range(0, 100, 10):
        commands.execute("timeline.beat.add", time=time)
    return beat_tl


def import_mei(path):
    commands.execute("timelines.import.pdf_mei", path=str(path))


def marker_data(pdf_tl):
    return [
        (m.get_data("time"), m.get_data("page_number"), m.get_data("bbox"))
        for m in pdf_tl
    ]


class TestImport:
    def test_creates_marker_per_measure(self, pdf_tlui, pdf_tl, measures, tmp_path):
        path = simple_mei(tmp_path)

        with undoable():
            import_mei(path)

        assert len(pdf_tl) == 2
        assert [m.get_data("time") for m in pdf_tl] == [0, 10]
        for marker in pdf_tl:
            assert marker.get_data("page_number") == 1
            assert marker.get_data("bbox") == pytest.approx(ZONE_BBOX)

    def test_regions_are_drawn_in_viewer(self, pdf_tlui, measures, tmp_path):
        import_mei(simple_mei(tmp_path))

        assert len(pdf_tlui.pdf_view.regions) == 2

    def test_page_is_position_of_surface(self, pdf_tl, pdf_tlui, measures, tmp_path):
        # A title page without zones still counts as page 1.
        path = write_mei(
            tmp_path,
            [surface_xml(), surface_xml(zone_xml("z1", *ZONE))],
            [mdiv_xml(measure_xml(1, "#z1"))],
        )

        import_mei(path)

        assert marker_data(pdf_tl) == [(0, 2, pytest.approx(ZONE_BBOX))]

    def test_bbox_is_relative_to_image_size(self, pdf_tl, pdf_tlui, measures, tmp_path):
        path = write_mei(
            tmp_path,
            [surface_xml(zone_xml("z1", 400, 300, 2000, 900), width=4000, height=6000)],
            [mdiv_xml(measure_xml(1, "#z1"))],
        )

        import_mei(path)

        assert pdf_tl[0].get_data("bbox") == pytest.approx([0.1, 0.05, 0.4, 0.1])

    def test_image_size_falls_back_to_surface_extent(
        self, pdf_tl, pdf_tlui, measures, tmp_path
    ):
        path = write_mei(
            tmp_path,
            [surface_xml(zone_xml("z1", *ZONE), graphic=False)],
            [mdiv_xml(measure_xml(1, "#z1"))],
        )

        import_mei(path)

        assert pdf_tl[0].get_data("bbox") == pytest.approx(ZONE_BBOX)

    def test_zone_is_clipped_to_image(self, pdf_tl, pdf_tlui, measures, tmp_path):
        path = write_mei(
            tmp_path,
            [surface_xml(zone_xml("z1", -50, 900, 500, 1200))],
            [mdiv_xml(measure_xml(1, "#z1"))],
        )

        import_mei(path)

        assert pdf_tl[0].get_data("bbox") == pytest.approx([0, 0.9, 0.5, 0.1])

    def test_measure_with_several_zones_uses_first(
        self, pdf_tl, pdf_tlui, measures, tmp_path
    ):
        # A measure broken across a system break has a zone in each system.
        path = write_mei(
            tmp_path,
            [
                surface_xml(
                    zone_xml("start", *ZONE) + zone_xml("rest", 0, 600, 200, 800)
                )
            ],
            [mdiv_xml(measure_xml(1, "#start #rest"))],
        )

        import_mei(path)

        assert len(pdf_tl) == 1
        assert pdf_tl[0].get_data("bbox") == pytest.approx(ZONE_BBOX)

    def test_repeated_measure_gets_marker_per_pass(
        self, pdf_tl, pdf_tlui, beat_tlui, measures, tmp_path
    ):
        # Measures 1–2 played twice: beat timeline numbers them 1, 2, 1, 2, ...
        beat_tlui.select_element(beat_tlui[2])
        with Serve(Get.FROM_USER_INT, (True, 1)):
            commands.execute("timeline.beat.set_measure_number")
        beat_tlui.deselect_element(beat_tlui[2])

        import_mei(simple_mei(tmp_path))

        assert [m.get_data("time") for m in pdf_tl] == [0, 10, 20, 30]

    def test_replaces_existing_markers(self, pdf_tl, pdf_tlui, measures, tmp_path):
        commands.execute("timeline.pdf.add", time=55, page_number=3)

        with Serve(Get.FROM_USER_YES_OR_NO, True):
            import_mei(simple_mei(tmp_path))

        assert [m.get_data("time") for m in pdf_tl] == [0, 10]

    def test_keeps_markers_if_user_declines_overwrite(
        self, pdf_tl, pdf_tlui, measures, tmp_path
    ):
        commands.execute("timeline.pdf.add", time=55, page_number=3)

        with Serve(Get.FROM_USER_YES_OR_NO, False):
            import_mei(simple_mei(tmp_path))

        assert marker_data(pdf_tl) == [(55, 3, None)]

    def test_asks_for_file_when_no_path_given(
        self, pdf_tl, pdf_tlui, measures, tmp_path
    ):
        path = simple_mei(tmp_path)

        with Serve(Get.FROM_USER_FILE_PATH, (True, str(path))):
            commands.execute("timelines.import.pdf_mei")

        assert len(pdf_tl) == 2


class TestPartialImport:
    def test_missing_measure_number_is_reported(
        self, pdf_tl, pdf_tlui, measures, tmp_path, tilia_errors
    ):
        path = write_mei(
            tmp_path,
            [surface_xml(zone_xml("z1", *ZONE) + zone_xml("z2", *ZONE))],
            [mdiv_xml(measure_xml(1, "#z1") + measure_xml(99, "#z2"))],
        )

        import_mei(path)

        assert len(pdf_tl) == 1
        tilia_errors.assert_in_error_message("No measure with number 99")

    def test_zone_beyond_pdf_pages_is_skipped(
        self, pdf_tl, pdf_tlui, measures, tmp_path, tilia_errors
    ):
        # example.pdf has 5 pages; the zone is on the 6th surface.
        surfaces = [surface_xml() for _ in range(5)]
        surfaces.append(surface_xml(zone_xml("z1", *ZONE)))
        path = write_mei(tmp_path, surfaces, [mdiv_xml(measure_xml(1, "#z1"))])

        import_mei(path)

        assert len(pdf_tl) == 0
        tilia_errors.assert_in_error_message("on page 6, but the PDF has 5 pages")

    def test_only_first_movement_is_imported(
        self, pdf_tl, pdf_tlui, measures, tmp_path, tilia_errors
    ):
        path = write_mei(
            tmp_path,
            [surface_xml(zone_xml("z1", *ZONE) + zone_xml("z2", 0, 500, 900, 700))],
            [
                mdiv_xml(measure_xml(1, "#z1"), label="Allegro"),
                mdiv_xml(measure_xml(1, "#z2"), label="Adagio"),
            ],
        )

        import_mei(path)

        assert marker_data(pdf_tl) == [(0, 1, pytest.approx(ZONE_BBOX))]
        tilia_errors.assert_in_error_message("only the first ('Allegro')")

    def test_non_integer_measure_number_is_skipped(
        self, pdf_tl, pdf_tlui, measures, tmp_path, tilia_errors
    ):
        path = write_mei(
            tmp_path,
            [surface_xml(zone_xml("z1", *ZONE))],
            [mdiv_xml(measure_xml("12a", "#z1"))],
        )

        import_mei(path)

        assert len(pdf_tl) == 0
        tilia_errors.assert_in_error_message("'12a': number is not an integer")


class TestFailedImport:
    def test_requires_beat_timeline(self, pdf_tl, pdf_tlui, tmp_path, tilia_errors):
        import_mei(simple_mei(tmp_path))

        assert len(pdf_tl) == 0
        tilia_errors.assert_in_error_message("A beat timeline is required")

    @pytest.mark.parametrize(
        "content, message",
        [
            ("not xml at all", "Can't read MEI file"),
            ("<score-partwise/>", "Not an MEI file"),
            (f'<mei xmlns="{MEI_NS}"><music/></mei>', "no measure zones"),
        ],
    )
    def test_invalid_file_keeps_existing_markers(
        self, pdf_tl, pdf_tlui, measures, tmp_path, tilia_errors, content, message
    ):
        commands.execute("timeline.pdf.add", time=55, page_number=3)
        path = tmp_path / "bad.mei"
        path.write_text(content)

        with Serve(Get.FROM_USER_YES_OR_NO, True):
            import_mei(path)

        assert marker_data(pdf_tl) == [(55, 3, None)]
        tilia_errors.assert_in_error_message(message)


class TestMenu:
    def test_pdf_menu_has_mei_import(self, qtui):
        pdf_menu = get_submenu(get_main_window_menu(qtui, "Timelines"), "PDF")
        assert get_command_action(pdf_menu, "timelines.import.pdf_mei")

    def test_import_from_menu(self, qtui, pdf_tl, pdf_tlui, measures, tmp_path):
        path = simple_mei(tmp_path)
        pdf_menu = get_submenu(get_main_window_menu(qtui, "Timelines"), "PDF")

        with Serve(Get.FROM_USER_FILE_PATH, (True, str(path))):
            get_command_action(pdf_menu, "timelines.import.pdf_mei").trigger()

        assert len(pdf_tl) == 2
