def format_media_time(audio_time: float | str) -> str:
    seconds_and_fraction = f"{audio_time % 60:.1f}".zfill(4)
    minutes = int(float(audio_time) // 60)
    hours = str(minutes // 60) + ":" if minutes >= 60 else ""
    minutes = str(minutes % 60).zfill(2)
    return f"{hours}{minutes}:{seconds_and_fraction}"


def format_length_in_measures(length_in_measures: tuple[int, int] | None) -> str:
    """Format a (measures, beats) interval for inspector display.

    Returns an empty string when no metric info is available so callers can
    pass HIDE_FIELD to hide the row.
    """
    if length_in_measures is None:
        return ""
    measures, beats = length_in_measures
    if beats == 0:
        return f"{measures} m."
    return f"{measures} m. {beats} b."
