from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, List
import os
import shutil
import uuid

from filesorter.config import AppConfig
from filesorter.core.models import PlannedOp, OpResult, Settings
from filesorter.core.utils import format_ts, short_path
from filesorter.core.mapper import parse_file_name, extract_datetime_from_filename

class NetworkError(RuntimeError):
    pass


def _is_winerror(exc: BaseException, codes: List[int]) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror is None:
        return False
    return int(winerror) in set(int(c) for c in codes)


def _copy_atomic(src: Path, dst: Path, settings, log) -> None:
    if not dst.parent.exists():
        # Разрешаем создавать только папку "Не обработанно" в A
        if dst.parent.name == "Не обработанно":
            dst.parent.mkdir(parents=True, exist_ok=True)
            log(f"INFO Создана папка Не обработанно: {dst.parent}")
        else:
            raise FileNotFoundError(f"Папка назначения не найдена: {dst.parent}")

    if settings.delete_old_files:
        can_continue = _delete_older_files_in_target_folder(src, dst, settings, log)

        if not can_continue:
            raise FileExistsError("destination_has_newer_or_equal_file")

    tmp = dst.with_name(dst.name + ".tmp")

    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()


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
            _copy_atomic(op.src, op.dst, settings, log)

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

def _norm_path_text(value: str) -> str:
    return (
        str(value)
        .lower()
        .replace("ё", "е")
        .replace("/", "\\")
        .strip()
    )


def _is_delete_excluded_folder(folder: Path, settings) -> bool:
    """
    Проверяет, входит ли папка назначения в исключения.

    Поддерживает:
    - имя папки: Журнал
    - имя папки: Не обработанно
    - часть пути: Местор4\\Куст-35\\Скв-2332
    """

    excludes = getattr(settings, "delete_exclude_folders", []) or []

    if not excludes:
        return False

    folder_text = _norm_path_text(folder)

    try:
        rel_text = _norm_path_text(folder.relative_to(settings.dest_root))
    except Exception:
        rel_text = folder_text

    folder_parts = [
        _norm_path_text(part)
        for part in folder.parts
    ]

    for raw_exclude in excludes:
        exclude = _norm_path_text(raw_exclude)

        if not exclude:
            continue

        # Совпадение по имени папки
        if exclude in folder_parts:
            return True

        # Совпадение по части полного пути
        if exclude in folder_text:
            return True

        # Совпадение по части относительного пути внутри B
        if exclude in rel_text:
            return True

    return False

def _extract_datetime_from_filename(path: Path) -> datetime | None:
    """
    Достаёт дату/время из имени файла.

    Поддерживает:
    - 04_02_2026 11-37
    - 2026_2_3 14ч50м54с
    - 2026_02_03 15-46-43
    """

    name = path.name

    # Формат: YYYY_MM_DD HH-MM-SS или YYYY_M_D HHчMMмSSс
    m = re.search(
        r"(?P<y>20\d{2})[_-](?P<mo>\d{1,2})[_-](?P<d>\d{1,2})"
        r"(?:\s+(?P<h>\d{1,2})[ч:\-](?P<mi>\d{1,2})"
        r"(?:[м:\-](?P<s>\d{1,2}))?)?",
        name,
        re.IGNORECASE,
    )

    if m:
        return datetime(
            int(m.group("y")),
            int(m.group("mo")),
            int(m.group("d")),
            int(m.group("h") or 0),
            int(m.group("mi") or 0),
            int(m.group("s") or 0),
        )

    # Формат: DD_MM_YYYY HH-MM-SS
    m = re.search(
        r"(?P<d>\d{1,2})[_-](?P<mo>\d{1,2})[_-](?P<y>20\d{2})"
        r"(?:\s+(?P<h>\d{1,2})[ч:\-](?P<mi>\d{1,2})"
        r"(?:[м:\-](?P<s>\d{1,2}))?)?",
        name,
        re.IGNORECASE,
    )

    if m:
        return datetime(
            int(m.group("y")),
            int(m.group("mo")),
            int(m.group("d")),
            int(m.group("h") or 0),
            int(m.group("mi") or 0),
            int(m.group("s") or 0),
        )

    return None


def _logical_file_key(path: Path) -> tuple[str, str, str]:
    """
    Логический ключ файла.

    CKB-2332
    CKB-2332в
    CKB-2332А

    считаются одной скважиной 2332.
    """

    parsed = parse_file_name(path.name)

    cluster = ""
    well = ""

    if parsed.cluster:
        cluster = re.search(r"\d+", parsed.cluster).group(0)

    if parsed.well:
        well = re.search(r"\d+", parsed.well).group(0)

    return (
        path.suffix.lower(),
        cluster,
        well,
    )


def _delete_older_files_in_target_folder(src: Path, dst: Path, settings, log) -> bool:
    """
    Удаляет старые файлы в той же папке назначения.

    Сравнение идёт по дате из названия файла.
    """

    if not dst.parent.exists():
        return True

    # Если папка в исключениях — старые файлы НЕ удаляем
    if _is_delete_excluded_folder(dst.parent, settings):
        log(f"INFO Удаление старых файлов отключено для папки: {dst.parent}")
        return True

    src_dt = extract_datetime_from_filename(src.name)

    if src_dt is None:
        log(f"SKIP Не найдена дата в имени файла: {src.name}")
        return False

    src_key = _logical_file_key(src)

    log(f"INFO Поиск старых файлов: key={src_key}, date={src_dt}, folder={dst.parent}")

    for old_file in dst.parent.iterdir():
        if not old_file.is_file():
            continue

        old_key = _logical_file_key(old_file)

        if old_key != src_key:
            continue

        old_dt = extract_datetime_from_filename(old_file.name)

        if old_dt is None:
            log(f"INFO У старого файла нет даты в имени, пропущен: {old_file}")
            continue

        if old_dt < src_dt:
            old_file.unlink()
            log(f"DEL  Удалён старый файл по дате из имени: {old_file}")
        else:
            log(
                f"SKIP В папке уже есть такой же или более новый файл: "
                f"{old_file.name} ({old_dt}) >= {src.name} ({src_dt})"
            )
            return False

    return True