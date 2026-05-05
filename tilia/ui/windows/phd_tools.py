import os
import sys
from pathlib import Path
from typing import cast

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QPushButton, QVBoxLayout

from tilia.parsers import get_import_function
from tilia.requests import Get, Post, get, post
from tilia.timelines.collection.collection import Timelines

# Path to the companion mpb-para-tilia project (override with env var).
MPB_TO_TILIA_PATH = Path(
    os.environ.get(
        "MPB_TO_TILIA_PATH",
        Path.home() / "dev" / "mpb-para-tilia",
    )
)
CSV_PATH = MPB_TO_TILIA_PATH / "data" / "tilia-csvs"


class PhdToolsWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhD Tools")

        try:
            self.file_code = get(Get.MEDIA_METADATA)["file code"]
        except KeyError:
            self.file_code = ""
        file_code_label = QLabel("File code")
        file_code_edit = QLineEdit()
        file_code_edit.setMaximumWidth(100)
        file_code_edit.setText(self.file_code)

        tools_label = QLabel("Tools")

        import_button = QPushButton("Import Projeto MPB data")
        import_button.clicked.connect(self.on_import_button_clicked)

        report_sections_button = QPushButton("Report sections")
        report_sections_button.clicked.connect(self.on_report_sections_button_clicked)

        get_segments_duration_button = QPushButton("Get segments duration")
        get_segments_duration_button.clicked.connect(
            self.on_get_segments_duration_button_clicked
        )

        layout = QVBoxLayout()
        layout.addWidget(file_code_label)
        layout.addWidget(file_code_edit)
        layout.addWidget(tools_label)
        layout.addWidget(import_button)
        layout.addWidget(report_sections_button)
        layout.addWidget(get_segments_duration_button)
        self.setLayout(layout)

        self.show()

    def on_import_button_clicked(self):
        self.on_report_sections_button_clicked()  # update files to be imported
        timelines = cast(Timelines, get(Get.TIMELINE_COLLECTION))

        beat_tl = timelines.get_timeline_by_attr("name", "Measures")
        if not beat_tl:
            print("ERROR: Beat timeline named 'Measures' not found.")
            return

        tl_data = [
            ("Harmony", "chord_symbols"),
            ("Keys", "keys"),
            ("Harm. functions", "functions"),
            ("Harm. segments (imp.)", "harmonic_segments"),
        ]

        for tl_name, dir_name in tl_data:
            tl = timelines.get_timeline_by_attr("name", tl_name)
            if not tl:
                print(f"ERROR: Timeline named '{tl_name}' not found.")
                continue

            csv_path = Path(CSV_PATH) / dir_name / f"{self.file_code}.csv"
            if not csv_path.exists():
                print(f"ERROR: CSV not found at {csv_path}.")
                continue

            import_fn = get_import_function(tl.KIND, by="measure")
            success, errors = import_fn(tl, beat_tl, csv_path)
            if success:
                print(f"Successfully imported {tl_name}.")
            else:
                print(f"Failed to import {tl_name}.")

            if errors:
                print(f"Errors: {', '.join(errors)}")

    def on_get_segments_duration_button_clicked(self):
        mpb_to_tilia_module_path = MPB_TO_TILIA_PATH.resolve().__str__()
        sys.path.append(mpb_to_tilia_module_path)

        from mpb_para_tilia.tilia import get_segments_duration

        if not self.file_code:
            print("ERROR: File code not found.")
            return

        corpus_id, composition_id = self.file_code.split("-")
        try:
            duration_df = get_segments_duration(corpus_id, int(composition_id))
        except Exception as e:
            print(f"ERROR: {e}")
        else:
            print(duration_df)

        sys.path.remove(mpb_to_tilia_module_path)

    def on_report_sections_button_clicked(self):
        our_segments = post(Post.REPORT_SECTIONS)

        if not self.file_code:
            print("ERROR: File code not found.")
            return

        report_path = Path("reports", f"{self.file_code}-report.csv")
        if not report_path.exists():
            print(f"ERROR: Report not found at {report_path}.")

        unfolded_path = Path("reports", f"{self.file_code}-unfolded.csv")
        if not unfolded_path.exists():
            print(f"ERROR: Unfolded segments not found at {report_path}.")

        mpb_to_tilia_module_path = MPB_TO_TILIA_PATH.resolve().__str__()
        sys.path.append(mpb_to_tilia_module_path)

        from mpb_para_tilia.tilia import (
            generate_import_data,
            update_unfolded_segments_for_composition,
        )

        corpus_id, composition_id = self.file_code.split("-")
        try:
            update_unfolded_segments_for_composition(
                corpus_id, int(composition_id), unfolded_path
            )
            segments_dfs = generate_import_data(corpus_id, int(composition_id))
        except Exception as e:
            print(f"ERROR: {e}")
        else:
            mpb_to_tilia_segments = {
                name: df.duration.sum() for name, df in segments_dfs.items()
            }
            print(f"{'name':<10}{'ours':<8}mpb-to-tilia")
            for name, duration in our_segments:
                if name in mpb_to_tilia_segments:
                    marker = (
                        " *"
                        if float(duration) != float(mpb_to_tilia_segments[name])
                        else ""
                    )
                    print(
                        f"{name:<10}{duration:<8}{mpb_to_tilia_segments.get(name)}{marker}"
                    )
                else:
                    print(f"{name:<10}{duration:<8}NOT FOUND")

            for name, duration in mpb_to_tilia_segments.items():
                if name not in dict(our_segments):
                    print(f"{name:<10}{'NOT FOUND':<8}{duration}")

        sys.path.remove(mpb_to_tilia_module_path)
