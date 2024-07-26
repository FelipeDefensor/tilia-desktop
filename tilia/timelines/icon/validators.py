from tilia.timelines.icon.enums import Alignment


def validate_alignment(alignment: str) -> bool:
    return alignment in Alignment
