"""The score viewer's schema panel: pick a schema, drag its degrees onto
noteheads."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tilia.timelines.score.schema import family_name
from tilia.ui.schema import library
from tilia.ui.schema.diagram import SchemaDiagram
from tilia.ui.schema.editor import edit_schema

PALETTE_WIDTH = 340
HINT_NO_INSTANCE = "Drag a degree onto a notehead to start a new instance."


class SchemaPalette(QWidget):
    """Shows one schema at a time, either the library's or, while an instance
    is active, the instance's own copy (which may differ, e.g. in a file
    from someone else's library).

    `on_finish` and `on_delete` act on the active instance. Whoever owns
    the palette calls `refresh_library` when the library changes.
    """

    def __init__(
        self,
        on_finish: Callable[[], None],
        on_delete: Callable[[], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.on_finish = on_finish
        self.on_delete = on_delete
        self.setFixedWidth(PALETTE_WIDTH)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<b>Schemata</b>"))

        self.combo = QComboBox()
        self.combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self.combo)

        buttons = QHBoxLayout()
        self.new_button = QPushButton("New…")
        self.edit_button = QPushButton("Edit…")
        self.delete_button = QPushButton("Delete")
        for button in (self.new_button, self.edit_button, self.delete_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.new_button.clicked.connect(self.new_schema)
        self.edit_button.clicked.connect(self.edit_current_schema)
        self.delete_button.clicked.connect(self.delete_current_schema)

        self.diagram = SchemaDiagram(draggable=True)
        layout.addWidget(self.diagram, stretch=1)
        layout.addWidget(QLabel("Drag a circle onto a notehead to mark it."))

        self.instance_label = QLabel(HINT_NO_INSTANCE)
        self.instance_label.setWordWrap(True)
        layout.addWidget(self.instance_label)
        instance_buttons = QHBoxLayout()
        self.finish_button = QPushButton("Finish instance")
        self.delete_instance_button = QPushButton("Delete instance")
        instance_buttons.addWidget(self.finish_button)
        instance_buttons.addWidget(self.delete_instance_button)
        layout.addLayout(instance_buttons)
        self.finish_button.clicked.connect(lambda: self.on_finish())
        self.delete_instance_button.clicked.connect(lambda: self.on_delete())

        self.instance_schema: dict | None = None
        self.refresh_library()
        self.show_instance(None)

    @property
    def schema(self) -> dict | None:
        """The schema whose degrees are dragged from the palette."""
        return self.diagram.schema

    def refresh_library(self, select: str | None = None) -> None:
        current = select or (self.schema["name"] if self.schema else None)
        self.combo.blockSignals(True)
        self.combo.clear()
        family = None
        for schema in library.get_schemata():
            if family is not None and family_name(schema) != family:
                self.combo.insertSeparator(self.combo.count())
            family = family_name(schema)
            self.combo.addItem(schema["name"], schema["name"])
        self.combo.blockSignals(False)
        index = self.combo.findData(current) if current else -1
        self.combo.setCurrentIndex(index if index >= 0 else 0)
        self._on_combo_changed()

    def select_schema(self, name: str) -> None:
        index = self.combo.findData(name)
        if index >= 0:
            self.combo.setCurrentIndex(index)

    def _on_combo_changed(self, *_) -> None:
        name = self.combo.currentData()
        if self.instance_schema and self.instance_schema["name"] == name:
            schema = self.instance_schema
        else:
            schema = library.get_schema(name) if name else None
            if self.instance_schema is not None:
                # Picking another schema starts a new instance with it.
                self.on_finish()
        placed = self.diagram.placed if schema is self.instance_schema else set()
        self.diagram.set_schema(schema)
        self.diagram.set_placed(placed)
        self.edit_button.setEnabled(schema is not None)
        self.delete_button.setEnabled(bool(name) and library.is_custom(name))
        self.delete_button.setText(
            "Reset" if name and library.is_starter(name) else "Delete"
        )

    def show_instance(self, schema: dict | None, degrees: list[dict] = ()) -> None:
        """Shows the active instance, or that there is none."""
        self.instance_schema = schema
        self.finish_button.setEnabled(schema is not None)
        self.delete_instance_button.setEnabled(schema is not None)
        if schema is None:
            self.instance_label.setText(HINT_NO_INSTANCE)
            self.diagram.set_placed(set())
            return

        total = sum(
            len(stage.get(v, []))
            for stage in schema["stages"]
            for v in ("upper", "inner", "lower")
        )
        self.instance_label.setText(
            f"Adding to <b>{schema['name']}</b>: {len(degrees)} of {total}"
            " degrees placed."
        )
        if self.combo.findData(schema["name"]) < 0:
            # Not in this library: show it anyway.
            self.combo.blockSignals(True)
            self.combo.addItem(f"{schema['name']} (from file)", schema["name"])
            self.combo.blockSignals(False)
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(self.combo.findData(schema["name"]))
        self.combo.blockSignals(False)
        self.diagram.set_schema(schema)
        self.diagram.set_placed({(d["stage"], d["voice"], d["index"]) for d in degrees})

    def new_schema(self) -> None:
        if schema := edit_schema():
            self.refresh_library(select=schema["name"])

    def edit_current_schema(self) -> None:
        if not self.schema:
            return
        if schema := edit_schema(self.schema):
            self.refresh_library(select=schema["name"])

    def delete_current_schema(self) -> None:
        if (name := self.combo.currentData()) and library.is_custom(name):
            library.delete_schema(name)
