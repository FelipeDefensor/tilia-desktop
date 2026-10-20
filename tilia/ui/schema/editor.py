"""The dialog to create and edit schemata."""

from __future__ import annotations

import copy
from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from tilia.timelines.score.schema import (
    DEFAULT_COLOR,
    DEGREE_VALUES,
    REGISTERS,
    STRENGTHS,
    VOICES,
    degree,
    family_name,
    validate_schema,
)
from tilia.ui.schema import library
from tilia.ui.schema.diagram import VOICE_NAMES, SchemaDiagram

ACCIDENTAL_NAMES = {"=": "none", "+": "↑ raised", "-": "↓ lowered", "~": "♮"}
STAGE_MIN_WIDTH = 230


def _combo(options: dict, current) -> QComboBox:
    combo = QComboBox()
    for value, text in options.items():
        combo.addItem(text, value)
    combo.setCurrentIndex(max(0, combo.findData(current)))
    return combo


def new_schema() -> dict:
    return {
        "name": "",
        "variant_of": "",
        "variant_short": "",
        "color": DEFAULT_COLOR,
        "stages": [
            {
                "strength": "S",
                "upper": [degree(1, "upper")],
                "inner": [],
                "lower": [degree(1, "lower")],
            }
        ],
    }


class DegreeEditor(QFrame):
    def __init__(self, data: dict, on_change: Callable, on_remove: Callable):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.data = data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self.value = _combo({v: str(v) for v in DEGREE_VALUES}, data["value"])
        self.accidental = _combo(ACCIDENTAL_NAMES, data.get("accidental", "="))
        self.register = _combo(REGISTERS, data.get("relH", ""))
        remove = QPushButton("✖")
        remove.setToolTip("Remove degree")
        remove.setFixedWidth(28)

        for widget in (self.value, self.accidental, self.register, remove):
            layout.addWidget(widget)

        def update(*_):
            data["value"] = self.value.currentData()
            data["accidental"] = self.accidental.currentData()
            if register := self.register.currentData():
                data["relH"] = register
            else:
                data.pop("relH", None)
            on_change()

        self.value.currentIndexChanged.connect(update)
        self.accidental.currentIndexChanged.connect(update)
        self.register.currentIndexChanged.connect(update)
        remove.clicked.connect(on_remove)


class StageEditor(QGroupBox):
    def __init__(
        self,
        number: int,
        data: dict,
        on_change: Callable,
        on_structure_change: Callable,
        on_remove: Callable,
    ):
        super().__init__(f"Stage {number}")
        self.data = data
        self.setMinimumWidth(STAGE_MIN_WIDTH)
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        header.addWidget(QLabel("Strength:"))
        self.strength = _combo(STRENGTHS, data["strength"])
        header.addWidget(self.strength)
        header.addStretch()
        remove = QPushButton("Remove stage")
        header.addWidget(remove)
        layout.addLayout(header)

        def set_strength(*_):
            data["strength"] = self.strength.currentData()
            on_change()

        self.strength.currentIndexChanged.connect(set_strength)
        remove.clicked.connect(on_remove)

        self.degree_editors: dict[str, list[DegreeEditor]] = {}
        self.add_buttons: dict[str, QPushButton] = {}
        for voice in VOICES:
            layout.addWidget(QLabel(f"<b>{VOICE_NAMES[voice]}</b>"))
            degrees = data.setdefault(voice, [])
            self.degree_editors[voice] = []
            for d in degrees:

                def remove_degree(*_, d=d, degrees=degrees):
                    degrees.remove(d)
                    on_structure_change()

                editor = DegreeEditor(d, on_change, remove_degree)
                self.degree_editors[voice].append(editor)
                layout.addWidget(editor)

            add = QPushButton("+ Add")
            self.add_buttons[voice] = add

            def add_degree(*_, voice=voice, degrees=degrees):
                degrees.append(degree(1, voice))
                on_structure_change()

            add.clicked.connect(add_degree)
            layout.addWidget(add)
        layout.addStretch()


class SchemaEditor(QDialog):
    """Edits a copy of a schema. `schema()` gives the result."""

    def __init__(self, schema: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.original_name = schema["name"] if schema else None
        self.setWindowTitle("Edit schema" if schema else "New schema")
        self._schema = copy.deepcopy(schema) if schema else new_schema()
        self.resize(820, 620)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(self._schema["name"])
        self.family = QComboBox()
        self.family.setEditable(True)
        families = sorted({family_name(s) for s in library.get_schemata()})
        self.family.addItems([""] + families)
        self.family.setCurrentText(self._schema.get("variant_of", ""))
        self.variant = QLineEdit(self._schema.get("variant_short", ""))
        self.color_button = QPushButton()
        self.color_button.clicked.connect(self._choose_color)
        form.addRow("Name", self.name)
        form.addRow("Family", self.family)
        form.addRow("Variant", self.variant)
        form.addRow("Color", self.color_button)
        layout.addLayout(form)

        layout.addWidget(QLabel("Stages"))
        self.stages_area = QScrollArea()
        self.stages_area.setWidgetResizable(True)
        layout.addWidget(self.stages_area, stretch=3)

        self.preview = SchemaDiagram()
        layout.addWidget(self.preview, stretch=2)

        self.error = QLabel()
        self.error.setStyleSheet("color: crimson")
        layout.addWidget(self.error)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.name.textChanged.connect(self._on_change)
        self.family.currentTextChanged.connect(self._on_change)
        self.variant.textChanged.connect(self._on_change)

        self._set_color(self._schema.get("color", DEFAULT_COLOR))
        self._build_stages()

    def _set_color(self, color: str) -> None:
        self._schema["color"] = color
        self.color_button.setText(color)
        self.color_button.setStyleSheet(f"background-color: {color}")
        self._on_change()

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._schema["color"]), self)
        if color.isValid():
            self._set_color(color.name())

    def _build_stages(self) -> None:
        container = QWidget()
        row = QHBoxLayout(container)
        self.stage_editors: list[StageEditor] = []
        stages = self._schema["stages"]
        for i, stage in enumerate(stages):

            def remove(*_, stage=stage):
                stages.remove(stage)
                self._build_stages()

            editor = StageEditor(
                i + 1, stage, self._on_change, self._build_stages, remove
            )
            self.stage_editors.append(editor)
            row.addWidget(editor)

        self.add_stage_button = QPushButton("+ Add stage")
        self.add_stage_button.clicked.connect(self.add_stage)
        row.addWidget(self.add_stage_button)
        row.addStretch()
        self.stages_area.setWidget(container)
        self._on_change()

    def add_stage(self) -> None:
        self._schema["stages"].append(
            {"strength": "W", "upper": [], "inner": [], "lower": []}
        )
        self._build_stages()

    def schema(self) -> dict:
        schema = copy.deepcopy(self._schema)
        schema["name"] = self.name.text().strip()
        schema["variant_of"] = self.family.currentText().strip()
        schema["variant_short"] = self.variant.text().strip()
        return schema

    def problem(self) -> str:
        """Why the schema can't be saved yet, or "" if it can."""
        schema = self.schema()
        if not schema["name"]:
            return "Give the schema a name."
        if not schema["stages"]:
            return "Add at least one stage."
        for i, stage in enumerate(schema["stages"]):
            if not any(stage.get(v) for v in VOICES):
                return f"Stage {i + 1} has no degrees."
        if (
            schema["name"] != self.original_name
            and library.get_schema(schema["name"]) is not None
        ):
            return f'There is already a schema named "{schema["name"]}".'
        if not validate_schema(schema):
            return "The schema is not valid."
        return ""

    def _on_change(self, *_) -> None:
        if not hasattr(self, "preview"):
            return
        schema = self.schema()
        self.preview.set_schema(schema if schema["stages"] else None)
        problem = self.problem()
        self.error.setText(problem)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setEnabled(
            not problem
        )

    def accept(self) -> None:
        if self.problem():
            return
        super().accept()


def edit_schema(schema: dict | None = None) -> dict | None:
    """Asks the user to create (schema=None) or edit a schema and saves it to
    the library. Returns the saved schema, or None if the user cancelled."""
    dialog = SchemaEditor(schema)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    result = dialog.schema()
    library.save_schema(result, replaces=dialog.original_name)
    return result
