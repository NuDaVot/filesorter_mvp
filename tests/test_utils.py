from pathlib import Path
from filesorter.core.utils import short_path, format_ts


def test_short_path_does_not_crash():
    p = Path("C:/very/long/path/" + ("x" * 400) + ".txt")
    s = short_path(p, max_len=80)
    assert isinstance(s, str)
    assert len(s) <= 80


def test_format_ts_none():
    assert format_ts(None) == "-"
