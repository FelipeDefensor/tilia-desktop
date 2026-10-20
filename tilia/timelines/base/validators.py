import math
from typing import Any

from PySide6.QtGui import QColor


def validate_time(value):
    return isinstance(value, (float, int)) and value >= 0


def validate_string(value):
    return isinstance(value, str)


def validate_bool(value):
    return isinstance(value, bool)


def validate_color(value):
    if value is None or value == "":
        # None or "" mean the default color.
        # 0 is a valid value for QColor,
        # so we can't simply use `if not value`.
        return True

    try:
        return QColor(value).isValid()
    except TypeError:
        return False


def validate_read_only(_):
    return False


def validate_boolean(value):
    return isinstance(value, bool)


def validate_integer(value):
    return isinstance(value, int)


def validate_non_negative_integer(value):
    return isinstance(value, int) and value >= 0


def validate_positive_integer(value):
    return isinstance(value, int) and value > 0


def validate_bounded_integer(value: int, lower=-math.inf, upper=math.inf):
    return isinstance(value, int) and lower <= value <= upper


def validate_normalized_rect(value) -> bool:
    """
    Accepts None (no rect) or [x, y, width, height] with positive size and the
    rect fully inside the unit square.
    """
    if value is None:
        return True
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return False
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return False
    x, y, w, h = value
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= 1 and y + h <= 1


def validate_pre_validated(_):
    return True


def validate_is_instance(cls: type, value: Any) -> bool:
    return isinstance(value, cls)
