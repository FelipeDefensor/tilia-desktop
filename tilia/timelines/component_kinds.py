from enum import auto, Enum


class ComponentKind(Enum):
    PDF_MARKER = auto()
    MODE = auto()
    HARMONY = auto()
    BEAT = auto()
    MARKER = auto()
    HIERARCHY = auto()
    AUDIOWAVE = auto()
    ICON = auto()


def get_component_class_by_kind(kind: ComponentKind):
    from tilia.timelines.hierarchy.components import Hierarchy
    from tilia.timelines.marker.components import Marker
    from tilia.timelines.beat.components import Beat
    from tilia.timelines.harmony.components import Harmony, Mode
    from tilia.timelines.pdf.components import PdfMarker
    from tilia.timelines.audiowave.components import AmplitudeBar
    from tilia.timelines.icon.components import Icon

    kind_to_class_dict = {
        ComponentKind.HIERARCHY: Hierarchy,
        ComponentKind.MARKER: Marker,
        ComponentKind.BEAT: Beat,
        ComponentKind.HARMONY: Harmony,
        ComponentKind.MODE: Mode,
        ComponentKind.PDF_MARKER: PdfMarker,
        ComponentKind.AUDIOWAVE: AmplitudeBar,
        ComponentKind.ICON: Icon,
    }

    return kind_to_class_dict[kind]
