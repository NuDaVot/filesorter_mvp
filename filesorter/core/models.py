from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Literal


# Режим основного действия приложения:
# - copy: копировать файл из A в B (источник остается)
# - move: переместить (в практической реализации часто copy+delete)
OperationMode = Literal["copy", "move"]

# Действие на уровне конкретного файла в плане выполнения:
# - copy/move: реально обработать
# - skip: пропустить (конфликт по дате, ошибка сканирования и т.п.)
PlanAction = Literal["copy", "move", "skip"]


@dataclass(frozen=True)
class Settings:
    """
    Settings — все параметры одного запуска.

    Совместимость:
    - ui_main.py создает Settings
    - worker.py передает Settings в planner/executor
    """
    source_root: Path
    dest_root: Path
    mode: OperationMode
    patterns: list[str]
    dry_run: bool
    mapping_mode: str  # "relative" | "regex" (переопределение поверх config.json)
    cleanup_empty_dirs: bool = True


@dataclass(frozen=True)
class PlannedOp:
    """
    PlannedOp — одна строка плана: что делать с конкретным исходным файлом.
    """
    src: Path
    dst: Path
    action: PlanAction
    reason: str
    src_mtime: Optional[float] = None
    dst_mtime: Optional[float] = None


@dataclass(frozen=True)
class OpResult:
    """
    OpResult — агрегированный итог выполнения плана.
    В executor.py результат накапливается в виде "создавать новый OpResult",
    поэтому frozen=True не мешает.
    """
    ok: int = 0
    skipped: int = 0
    locked: int = 0
    errors: int = 0

    def total(self) -> int:
        return self.ok + self.skipped + self.locked + self.errors
