from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, List
import os
import shutil
import uuid

from filesorter.config import AppConfig
from filesorter.core.models import PlannedOp, OpResult, Settings
from filesorter.core.utils import format_ts, short_path


class NetworkError(RuntimeError):
    pass


def _is_winerror(exc: BaseException, codes: List[int]) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror is None:
        return False
    return int(winerror) in set(int(c) for c in codes)


def _copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + f".tmp.{uuid.uuid4().hex}")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def execute_plan(
    plan: List[PlannedOp],
    settings: Settings,
    cfg: AppConfig,
    log: Callable[[str], None],
    progress: Optional[Callable[[int, int], None]] = None,
) -> OpResult:
    res = OpResult()
    total = len(plan)
    done = 0

    for op in plan:
        done += 1
        if progress:
            progress(done, total)

        if op.action == "skip":
            res = OpResult(
                ok=res.ok,
                skipped=res.skipped + 1,
                locked=res.locked,
                errors=res.errors,
            )
            log(_format_op_line("SKIP", op))
            continue

        if settings.dry_run:
            log(_format_op_line("DRY", op))
            continue

        try:
            _copy_atomic(op.src, op.dst)

            if op.action == "move":
                try:
                    op.src.unlink()
                except Exception as e:
                    if _is_winerror(e, cfg.errors.stop_on_network_winerrors):
                        raise NetworkError(f"Network error while deleting source: {e}")
                    if _is_winerror(e, cfg.errors.locked_file_winerrors):
                        res = OpResult(res.ok, res.skipped, res.locked + 1, res.errors)
                        log(_format_error_line("LOCK", op, e))
                        continue
                    res = OpResult(res.ok, res.skipped, res.locked, res.errors + 1)
                    log(_format_error_line("ERR", op, e))
                    continue

            res = OpResult(
                ok=res.ok + 1,
                skipped=res.skipped,
                locked=res.locked,
                errors=res.errors,
            )
            log(_format_op_line("OK", op))

        except Exception as e:
            if _is_winerror(e, cfg.errors.stop_on_network_winerrors):
                log(_format_error_line("NET", op, e))
                raise NetworkError(str(e))

            if _is_winerror(e, cfg.errors.locked_file_winerrors):
                res = OpResult(res.ok, res.skipped, res.locked + 1, res.errors)
                log(_format_error_line("LOCK", op, e))
                continue

            res = OpResult(res.ok, res.skipped, res.locked, res.errors + 1)
            log(_format_error_line("ERR", op, e))

    return res


def cleanup_empty_dirs(root: Path, log: Callable[[str], None]) -> None:
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        if p == root:
            continue
        try:
            if not any(p.iterdir()):
                p.rmdir()
                log(f"CLEAN Removed empty dir: {short_path(p)}")
        except Exception:
            pass


def _format_op_line(tag: str, op: PlannedOp) -> str:
    src_ts = format_ts(op.src_mtime)
    dst_ts = format_ts(op.dst_mtime)
    return f"{tag:4} {op.action.upper():4} {short_path(op.src)} -> {short_path(op.dst)} | {op.reason} | mtime A={src_ts} B={dst_ts}"


def _format_error_line(tag: str, op: PlannedOp, exc: BaseException) -> str:
    winerror = getattr(exc, "winerror", None)
    we = f" WinError={winerror}" if winerror is not None else ""
    return f"{tag:4} {op.action.upper():4} {short_path(op.src)} -> {short_path(op.dst)} | {type(exc).__name__}: {exc}{we}"
