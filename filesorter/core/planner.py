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
            src_size = src_stat.st_size
        except Exception:
            plan.append(
                PlannedOp(
                    src=src,
                    dst=settings.dest_root / src.name,
                    action="skip",
                    reason="source_stat_error",
                    src_mtime=None,
                    dst_mtime=None,
                )
            )
            continue

        if settings.skip_zero_files and src_size < (1024 * 1024):  # src_size хранится размер файла в байтах
            plan.append(
                PlannedOp(
                    src=src,
                    dst=settings.source_root / settings.unprocessed_folder / src.name,
                    action="skip",
                    reason="zero_size_file_skipped",
                    src_mtime=src_mtime,
                    dst_mtime=None,
                )
            )
            continue
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

        map_res = map_destination(src, source_root, dest_root)

        dst = map_res.dst
        reason = map_res.reason

        if dst.exists() and dst.is_file():
            try:
                dst_mtime = dst.stat().st_mtime
                dst_ctime = dst.stat().st_ctime
                src_ctime = src.stat().st_ctime
            except Exception:
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
                continue

            if settings.delete_old_files:
                # Новый режим:
                # если файл в Б создан раньше файла из A — будем удалять старый и копировать новый
                if dst_ctime < src_ctime:
                    plan.append(
                        PlannedOp(
                            src=src,
                            dst=dst,
                            action=("move" if settings.mode == "move" else "copy"),
                            reason="delete_old_destination_then_copy",
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
                            reason="destination_file_is_newer_or_equal_by_creation_time",
                            src_mtime=src_mtime,
                            dst_mtime=dst_mtime,
                        )
                    )
            else:
                if src_mtime > dst_mtime:
                    plan.append(
                        PlannedOp(
                            src=src,
                            dst=dst,
                            action=("move" if settings.mode == "move" else "copy"),
                            reason="replace_src_newer_by_modified_time",
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
                            reason="skip_dest_newer_or_equal_by_modified_time",
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
                    reason=reason,
                    src_mtime=src_mtime,
                    dst_mtime=None,
                )
            )

    return plan
