from __future__ import annotations

from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from filesorter.config import load_config, with_mapping_mode
from filesorter.core.models import Settings
from filesorter.core.planner import build_plan
from filesorter.core.executor import execute_plan, cleanup_empty_dirs, NetworkError


class Worker(QObject):
    log_line = Signal(str)
    progress = Signal(int, int)
    state = Signal(str)
    finished = Signal(dict)

    def __init__(self, settings: Settings):
        super().__init__()
        self._settings = settings
        self._cancelled = False

    @Slot()
    def run(self) -> None:
        try:
            self.state.emit("scanning")
            cfg = with_mapping_mode(load_config(_find_config_path()), self._settings.mapping_mode)

            a = self._settings.source_root
            b = self._settings.dest_root

            if not a.exists() or not a.is_dir():
                raise ValueError(f"Источник A не существует или не папка: {a}")
            if not b.exists() or not b.is_dir():
                raise ValueError(f"Приёмник B не существует или не папка: {b}")

            plan = build_plan(self._settings, cfg)
            self.log_line.emit(f"INFO План построен: {len(plan)} элементов (dry_run={self._settings.dry_run}).")

            self.state.emit("running")

            def _log(s: str) -> None:
                self.log_line.emit(s)

            def _prog(done: int, total: int) -> None:
                self.progress.emit(done, total)

            result = execute_plan(plan, self._settings, cfg, log=_log, progress=_prog)

            if self._settings.mode == "move" and (not self._settings.dry_run) and self._settings.cleanup_empty_dirs:
                cleanup_empty_dirs(self._settings.source_root, log=_log)

            self.state.emit("done")
            self.finished.emit(
                {
                    "ok": result.ok,
                    "skipped": result.skipped,
                    "locked": result.locked,
                    "errors": result.errors,
                    "total": result.total(),
                }
            )
        except NetworkError as e:
            self.state.emit("error")
            self.log_line.emit(f"FATAL Ошибка сети, процесс остановлен: {e}")
            self.finished.emit({"fatal": "network_error", "message": str(e)})
        except Exception as e:
            self.state.emit("error")
            tb = traceback.format_exc(limit=15)
            self.log_line.emit(f"FATAL Необработанная ошибка: {type(e).__name__}: {e}")
            self.log_line.emit(tb)
            self.finished.emit({"fatal": "exception", "message": str(e)})

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True


def _find_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("config.json")

    cwd = Path.cwd() / "config.json"
    if cwd.exists():
        return cwd

    candidate = Path(__file__).resolve().parent.parent / "config.json"
    return candidate
