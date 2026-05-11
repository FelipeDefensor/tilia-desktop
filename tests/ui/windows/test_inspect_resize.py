"""Regression test for the inspector dock resizing when its content
changes (commit a1ef4cc5 flipped the right_widget's horizontal policy
to `Expanding`, which made the dock grow to fit the longest label —
visually jarring every time you clicked a different hierarchy).

The fix kept `setMinimumWidth(100)` but reverted the policy back to
`Ignored`, so the dock width stays fixed regardless of the field's
text length.
"""

from PySide6.QtWidgets import QSizePolicy

from tilia.requests import Post, post
from tilia.ui import commands
from tilia.ui.windows.kinds import WindowKind


def _open_inspector_for(tlui, element, qtui):
    tlui.select_element(element)
    commands.execute("timeline.element.inspect")
    return qtui._windows[WindowKind.INSPECT]


class TestInspectorDockWidth:
    def test_right_widget_does_not_expand_horizontally(self, qtui, hierarchy_tlui):
        # If the horizontal policy expands, a long label/comment can
        # widen the dock as the user clicks through hierarchies — the
        # exact regression a1ef4cc5 introduced.
        hierarchy_tlui.create_hierarchy(0, 1, 1)
        element = hierarchy_tlui[0]

        inspector = _open_inspector_for(hierarchy_tlui, element, qtui)

        try:
            for _name, (_label, value) in inspector.field_name_to_widgets.items():
                horizontal = value.sizePolicy().horizontalPolicy()
                assert (
                    horizontal == QSizePolicy.Policy.Ignored
                ), f"{_name!r}: expected Ignored, got {horizontal}"
        finally:
            post(Post.WINDOW_CLOSE, WindowKind.INSPECT)
