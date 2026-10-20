# TODO: QThreads
from __future__ import annotations

from bisect import bisect
from statistics import median
from typing import Callable, Iterator

from lxml import etree
from PySide6.QtCore import (
    QKeyCombination,
    QPointF,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import tilia.errors
from tilia.log import logger
from tilia.requests import (
    Get,
    Post,
    get,
    listen,
    post,
    serve,
    stop_listening_to_all,
    stop_serving_all,
)
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.score.schema import stage_degree
from tilia.ui import commands
from tilia.ui.commands import get_qaction
from tilia.ui.schema import library
from tilia.ui.schema.diagram import DEGREE_MIME_TYPE, read_degree_mime_data
from tilia.ui.schema.items import (
    SvgSchemaDegree,
    SvgSchemaInstance,
    layout_schema_instances,
)
from tilia.ui.schema.palette import SchemaPalette
from tilia.ui.smooth_scroll import SmoothSetter
from tilia.ui.windows.view_window import ViewDockWidget

NOTEHEAD_CLASS = "vf-notehead"
# How far from a notehead (in notehead heights) a dropped degree still lands
# on it.
NOTEHEAD_DROP_TOLERANCE = 1.0
DROP_HIGHLIGHT_COLOR = QColor(25, 118, 210)
# Scene units, for scores without noteheads.
DEFAULT_NOTEHEAD_HEIGHT = 10.0
# Seconds within which a note counts as starting at a given time.
NOTE_TIME_TOLERANCE = 1e-6


class SvgViewer(ViewDockWidget):
    def __init__(self, name: str, tl_id: int, *args, **kwargs) -> None:
        super().__init__("TiLiA Score Viewer", *args, menu_title=name, **kwargs)
        self.setObjectName(f"TiLiA Score Viewer {tl_id}")
        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )
        self.timeline_id = tl_id

        self.__setup_score_viewer()
        serve(self, Get.SCORE_VIEWER, self.get_viewer)
        listen(
            self,
            Post.SCHEMA_LIBRARY_UPDATED,
            lambda: self.schema_palette.refresh_library(),
        )

    def get_viewer(self, tl_id: int):
        if tl_id == self.timeline_id:
            return self

    @property
    def timeline(self):
        return get(Get.TIMELINE, self.timeline_id)

    @property
    def timeline_ui(self):
        return get(Get.TIMELINE_UI, self.timeline_id)

    def __setup_score_viewer(self) -> None:
        self.view = SvgGraphicsView(
            get_times=self._get_time_from_scene_x,
            update_measure_tracker=self.update_measure_tracker,
            update_scroll_margins=self._update_scroll_margins,
            on_degree_drag=self._on_degree_drag,
            on_degree_drop=self._on_degree_drop,
            parent=self,
        )
        self.scene = QGraphicsScene(self.view)
        self.view.setScene(self.scene)

        v_toolbar = self._get_toolbar()
        self.schema_palette = SchemaPalette(
            on_finish=lambda: commands.execute("timeline.score.finish_schema_instance"),
            on_delete=lambda: commands.execute("timeline.score.delete_schema_instance"),
        )
        self.schema_palette.hide()
        h_box = QHBoxLayout()
        h_box.addLayout(v_toolbar)
        h_box.addWidget(self.view)
        h_box.addWidget(self.schema_palette)
        widget = QWidget()
        widget.setLayout(h_box)
        self.setWidget(widget)

        self.score_root = ""
        self.score_renderer = QSvgRenderer()
        self.tla_annotations = {}
        self.next_tla_id = 0
        self.drag_pos = QPointF()
        self.is_hidden = False
        self.is_svg_loaded = False
        self.visible_times = [0, 0]
        self.beat_x_position = {}
        self.cur_t_x = 0.0
        # Notehead element id -> (its rect, its stave note's element id)
        self.noteheads: dict[str, tuple[QRectF, str]] = {}
        self.notehead_unit = DEFAULT_NOTEHEAD_HEIGHT
        self.system_rect = QRectF()
        self.stavenotes: dict[str, SvgStaveNote] = {}
        self.schema_instances: dict[int, SvgSchemaInstance] = {}
        self.active_schema_instance: int | None = None
        self.drop_highlight = QGraphicsRectItem()
        self.drop_highlight.setPen(QPen(DROP_HIGHLIGHT_COLOR, 2))
        self.drop_highlight.setZValue(4)
        self.drop_highlight.hide()
        self._update_scroll_margins()

    def _get_toolbar(self) -> QVBoxLayout:
        command_data = [
            (
                "timeline.score.add",
                self.annotation_add,
                "Add Annotation (Return)",
                "",
                "annotation-add",
            ),
            (
                "timeline.score.delete",
                self.annotation_delete,
                "Delete Annotation (Delete)",
                "",
                "annotation-delete",
            ),
            (
                "timeline.score.edit",
                self.annotation_edit,
                "Edit Annotation",
                "Shift+Return",
                "annotation-edit",
            ),
            (
                "timeline.score.font_dec",
                self.annotation_font_dec,
                "Decrease Annotation Font",
                "Shift+Down",
                "annotation-font-decrease",
            ),
            (
                "timeline.score.font_inc",
                self.annotation_font_inc,
                "Increase Annotation Font",
                "Shift+Up",
                "annotation-font-increase",
            ),
            (
                "timeline.score.toggle_schemata",
                self.toggle_schema_palette,
                "Schemata",
                "",
                "",
            ),
        ]

        v_toolbar = QVBoxLayout()

        for name, callback, text, shortcut, icon in command_data:
            commands.register(name, callback, text, shortcut, icon)
            button = QToolButton()
            button.setDefaultAction(get_qaction(name))
            v_toolbar.addWidget(button)

        for name, callback, text in [
            (
                "timeline.score.add_schema_degree",
                self.add_schema_degree,
                "Add schema degree",
            ),
            (
                "timeline.score.remove_schema_degree",
                self.remove_schema_degree,
                "Remove schema degree",
            ),
            (
                "timeline.score.delete_schema_instance",
                self.delete_schema_instance,
                "Delete schema instance",
            ),
            (
                "timeline.score.finish_schema_instance",
                self.finish_schema_instance,
                "Finish schema instance",
            ),
        ]:
            commands.register(name, callback, text)

        return v_toolbar

    def load_svg_data(self, data: str) -> None:
        if not data:
            logger.error("Score viewer got no SVG data to load.")
            return
        self.score_root = etree.fromstring(data, None)
        if not (x_pos := self.timeline.get_data("viewer_beat_x")):
            beat_x_pos, success = self.timeline.set_data(
                "viewer_beat_x", self._get_beat_x_pos(self.score_root)
            )
            if not success or not beat_x_pos:
                tilia.errors.display(
                    tilia.errors.SCORE_SVG_CREATE_ERROR,
                    "File not properly set up. Beat positions not found.",
                )
                return
            else:
                self.beat_x_position = {
                    float(beat): float(x) for beat, x in beat_x_pos.items()
                }
        else:
            # `_get_beat_x_pos` strips data-marker elements as a side effect.
            # When viewer_beat_x is already cached we skip it, so the markers
            # can survive into the rendered SVG. Qt emits a font warning per
            # marker per paint (issue #513), which both floods the log and
            # tanks frame rate — strip them here too.
            self._strip_beat_x_markers(self.score_root)
            self.beat_x_position = {float(beat): float(x) for beat, x in x_pos.items()}
        self._assign_notehead_ids(self.score_root)
        self.timeline.save_svg_data(str(etree.tostring(self.score_root), "utf-8"))

        self.setParent(get(Get.MAIN_WINDOW))
        self.score_renderer.load(bytearray(etree.tostring(self.score_root)))
        self.is_svg_loaded = True

        for item in self.scene.items():
            if isinstance(item, SvgStaveNote) or isinstance(item, QGraphicsSvgItem):
                self.scene.removeItem(item)

        bg = QGraphicsSvgItem()
        bg.setZValue(0)
        bg.setSharedRenderer(self.score_renderer)
        self.scene.addItem(bg)
        self.create_stavenotes(self.score_root)
        self._index_noteheads(self.score_root)
        if self.drop_highlight.scene() is None:
            self.scene.addItem(self.drop_highlight)
        self._redraw_schema_instances()

        if not self.isVisible() and not self.is_hidden:
            self.parentWidget().addDockWidget(
                Qt.DockWidgetArea.BottomDockWidgetArea, self
            )
            self.show()

        self.view.check_scale()

    @staticmethod
    def _extract_beat_position_markers(
        root: etree._Element,
    ) -> Iterator[tuple[etree._Element, list[str]]]:
        """Yield ``(element, ␟-parts)`` for each near-zero-font-size
        ``<g class='vf-text'>`` data marker carrying a 3-part payload.

        Markers that lack the expected payload have their font-size bumped
        to ``15px`` (so they render visibly) and are skipped. Callers are
        responsible for removing the yielded elements.
        """
        for e in root.findall(".//g[@class='vf-text']", None):
            if not len(e):
                continue
            try:
                if float(e[0].attrib["font-size"].strip("px")) > 1:
                    continue
            except (KeyError, ValueError):
                continue
            parts = (e[0].text or "").split("␟")
            if len(parts) != 3:
                e[0].attrib["font-size"] = "15px"
                continue
            yield e, parts

    @staticmethod
    def _strip_beat_x_markers(root: etree._Element) -> None:
        """Remove the data-marker text elements that `_get_beat_x_pos`
        strips on first load. Used when reloading an already-processed SVG.
        """
        for e, _ in SvgViewer._extract_beat_position_markers(root):
            e.getparent().remove(e)

    def _get_beat_x_pos(self, root: etree._Element) -> dict[float, float]:
        x_stamps = {}
        measure_divs = {}
        for e, parts in self._extract_beat_position_markers(root):
            e.getparent().remove(e)

            measure, beat_div, max_div = map(int, parts)
            if x_stamps.get(measure):
                if cur_x := x_stamps[measure].get(beat_div):
                    if cur_x > (x := float(e[0].attrib["x"])):
                        x_stamps[measure][beat_div] = round(x, 3)
                else:
                    x_stamps[measure][beat_div] = round(float(e[0].attrib["x"]), 3)

            else:
                x_stamps[measure] = {beat_div: round(float(e[0].attrib["x"]), 3)}
                measure_divs[measure] = max_div

        return {
            measure + beat_div / measure_divs[measure]: x
            for measure, value in x_stamps.items()
            for beat_div, x in value.items()
        }

    def create_stavenotes(self, root: etree._Element) -> None:
        def process(element: etree._Element):
            if element.attrib.get("class", "none") != "vf-stavenote":
                for child in element:
                    process(child)
            else:
                id = element.attrib.get("id")
                stavenote = SvgStaveNote(
                    self.score_renderer, id, self._get_closest_time
                )
                self.stavenotes[id] = stavenote
                self.scene.addItem(stavenote)
                stavenote.seek_x = x_pos[
                    bisect(x_pos, stavenote.sceneBoundingRect().right()) - 1
                ]

        x_pos = list(self.beat_x_position.values())
        self.stavenotes = {}
        process(root)

    @staticmethod
    def _assign_notehead_ids(root: etree._Element) -> None:
        """Gives each notehead an id, so schema degrees can be placed on it.

        OSMD only gives ids to stave notes (a chord is one stave note), so
        each notehead gets its stave note's id and its position in it. They
        are saved with the SVG, so they stay the same when the file is opened
        again.
        """
        for stavenote in root.iter():
            if stavenote.get("class") != "vf-stavenote" or not stavenote.get("id"):
                continue
            noteheads = [
                e for e in stavenote.iter() if e.get("class") == NOTEHEAD_CLASS
            ]
            for k, notehead in enumerate(noteheads):
                if not notehead.get("id"):
                    notehead.set("id", f"{stavenote.get('id')}-notehead{k}")

    def _index_noteheads(self, root: etree._Element) -> None:
        self.noteheads = {}
        self.notehead_unit = DEFAULT_NOTEHEAD_HEIGHT
        for stavenote in root.iter():
            if stavenote.get("class") != "vf-stavenote":
                continue
            for notehead in stavenote.iter():
                if notehead.get("class") != NOTEHEAD_CLASS or not notehead.get("id"):
                    continue
                rect = self.score_renderer.boundsOnElement(notehead.get("id"))
                if not rect.isEmpty():
                    self.noteheads[notehead.get("id")] = (rect, stavenote.get("id"))
        if self.noteheads:
            self.notehead_unit = median(r.height() for r, _ in self.noteheads.values())
        self.system_rect = self._get_system_rect(root)

    def _get_system_rect(self, root: etree._Element) -> QRectF:
        """Where the staves and what is drawn on them are."""
        rect = QRectF()
        for staffline in root.iter():
            if staffline.get("class") == "staffline" and staffline.get("id"):
                rect = rect.united(
                    self.score_renderer.boundsOnElement(staffline.get("id"))
                )
        for stavenote in self.stavenotes.values():
            rect = rect.united(stavenote.sceneBoundingRect())
        for notehead, _ in self.noteheads.values():
            rect = rect.united(notehead)
        return rect

    def notehead_at(self, pos: QPointF) -> str | None:
        """The notehead under `pos`, or the closest one nearby."""
        closest, distance = None, float("inf")
        for id, (rect, _) in self.noteheads.items():
            if rect.contains(pos):
                return id
            d = (rect.center() - pos).manhattanLength()
            if d < distance and d <= rect.height() * (1 + NOTEHEAD_DROP_TOLERANCE):
                closest, distance = id, d
        return closest

    def _get_drag_actions(self) -> dict[str, Callable[[QPointF], None]]:
        def _start_drag(start_pos: QPointF) -> None:
            self.filter_selection(SvgTlaAnnotation)
            self.drag_pos = start_pos

        def _while_drag(current_pos: QPointF) -> None:
            d_pos = current_pos - self.drag_pos
            for item in self.scene.selectedItems():
                item.moveBy(d_pos.x(), d_pos.y())
            self.drag_pos = current_pos

        def _after_drag(final_pos: QPointF) -> None:
            d_pos = final_pos - self.drag_pos
            for item in self.scene.selectedItems():
                item.moveBy(d_pos.x(), d_pos.y())
                self.save_tla_annotation(item)
            post(Post.APP_STATE_RECORD, "score annotation")

        return {"press": _start_drag, "move": _while_drag, "release": _after_drag}

    def remove_annotation(self, tl_component_id) -> None:
        viewer_ids = [
            v_id
            for v_id, value in self.tla_annotations.items()
            if value["component"] == tl_component_id
        ]
        for viewer_id in viewer_ids:
            self.scene.removeItem(self.tla_annotations[viewer_id]["annotation"])
            self.tla_annotations.pop(viewer_id)

    def update_annotation(self, tl_component_id) -> None:
        data: dict = self.timeline.get_component(tl_component_id).get_viewer_data()
        if data["viewer_id"] in self.tla_annotations.keys():
            component_id = data["viewer_id"]
            self.scene.removeItem(self.tla_annotations[component_id]["annotation"])
            self.tla_annotations.pop(component_id)
        annotation = self.create_annotation(
            data["text"], data["viewer_id"], data["x"], data["y"], data["font_size"]
        )
        self.tla_annotations[data["viewer_id"]] = {
            "component": tl_component_id,
            "annotation": annotation,
        }

    def filter_selection(self, type: type[SvgStaveNote | SvgTlaAnnotation]) -> None:
        for selected in self.scene.selectedItems():
            if not isinstance(selected, type):
                selected.setSelected(False)

    def save_tla_annotation(self, item: SvgTlaAnnotation) -> None:
        self.timeline.get_component(
            self.tla_annotations[item.id]["component"]
        ).save_data(
            x=item.x(),
            y=item.y(),
            viewer_id=item.id,
            text=item.text(),
            font_size=item.font().pointSize(),
        )

    def _check_tla_id(self, id) -> None:
        if self.next_tla_id <= id:
            self.next_tla_id = id + 1

    def create_annotation(
        self, text: str, id: int, x: float, y: float, font_size: int = 16
    ) -> SvgTlaAnnotation:
        new_annotation = SvgTlaAnnotation(
            text, id, x, y, font_size, self._get_drag_actions()
        )
        self._check_tla_id(id)
        self.scene.addItem(new_annotation)
        return new_annotation

    def annotation_add(self, text: str | None = None) -> None:
        self.filter_selection(SvgStaveNote)
        if not (to_add := self.scene.selectedItems()):
            return
        if text is None:
            success, text = get(
                Get.FROM_USER_STRING, "Score Annotation", "Add annotation"
            )
            if not success:
                return
        if not text:
            return
        for item in to_add:
            new_annotation = self.create_annotation(
                text, self.next_tla_id, item.x(), item.y()
            )
            item.setSelected(False)
            new_annotation.setSelected(True)
            (score_annotation, _) = self.timeline.create_component(
                kind=ComponentKind.SCORE_ANNOTATION
            )
            self.tla_annotations[new_annotation.id] = {
                "component": score_annotation.id,
                "annotation": new_annotation,
            }
            self.save_tla_annotation(new_annotation)
        post(Post.APP_STATE_RECORD, "score annotation")

    def annotation_delete(self) -> None:
        self.filter_selection(SvgTlaAnnotation)
        if not (to_delete := self.scene.selectedItems()):
            return
        tl = self.timeline
        self.timeline.delete_components(
            [
                tl.get_component(self.tla_annotations[item.id]["component"])
                for item in to_delete
            ]
        )
        post(Post.APP_STATE_RECORD, "score annotation")

    def annotation_edit(self, text: str | None = None) -> None:
        self.filter_selection(SvgTlaAnnotation)
        if not (to_edit := self.scene.selectedItems()):
            return
        for item in to_edit:
            if text is None:
                success, annotation = get(
                    Get.FROM_USER_STRING,
                    "Score Annotation",
                    "Edit Annotation",
                    text=item.text(),
                )
                if not success:
                    continue
            else:
                annotation = text
            if not annotation:
                if get(
                    Get.FROM_USER_YES_OR_NO,
                    "Edit annotation",
                    "No text inputted. Delete annotation?",
                ):
                    tl = self.timeline
                    self.timeline.delete_components(
                        [tl.get_component(self.tla_annotations[item.id]["component"])]
                    )
                    post(Post.APP_STATE_RECORD, "score annotation")
                continue

            item.setText(annotation)
            item.setSelected(False)
            self.save_tla_annotation(item)
            post(Post.APP_STATE_RECORD, "score annotation")

    def annotation_font_dec(self) -> None:
        self.filter_selection(SvgTlaAnnotation)
        if not (to_edit := self.scene.selectedItems()):
            return
        for item in to_edit:
            font = item.font()
            if font.pointSize() < 2:
                continue
            font.setPointSize(font.pointSize() // 2)
            item.setFont(font)
            self.save_tla_annotation(item)
        post(Post.APP_STATE_RECORD, "score annotation")

    def annotation_font_inc(self) -> None:
        self.filter_selection(SvgTlaAnnotation)
        if not (to_edit := self.scene.selectedItems()):
            return
        for item in to_edit:
            font = item.font()
            font.setPointSize(font.pointSize() * 2)
            item.setFont(font)
            self.save_tla_annotation(item)
        post(Post.APP_STATE_RECORD, "score annotation")

    def toggle_schema_palette(self) -> None:
        self.schema_palette.setVisible(not self.schema_palette.isVisible())

    def _schema_instance(self, id: int | None):
        if id is None:
            return None
        try:
            component = self.timeline.get_component(id)
        except KeyError:
            return None
        if component.KIND != ComponentKind.SCHEMA_INSTANCE:
            return None
        return component

    def set_active_schema_instance(self, id: int | None) -> None:
        """The instance dropped degrees go to. None starts a new one on the
        next drop."""
        instance = self._schema_instance(id)
        self.active_schema_instance = instance.id if instance else None
        if instance:
            self.schema_palette.show_instance(instance.schema, instance.degrees)
        else:
            self.schema_palette.show_instance(None)

    def add_schema_degree(
        self,
        notehead: str,
        schema: str,
        stage: int,
        voice: str,
        index: int,
        value: int | None = None,
        accidental: str | None = None,
        instance_id: int | None = None,
    ) -> bool:
        """Places a schema's degree on a notehead.

        It goes to `instance_id`, or else to the active instance, if that is
        an instance of `schema`; otherwise it starts a new instance. A degree
        already placed for that stage, voice and index moves to the
        notehead. `value` and `accidental` default to the schema's.
        """
        if notehead not in self.noteheads:
            logger.error(f"No notehead with id {notehead!r} in the score.")
            return False
        instance = self._schema_instance(
            instance_id if instance_id is not None else self.active_schema_instance
        )
        if instance and instance.schema["name"] != schema:
            instance = None
        definition = instance.schema if instance else library.get_schema(schema)
        if definition is None:
            logger.error(f"No schema named {schema!r}.")
            return False
        if (defined := stage_degree(definition, stage, voice, index)) is None:
            logger.error(f"{schema} has no {voice} degree {index} in stage {stage}.")
            return False

        placed = {
            "notehead": notehead,
            "stage": stage,
            "voice": voice,
            "index": index,
            "value": defined["value"] if value is None else value,
            "accidental": (
                defined.get("accidental", "=") if accidental is None else accidental
            ),
        }
        if instance:
            degrees = [
                d
                for d in instance.degrees
                if d["notehead"] != notehead
                and (d["stage"], d["voice"], d["index"]) != (stage, voice, index)
            ]
            _, success = self.timeline.set_component_data(
                instance.id, "degrees", degrees + [placed]
            )
            if not success:
                return False
        else:
            instance, reason = self.timeline.create_component(
                ComponentKind.SCHEMA_INSTANCE, schema=definition, degrees=[placed]
            )
            if instance is None:
                logger.error(f"Couldn't create schema instance: {reason}")
                return False

        self.set_active_schema_instance(instance.id)
        post(Post.APP_STATE_RECORD, "add schema degree")
        return True

    def _remove_schema_degrees(self, instance_id: int, noteheads: set[str]) -> bool:
        if (instance := self._schema_instance(instance_id)) is None:
            return False
        degrees = [d for d in instance.degrees if d["notehead"] not in noteheads]
        if len(degrees) == len(instance.degrees):
            return False
        if degrees:
            self.timeline.set_component_data(instance.id, "degrees", degrees)
        else:
            self.timeline.delete_components([instance])
        return True

    def remove_schema_degree(self, instance_id: int, notehead: str) -> bool:
        """Removes a placed degree, and its instance if it was the last."""
        if not self._remove_schema_degrees(instance_id, {notehead}):
            return False
        self.set_active_schema_instance(self.active_schema_instance)
        post(Post.APP_STATE_RECORD, "remove schema degree")
        return True

    def schema_degrees_delete(self) -> bool:
        """Removes the selected degrees."""
        by_instance: dict[int, set[str]] = {}
        for item in self.scene.selectedItems():
            if isinstance(item, SvgSchemaDegree):
                by_instance.setdefault(item.instance_id, set()).add(item.notehead)
        if not by_instance:
            return False
        for instance_id, noteheads in by_instance.items():
            self._remove_schema_degrees(instance_id, noteheads)
        self.set_active_schema_instance(self.active_schema_instance)
        post(Post.APP_STATE_RECORD, "remove schema degree")
        return True

    def delete_schema_instance(self, instance_id: int | None = None) -> bool:
        """Deletes an instance, by default the active one."""
        instance = self._schema_instance(
            self.active_schema_instance if instance_id is None else instance_id
        )
        if instance is None:
            return False
        self.timeline.delete_components([instance])
        self.set_active_schema_instance(None)
        post(Post.APP_STATE_RECORD, "delete schema instance")
        return True

    def finish_schema_instance(self) -> None:
        """The next dropped degree starts a new instance."""
        self.set_active_schema_instance(None)

    def update_schema_instance(self, _: int) -> None:
        self._redraw_schema_instances()
        if self.active_schema_instance is not None:
            self.set_active_schema_instance(self.active_schema_instance)

    def remove_schema_instance(self, id: int) -> None:
        if (drawn := self.schema_instances.pop(id, None)) is not None:
            for item in drawn.items():
                self.scene.removeItem(item)
        # The others may move into the rows it leaves.
        self._redraw_schema_instances()
        if id == self.active_schema_instance:
            self.set_active_schema_instance(None)

    def _clear_schema_items(self) -> None:
        for drawn in self.schema_instances.values():
            for item in drawn.items():
                if item.scene() is self.scene:
                    self.scene.removeItem(item)
        self.schema_instances = {}

    def _redraw_schema_instances(self) -> None:
        # Instances share rows in the bands around the system, so any change
        # can move the others: lay them all out again.
        self._clear_schema_items()
        if not self.is_svg_loaded:
            return
        instances = self.timeline.get_components_by_attr(
            "KIND", ComponentKind.SCHEMA_INSTANCE
        )
        for instance in instances:
            for placed in instance.degrees:
                if placed["notehead"] not in self.noteheads:
                    logger.error(
                        f"Schema degree on missing notehead {placed['notehead']!r}."
                    )
        self.schema_instances = layout_schema_instances(
            [(i.id, i.schema, i.degrees) for i in instances],
            {id: rect for id, (rect, _) in self.noteheads.items()},
            self.system_rect,
            self.notehead_unit,
            self._on_schema_degree_press,
            self._on_schema_degree_double_click,
        )
        for drawn in self.schema_instances.values():
            for item in drawn.items():
                self.scene.addItem(item)
        self.view.fit_scene()

    def notehead_times(self, notehead: str) -> list[float]:
        """When the note is played: one time per pass through its measure."""
        if notehead not in self.noteheads:
            return []
        if (stavenote := self.stavenotes.get(self.noteheads[notehead][1])) is None:
            return []
        return self._get_time_from_scene_x({0: stavenote.seek_x}).get(0, [])

    def _end_of_notes_at(self, time: float) -> float:
        """When the notes that start at `time` end: the longest of them."""
        ends = [
            note.end
            for note in self.timeline.get_components_by_attr("KIND", ComponentKind.NOTE)
            if abs(note.start - time) < NOTE_TIME_TOLERANCE
        ]
        return max(ends, default=time)

    def schema_instance_spans(self, instance) -> list[tuple[float, float]]:
        """The times an instance covers: from its first note's start to its
        last note's end, once per pass if its measures repeat."""
        times = [
            t for d in instance.degrees if (t := self.notehead_times(d["notehead"]))
        ]
        if not times:
            return []
        spans = []
        for k in range(min(len(t) for t in times)):
            starts = [t[k] for t in times]
            spans.append((min(starts), self._end_of_notes_at(max(starts))))
        return spans

    def _on_schema_degree_press(
        self, item: SvgSchemaDegree, modifiers: Qt.KeyboardModifier
    ) -> None:
        if Qt.KeyboardModifier.ShiftModifier in modifiers:
            commands.execute(
                "timeline.score.remove_schema_degree",
                instance_id=item.instance_id,
                notehead=item.notehead,
            )
            return
        self.set_active_schema_instance(item.instance_id)

    def _on_schema_degree_double_click(self, item: SvgSchemaDegree) -> None:
        if stavenote := self.stavenotes.get(self.noteheads[item.notehead][1]):
            stavenote.seek()

    def _on_degree_drag(self, pos: QPointF | None) -> None:
        """Highlights the notehead a degree dragged to `pos` would land on."""
        notehead = self.notehead_at(pos) if pos is not None else None
        if notehead is None:
            self.drop_highlight.hide()
            return
        rect = self.noteheads[notehead][0]
        margin = rect.height() * 0.3
        self.drop_highlight.setRect(rect.adjusted(-margin, -margin, margin, margin))
        self.drop_highlight.show()

    def _on_degree_drop(self, payload: dict, pos: QPointF) -> None:
        self.drop_highlight.hide()
        if (notehead := self.notehead_at(pos)) is None:
            return
        commands.execute(
            "timeline.score.add_schema_degree",
            notehead=notehead,
            schema=payload["schema"],
            stage=payload["stage"],
            voice=payload["voice"],
            index=payload["index"],
            value=payload.get("value"),
            accidental=payload.get("accidental"),
        )

    def _get_time_from_scene_x(self, xs: dict[int, float]) -> dict[int, list[float]]:
        output = {}
        beat_pos = {}
        beats = list(self.beat_x_position.keys())
        x_pos = list(self.beat_x_position.values())
        for key, x in xs.items():
            x = round(x, 3)
            if x in x_pos:
                idx = x_pos.index(x)
                beat_pos[key] = ((b := beats[idx]) // 1, b % 1)
                continue

            idx = bisect(x_pos, x)
            if idx == 0 and len(beats) == 0:
                b0 = 0
                b1 = 1
                x0 = self.scene.sceneRect().left()
                x1 = self.scene.sceneRect().right()
            elif idx == 0:
                b0 = 0
                b1 = beats[0]
                x0 = self.scene.sceneRect().left()
                x1 = x_pos[0]
            elif idx == len(beats):
                b0 = beats[idx - 1]
                b1 = round(-(-b0 // 1))
                x0 = x_pos[idx - 1]
                x1 = self.scene.sceneRect().right()
            else:
                b0 = beats[idx - 1]
                b1 = beats[idx]
                x0 = x_pos[idx - 1]
                x1 = x_pos[idx]

            beat = b0 + (b1 - b0) * (x - x0) / (x1 - x0)
            beat_pos[key] = (beat // 1, beat % 1)
            self.beat_x_position[beat] = x

            self.beat_x_position = {
                k: self.beat_x_position[k] for k in sorted(self.beat_x_position.keys())
            }

        beat_tl = get(
            Get.TIMELINE_COLLECTION
        ).get_beat_timeline_for_measure_calculation()

        if not beat_tl or not beat_tl.measure_count:
            return {}

        for key, beat in beat_pos.items():
            t = beat_tl.get_time_by_measure(*beat)
            if not t:
                t = (
                    [0]
                    if beat[0] < min(beat_tl.measure_numbers)
                    else [get(Get.MEDIA_DURATION)]
                )
            output[key] = t

        return output

    def _get_scene_x_from_time(self, time: float) -> float:
        beat_tl = get(
            Get.TIMELINE_COLLECTION
        ).get_beat_timeline_for_measure_calculation()
        if not beat_tl:
            return 0
        beat = beat_tl.get_metric_fraction_by_time(time)
        if x := self.beat_x_position.get(beat):
            return x
        beats = list(self.beat_x_position.keys())
        x_pos = list(self.beat_x_position.values())
        idx = bisect(beats, beat)
        if idx == 0:
            return x_pos[0]
        if idx == len(beats):
            return x_pos[idx - 1]
        return (beat - beats[idx - 1]) / (beats[idx] - beats[idx - 1]) * (
            x_pos[idx] - x_pos[idx - 1]
        ) + x_pos[idx - 1]

    def _get_closest_time(
        self, x: float
    ) -> tuple[tuple[float, float], None | tuple[float, float]]:
        times = self._get_time_from_scene_x({0: x}).get(0)
        current_time = get(Get.SELECTED_TIME)
        idx = bisect(times, current_time)
        if idx == 0:
            return ((times[0], current_time - times[0]), None)
        if idx == len(times):
            return ((times[-1], current_time - times[0]), None)
        return (
            ((t0 := times[idx - 1]), current_time - t0),
            ((t1 := times[idx]), current_time - t1),
        )

    def update_measure_tracker(self, start: float, end: float) -> None:
        if (new_visible_times := [start, end]) == self.visible_times:
            return
        self.visible_times = new_visible_times
        if start != end:
            self.timeline_ui.update_measure_tracker_position(start, end)
            self.timeline_ui.measure_tracker.show()
        else:
            self.timeline_ui.measure_tracker.hide()

    def scroll_to_time(self, time: float, is_centered: bool):
        self.cur_t_x = self._get_scene_x_from_time(time)
        if is_centered:
            self.view.scroll_to_x(self.cur_t_x)
            return
        cur_viewport_x = self.view.current_viewport_x
        if (
            (cur_viewport_x[0] + self.scroll_margin)
            < self.cur_t_x
            < (cur_viewport_x[1] - self.scroll_margin)
        ):
            return
        self.view.scroll_to_x(self.cur_t_x + self.scroll_offset)

    def _update_scroll_margins(self):
        cur_viewport_x = self.view.current_viewport_x
        self.scroll_margin = (cur_viewport_x[1] - cur_viewport_x[0]) / 10
        self.scroll_offset = self.scroll_margin * 4

    def deleteLater(self):
        super().deleteLater()
        stop_serving_all(self)
        stop_listening_to_all(self)

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._update_scroll_margins()

    def hideEvent(self, a0) -> None:
        try:
            self.timeline_ui.measure_tracker.hide()
        except RuntimeError:
            pass

        self.is_hidden = True
        return super().hideEvent(a0)

    def showEvent(self, event):
        self.scroll_to_time(get(Get.SELECTED_TIME), True)
        if self.timeline_ui:
            self.timeline_ui.measure_tracker.show()
        self.is_hidden = False
        return super().showEvent(event)

    def enterEvent(self, event) -> None:
        self.setFocus()
        return super().enterEvent(event)

    def leaveEvent(self, a0) -> None:
        self.clearFocus()
        return super().leaveEvent(a0)

    def keyPressEvent(self, a0) -> None:
        # listen here because these shortcuts are shared with the main window
        key_comb_to_action = {
            QKeyCombination(
                Qt.KeyboardModifier.NoModifier, Qt.Key.Key_Delete
            ): lambda: self.schema_degrees_delete()
            or self.annotation_delete(),
            QKeyCombination(
                Qt.KeyboardModifier.NoModifier, Qt.Key.Key_Return
            ): self.annotation_add,
        }
        if action := key_comb_to_action.get(a0.keyCombination()):
            a0.accept()
            action()
        else:
            return super().keyPressEvent(a0)


class SvgGraphicsView(QGraphicsView):
    def __init__(
        self,
        get_times: Callable[[dict[int, float]], dict[int, list[float]]],
        update_measure_tracker: Callable[[float, float], None],
        update_scroll_margins: Callable[..., None],
        *args,
        on_degree_drag: Callable[[QPointF | None], None] | None = None,
        on_degree_drop: Callable[[dict, QPointF], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.on_degree_drag = on_degree_drag
        self.on_degree_drop = on_degree_drop
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.setFrameShape(QFrame.Shape.Panel)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setBackgroundBrush(QColor("white"))
        self.get_times = get_times
        self.current_viewport_x = {0: 0.0, 1: 0.0}
        self.current_viewport_y_center = 0.0
        self.current_viewport_x_center = 0.0
        self._viewport_updated()
        self.update_measure_tracker = update_measure_tracker
        self.update_scroll_margins = update_scroll_margins
        # Where the view is centred now: current_viewport_x_center is only
        # updated when the view is painted.
        self.smooth_x = SmoothSetter(
            lambda: self.mapToScene(self.viewport().rect().center()).x(),
            self._center_on_x,
            parent=self,
        )

    def _viewport_updated(self) -> bool:
        viewport = self.mapToScene(self.viewport().geometry()).boundingRect()
        self.current_viewport_y_center = viewport.center().y()
        self.current_viewport_x_center = viewport.center().x()
        if (
            vp := {0: viewport.left(), 1: viewport.right()}
        ).values() == self.current_viewport_x.values():
            return False

        self.current_viewport_x = vp
        return True

    def _check_scene_bounding_rect(self) -> None:
        if (
            scene_bounding_rect := self.scene().itemsBoundingRect()
        ) != self.scene().sceneRect():
            self.scene().setSceneRect(scene_bounding_rect)

    def fit_scene(self) -> None:
        """Fits the scene to what is in it now, as items were added."""
        self._check_scene_bounding_rect()
        self.check_scale()

    def check_scale(self) -> None:
        if (
            visible := self.mapToScene(self.viewport().geometry())
            .boundingRect()
            .height()
            - (
                h_scroll_bar.height()
                if (h_scroll_bar := self.horizontalScrollBar()).maximum() != 0
                else 0
            )
        ) < (actual := self.sceneRect().height()):
            self.setTransform(
                self.transform().scale((zoom_level := visible / actual), zoom_level)
            )
            self._check_scene_bounding_rect()

    def scroll_to_x(self, x: float):
        self.smooth_x(x)

    def _center_on_x(self, x: float) -> None:
        old, has_sb = (
            (sb.value(), True) if (sb := self.verticalScrollBar()) else (None, False)
        )
        self.centerOn(x, 0)
        if has_sb:
            self.verticalScrollBar().setValue(old)

    def _is_degree_drag(self, event) -> bool:
        return self.on_degree_drop is not None and event.mimeData().hasFormat(
            DEGREE_MIME_TYPE
        )

    def dragEnterEvent(self, event) -> None:
        if not self._is_degree_drag(event):
            return super().dragEnterEvent(event)
        event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if not self._is_degree_drag(event):
            return super().dragMoveEvent(event)
        if self.on_degree_drag:
            self.on_degree_drag(self.mapToScene(event.position().toPoint()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        if self.on_degree_drag:
            self.on_degree_drag(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if not self._is_degree_drag(event):
            return super().dropEvent(event)
        if (payload := read_degree_mime_data(event.mimeData())) is not None:
            self.on_degree_drop(payload, self.mapToScene(event.position().toPoint()))
        event.acceptProposedAction()

    def wheelEvent(self, event):
        if Qt.KeyboardModifier.ControlModifier not in event.modifiers():
            return super().wheelEvent(event)

        if Qt.KeyboardModifier.ShiftModifier in event.modifiers():
            dx = event.angleDelta().y()
            dy = event.angleDelta().x()
        else:
            dx = event.angleDelta().x()
            dy = event.angleDelta().y()

        if event.inverted():
            temp = dx
            dx = dy
            dy = temp

        old_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        if dy > 0:
            self.setTransform(self.transform().scale(1.1, 1.1))
        else:
            self.setTransform(self.transform().scale(1 / 1.1, 1 / 1.1))
        self.setTransformationAnchor(old_anchor)
        self.update_scroll_margins()
        self._check_scene_bounding_rect()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._viewport_updated():
            times = self.get_times(self.current_viewport_x).values()
            if not times:
                # Beat timeline has been deleted?
                # This means the svg viewer won't scroll?
                return
            else:
                # This relies on the order dictionary entries,
                # which is undefined.
                # We should use another data structure if we care about order.
                start_ts, end_ts = list(times)

            current_time = get(Get.SELECTED_TIME)
            start_time = start_ts[
                s_idx - 1 if (s_idx := bisect(start_ts, current_time)) != 0 else s_idx
            ]
            end_time = (
                end_ts[e_idx]
                if (e_idx := bisect(end_ts, start_time)) != len(end_ts)
                else (
                    get(Get.MEDIA_DURATION) if start_time != 0 and end_ts[0] != 0 else 0
                )
            )
            self.update_measure_tracker(start_time, end_time)


class SvgStaveNote(QGraphicsSvgItem):
    def __init__(
        self,
        renderer: QSvgRenderer,
        id: str,
        get_time: Callable[
            [float], tuple[tuple[float, float], None | tuple[float, float]]
        ],
    ) -> None:
        super().__init__()
        self.setSharedRenderer(renderer)
        self.setElementId(id)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setPos(renderer.boundsOnElement(id).topLeft())
        self.setZValue(1)
        self.seek_x = 0.0
        self.get_time = get_time

    def paint(self, painter, option, widget) -> None:
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setRenderHint(painter.RenderHint.Antialiasing, True)
            painter.setCompositionMode(painter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(self.boundingRect(), Qt.GlobalColor.red)

    def seek(self) -> None:
        """Seeks to the note's time closest to the current one."""
        t0, t1 = self.get_time(self.seek_x)
        if not t1 or abs(t0[1]) < abs(t1[1]):
            commands.execute("media.seek", t0[0])
        else:
            commands.execute("media.seek", t1[0])

    def mouseDoubleClickEvent(self, event) -> None:
        self.seek()
        return super().mouseDoubleClickEvent(event)


class SvgTlaAnnotation(QGraphicsSimpleTextItem):
    def __init__(
        self,
        text: str,
        id: int,
        x: float,
        y: float,
        font_size: int,
        drag_actions: dict[str, Callable[[QPointF], None]],
    ) -> None:
        super().__init__(text)
        self.id = id
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setPos(x, y)
        font = self.font()
        font.setPointSize(font_size)
        font.setStyle(QFont.Style.StyleOblique)
        font.setWeight(QFont.Weight.Medium)
        font.setStyleHint(QFont.StyleHint.Serif, QFont.StyleStrategy.PreferDevice)
        self.setFont(font)
        self.setZValue(1)
        self.drag_actions = drag_actions

    def paint(self, painter, option, widget) -> None:
        self.setBrush(Qt.GlobalColor.red if self.isSelected() else Qt.GlobalColor.black)
        return super().paint(painter, option, widget)

    def mousePressEvent(self, event) -> None:
        self.drag_actions["press"](event.scenePos())
        return super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.drag_actions["move"](event.scenePos())
        return super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.drag_actions["release"](event.scenePos())
        return super().mouseReleaseEvent(event)
