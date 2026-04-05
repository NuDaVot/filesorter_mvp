from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional


def format_ts(ts: Optional[float]) -> str:
    """
    Преобразует timestamp (mtime из stat().st_mtime) в строку для логов.

    Если ts None — возвращает '-'.
    """
    if ts is None:
        return "-"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # На случай экзотических значений — не падаем, а выводим как есть
        return str(ts)


def short_path(p: Path, max_len: int = 120) -> str:
    """
    Сокращает длинные пути для читаемого лога:
    'C:\\very\\long\\...\\file.ext' => 'C:\\very\\long ... \\file.ext'

    max_len — целевая максимальная длина строки.
    """
    s = str(p)
    if len(s) <= max_len:
        return s

    # Простейшее усечение: берем начало и конец.
    head = 40
    tail = max(10, max_len - head - 5)  # 5 на " … "
    return s[:head] + " … " + s[-tail:]
