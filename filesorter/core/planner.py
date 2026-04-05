from __future__ import annotations

from pathlib import Path
from typing import Iterable, List
import fnmatch
import os

from filesorter.config import AppConfig
from filesorter.core.mapper import map_destination
from filesorter.core.models import Settings, PlannedOp


def iter_matching_files(source_root: Path, patterns: List[str]) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(source_root):
        for fn in filenames:
            if patterns:
                matched = any(fnmatch.fnmatch(fn, pat) for pat in patterns)
                if not matched:
                    continue
            yield Path(dirpath) / fn


def build_plan(settings: Settings, cfg: AppConfig) -> List[PlannedOp]:
    plan: List[PlannedOp] = []
    source_root = settings.source_root
    dest_root = settings.dest_root

    for src in iter_matching_files(source_root, settings.patterns):
        try:
            src_stat = src.stat()
            src_mtime = src_stat.st_mtime
        except Exception:
            plan.append(
                PlannedOp(
                    src=src,
                    dst=dest_root / src.name,
                    action="skip",
                    reason="scan_error",
                    src_mtime=None,
                    dst_mtime=None,
                )
            )
            continue

        map_res = map_destination(src, source_root, cfg)
        dst = dest_root / map_res.dst_rel

        if dst.exists() and dst.is_file():
            try:
                dst_mtime = dst.stat().st_mtime
            except Exception:
                dst_mtime = None

            if dst_mtime is None:
                plan.append(
                    PlannedOp(
                        src=src,
                        dst=dst,
                        action="skip",
                        reason="dest_stat_error",
                        src_mtime=src_mtime,
                        dst_mtime=None,
                    )
                )
            else:
                if src_mtime > dst_mtime:
                    plan.append(
                        PlannedOp(
                            src=src,
                            dst=dst,
                            action=("move" if settings.mode == "move" else "copy"),
                            reason="replace_src_newer",
                            src_mtime=src_mtime,
                            dst_mtime=dst_mtime,
                        )
                    )
                else:
                    plan.append(
                        PlannedOp(
                            src=src,
                            dst=dst,
                            action="skip",
                            reason="skip_dest_newer_or_equal",
                            src_mtime=src_mtime,
                            dst_mtime=dst_mtime,
                        )
                    )
        else:
            plan.append(
                PlannedOp(
                    src=src,
                    dst=dst,
                    action=("move" if settings.mode == "move" else "copy"),
                    reason="new",
                    src_mtime=src_mtime,
                    dst_mtime=None,
                )
            )

    return plan
