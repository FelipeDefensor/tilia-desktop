from tilia.ui.actions import TiliaAction
from tilia.ui.menus import MenuItemKind
from tilia.ui.timelines.base.context_menus import TimelineUIElementContextMenu


class IconContextMenu(TimelineUIElementContextMenu):
    name = "Icon"
    items = [
        (MenuItemKind.ACTION, TiliaAction.TIMELINE_ELEMENT_INSPECT),
        (MenuItemKind.SEPARATOR, None),
        (MenuItemKind.ACTION, TiliaAction.TIMELINE_ELEMENT_COPY),
        (MenuItemKind.ACTION, TiliaAction.TIMELINE_ELEMENT_PASTE),
        (MenuItemKind.SEPARATOR, None),
        (MenuItemKind.ACTION, TiliaAction.TIMELINE_ELEMENT_DELETE),
    ]
