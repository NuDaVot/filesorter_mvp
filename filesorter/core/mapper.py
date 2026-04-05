from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict
import re

from filesorter.config import AppConfig


@dataclass(frozen=True)
class MapResult:
    """
    Результат маппинга: относительный путь назначения под dest_root.

    planner.py использует map_res.dst_rel
    """
    dst_rel: Path
    rule_name: Optional[str] = None


_ILLEGAL_WIN_CHARS = r'<>:"/\\|?*'


def _sanitize_component(value: str) -> str:
    """
    Мини-санитайзер компонента пути (особенно актуально для regex-групп).
    Удаляет символы, запрещённые в именах файлов/папок Windows.
    """
    v = value.strip()
    if not v:
        return "_"
    # заменяем запрещенные символы на '_'
    table = str.maketrans({ch: "_" for ch in _ILLEGAL_WIN_CHARS})
    v = v.translate(table)
    # Чтобы не получить компоненты вида "...." или пустые после замены
    v = v.strip(" .")
    return v or "_"


def map_destination(src_file: Path, source_root: Path, cfg: AppConfig) -> MapResult:
    """
    Возвращает ОТНОСИТЕЛЬНЫЙ путь назначения (под B) для исходного файла src_file.

    Режимы:
    - cfg.mapping.mode == "relative": сохраняем относительную структуру от source_root.
    - cfg.mapping.mode == "regex": пытаемся применить regex_rules к имени файла и
      собрать подпапки по dest_template, иначе кладем в unsorted_folder.

    ВАЖНО: функция не создает папки, не делает I/O — только строит путь.
    """

    mode = (cfg.mapping.mode or "relative").strip().lower()

    # 1) Самый надежный режим: сохраняем относительный путь от A.
    if mode != "regex":
        try:
            rel = src_file.relative_to(source_root)
        except Exception:
            # Если path не relative (редкий случай, но лучше не падать)
            rel = Path(src_file.name)
        return MapResult(dst_rel=rel, rule_name=None)

    # 2) Regex-режим: пытаемся извлечь параметры из имени файла.
    fname = src_file.name

    for rule in cfg.mapping.regex_rules:
        rx = rule.compile()
        m = rx.search(fname)
        if not m:
            continue

        raw_groups: Dict[str, str] = {
            k: v for k, v in m.groupdict().items()
            if v is not None
        }
        # Санитизация значений групп, чтобы они были пригодны как компоненты пути.
        groups = {k: _sanitize_component(v) for k, v in raw_groups.items()}

        try:
            rel_dir = Path(rule.dest_template.format(**groups))
            rel = rel_dir / fname
            return MapResult(dst_rel=rel, rule_name=rule.name)
        except Exception:
            # Если шаблон кривой (нет нужной группы и т.п.) — не валим весь прогон
            break

    # 3) Fallback: если ни одно правило не сработало
    return MapResult(dst_rel=Path(cfg.mapping.unsorted_folder) / fname, rule_name=None)
