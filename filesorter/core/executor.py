from __future__ import annotations

import os
import re
import shutil
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from filesorter.core.models import OpResult, PlannedOp, Settings
from filesorter.core.utils import short_path

try:
    from filesorter.core.mapper import parse_file_name, extract_datetime_from_filename
except Exception:
    parse_file_name = None  # type: ignore
    extract_datetime_from_filename = None  # type: ignore


LogFunc = Callable[[str], None]
ProgressFunc = Callable[[int, int], None]


def _noop_log(message: str) -> None:
    pass


def _noop_progress(done: int, total: int) -> None:
    pass


def _norm(value: str) -> str:
    return (
        str(value)
        .lower()
        .replace("ё", "е")
        .replace("_", "-")
        .replace("/", "\\")
        .strip()
    )


def _reason_text(reason: str) -> str:
    mapping = {
        "target_found": "папка назначения найдена",
        "found_existing_folder": "папка назначения найдена",
        "target_folder_not_found": "подходящая папка назначения не найдена",
        "target_folder_not_found_to_unprocessed": "подходящая папка назначения не найдена, файл отправлен в Не обработанно",
        "well_not_found_in_filename": "в имени файла не найдена скважина",
        "cluster_not_found_in_filename": "в имени файла не найден куст",
        "ambiguous_target_folder": "найдено несколько подходящих папок, нельзя выбрать безопасно",
        "Мятая скважина": "мятая скважина: папка скважины названа с лишним текстом",
        "zero_size_file_skipped": "нулевой файл 0 байт",
        "destination_has_newer_or_equal_file": "в папке назначения уже есть такой же или более новый файл",
        "destination_file_is_newer_or_equal_by_creation_time": "в B файл создан позже или одновременно",
    }
    return mapping.get(str(reason or ""), str(reason or "причина не указана"))


def _extract_dt_fallback(filename: str) -> datetime | None:
    """
    Достаёт дату/время из имени файла.

    Поддерживает:
    - 03_02_2026 10-37
    - 03_02_2026 09-52
    - 2026_2_3 16ч50м54с
    - 2026_02_03 17-46-43
    - 10ч39м8с
    """
    name = str(filename)

    # YYYY_M_D HH-MM-SS / YYYY_M_D HHчMMмSSс
    m = re.search(
        r"(?P<y>20\d{2})[_\-.](?P<mo>\d{1,2})[_\-.](?P<d>\d{1,2})"
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

    # DD_MM_YYYY HH-MM-SS
    m = re.search(
        r"(?P<d>\d{1,2})[_\-.](?P<mo>\d{1,2})[_\-.](?P<y>20\d{2})"
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

    # Только время: 10ч39м8с
    m = re.search(
        r"(?P<h>\d{1,2})ч(?P<mi>\d{1,2})м(?P<s>\d{1,2})с",
        name,
        re.IGNORECASE,
    )
    if m:
        return datetime(
            1900,
            1,
            1,
            int(m.group("h")),
            int(m.group("mi")),
            int(m.group("s")),
        )

    return None


def _file_dt(path: Path) -> datetime | None:
    if extract_datetime_from_filename is not None:
        try:
            return extract_datetime_from_filename(path.name)
        except TypeError:
            try:
                return extract_datetime_from_filename(str(path.name))
            except Exception:
                pass
        except Exception:
            pass

    return _extract_dt_fallback(path.name)


def _digits(value: str | None) -> str:
    if not value:
        return ""
    m = re.search(r"\d+", str(value))
    return m.group(0) if m else ""


def _parse_key_fallback(path: Path) -> tuple[str, str, str]:
    """
    Логический ключ файла:
    (расширение, куст-цифры, скважина-цифры)

    CKB-2332, CKB-2332А, CKB-2332в считаются одной скважиной 2332.
    """
    name = _norm(path.name)

    cluster = ""
    well = ""

    m = re.search(r"(?:куст|kyct)[\s_-]*(\d+)", name, re.IGNORECASE)
    if m:
        cluster = m.group(1)

    m = re.search(r"(?:скв|ckb)[\s_-]*(\d+)", name, re.IGNORECASE)
    if m:
        well = m.group(1)

    return (path.suffix.lower(), cluster, well)


def _logical_file_key(path: Path) -> tuple[str, str, str]:
    if parse_file_name is not None:
        try:
            parsed = parse_file_name(path.name)
            return (
                path.suffix.lower(),
                _digits(getattr(parsed, "cluster", "")),
                _digits(getattr(parsed, "well", "")),
            )
        except Exception:
            pass

    return _parse_key_fallback(path)


def _norm_path_text(value: str | Path) -> str:
    return _norm(str(value))


def _is_delete_excluded_folder(folder: Path, settings: Settings) -> bool:
    excludes = getattr(settings, "delete_exclude_folders", []) or []
    if not excludes:
        return False

    folder_text = _norm_path_text(folder)

    try:
        rel_text = _norm_path_text(folder.relative_to(settings.dest_root))
    except Exception:
        rel_text = folder_text

    folder_parts = [_norm_path_text(part) for part in folder.parts]

    for raw_exclude in excludes:
        exclude = _norm_path_text(raw_exclude)
        if not exclude:
            continue

        if exclude in folder_parts:
            return True
        if exclude in folder_text:
            return True
        if exclude in rel_text:
            return True

    return False


def _delete_older_files_in_target_folder(
    src: Path,
    dst: Path,
    settings: Settings,
    log: LogFunc,
) -> bool:
    """
    Удаляет старые файлы в папке назначения по дате из имени файла.

    Возвращает:
    - True: можно продолжать копирование/перемещение
    - False: копировать нельзя, потому что уже есть такой же или более новый файл
    """
    if not dst.parent.exists():
        return True

    if _is_delete_excluded_folder(dst.parent, settings):
        log(
            "INFO Удаление старых файлов отключено для этой папки: "
            f"{short_path(dst.parent)}"
        )
        return True

    src_dt = _file_dt(src)
    if src_dt is None:
        log(
            "SKIP "
            f"{src} -> {dst} | date_not_found_in_source_name | "
            "В имени файла A не найдена дата, сравнение невозможно"
        )
        return False

    src_key = _logical_file_key(src)

    log(
        "INFO "
        f"Проверяю старые файлы в папке назначения: key={src_key}, "
        f"date={src_dt}, folder={short_path(dst.parent)}"
    )

    for old_file in sorted(dst.parent.iterdir()):
        if not old_file.is_file():
            continue

        # Не трогаем временные файлы.
        if ".tmp" in old_file.name.lower():
            continue

        old_key = _logical_file_key(old_file)
        if old_key != src_key:
            continue

        old_dt = _file_dt(old_file)

        if old_dt is None:
            log(
                "INFO "
                f"Старый файл пропущен при сравнении, потому что в имени нет даты: "
                f"{short_path(old_file)}"
            )
            continue

        if old_dt < src_dt:
            old_file.unlink()
            log(
                "DEL "
                f"{old_file} -> {dst} | old_file_deleted | "
                f"Удалён старый файл: {old_file.name} ({old_dt}) < "
                f"{src.name} ({src_dt})"
            )
        else:
            log(
                "SKIP "
                f"{src} -> {dst} | destination_has_newer_or_equal_file | "
                f"В папке уже есть такой же или более новый файл: "
                f"{old_file.name} ({old_dt}) >= {src.name} ({src_dt})"
            )
            return False

    return True


def _is_locked_error(exc: BaseException) -> bool:
    winerror = getattr(exc, "winerror", None)
    # 32: sharing violation, 33: lock violation
    return winerror in (32, 33)


def _ensure_destination_parent(dst: Path, settings: Settings, log: LogFunc) -> None:
    if dst.parent.exists():
        return

    # Разрешаем создавать только папку "Не обработанно".
    if dst.parent.name == getattr(settings, "unprocessed_folder", "Не обработанно"):
        dst.parent.mkdir(parents=True, exist_ok=True)
        log(f"INFO Создана папка Не обработанно: {dst.parent}")
        return

    raise FileNotFoundError(f"Папка назначения не найдена: {dst.parent}")


def _copy_atomic(src: Path, dst: Path, settings: Settings, log: LogFunc) -> bool:
    """
    Копирует файл.
    Возвращает True если реально скопировал, False если нужно SKIP.
    """
    _ensure_destination_parent(dst, settings, log)

    if getattr(settings, "delete_old_files", False):
        can_continue = _delete_older_files_in_target_folder(src, dst, settings, log)
        if not can_continue:
            return False

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

    return True


def _move_via_copy_delete(src: Path, dst: Path, settings: Settings, log: LogFunc) -> bool:
    copied = _copy_atomic(src, dst, settings, log)
    if not copied:
        return False

    src.unlink()
    return True


def _remove_empty_dirs(root: Path, log: LogFunc) -> None:
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir():
            continue
        try:
            if path.name == getattr(root, "name", ""):
                continue
            if not any(path.iterdir()):
                path.rmdir()
                log(f"INFO Удалена пустая папка: {short_path(path)}")
        except Exception:
            # Не критично.
            pass


def execute_plan(
    plan: Iterable[PlannedOp],
    settings: Settings,
    cfg: Any = None,
    config: Any = None,
    log: LogFunc | None = None,
    log_callback: LogFunc | None = None,
    progress: ProgressFunc | None = None,
    progress_callback: ProgressFunc | None = None,
) -> OpResult:
    """
    Выполняет план и пишет подробный лог по каждому файлу.

    Главное отличие:
    - destination_has_newer_or_equal_file теперь это SKIP, а не ERR/Traceback.
    - cfg может быть None, executor от этого не падает.
    """
    log_func = log or log_callback or _noop_log
    progress_func = progress or progress_callback or _noop_progress

    plan_list = list(plan)
    total = len(plan_list)

    ok = 0
    skipped = 0
    locked = 0
    errors = 0

    dry_run = getattr(settings, "dry_run", False)
    mode = getattr(settings, "mode", "copy")

    for index, op in enumerate(plan_list, start=1):
        src = Path(op.src)
        dst = Path(op.dst)
        action = str(op.action)
        reason = str(getattr(op, "reason", "") or "")

        progress_func(index - 1, total)

        try:
            if action == "skip":
                skipped += 1
                log_func(
                    "SKIP "
                    f"{src} -> {dst} | {reason or 'skip'} | "
                    f"{_reason_text(reason)}"
                )
                continue

            if getattr(settings, "skip_zero_files", True):
                try:
                    if src.stat().st_size == 0:
                        skipped += 1
                        log_func(
                            "SKIP "
                            f"{src} -> {dst} | zero_size_file_skipped | "
                            "Файл имеет размер 0 байт"
                        )
                        continue
                except Exception as exc:
                    skipped += 1
                    log_func(
                        "SKIP "
                        f"{src} -> {dst} | source_stat_error | "
                        f"Не удалось проверить размер файла: {exc}"
                    )
                    continue

            if dry_run:
                ok += 1
                log_func(
                    "OK "
                    f"{src} -> {dst} | dry_run | "
                    f"Тестовый режим: файл был бы {'перемещён' if action == 'move' else 'скопирован'}"
                )
                continue

            if action == "move":
                did = _move_via_copy_delete(src, dst, settings, log_func)
                if did:
                    ok += 1
                    log_func(
                        "OK "
                        f"{src} -> {dst} | moved | "
                        "Файл успешно перемещён"
                    )
                else:
                    skipped += 1
            else:
                did = _copy_atomic(src, dst, settings, log_func)
                if did:
                    ok += 1
                    log_func(
                        "OK "
                        f"{src} -> {dst} | copied | "
                        "Файл успешно скопирован"
                    )
                else:
                    skipped += 1

        except PermissionError as exc:
            if _is_locked_error(exc):
                locked += 1
                log_func(
                    "LOCKED "
                    f"{src} -> {dst} | file_locked | "
                    f"Файл занят другой программой: {exc}"
                )
            else:
                errors += 1
                log_func(
                    "ERR "
                    f"{src} -> {dst} | permission_denied | "
                    f"Нет доступа: {exc}"
                )

        except FileNotFoundError as exc:
            errors += 1
            log_func(
                "ERR "
                f"{src} -> {dst} | file_or_folder_not_found | "
                f"{exc}"
            )

        except Exception as exc:
            errors += 1
            log_func(
                "ERR "
                f"{src} -> {dst} | unexpected_error | "
                f"{type(exc).__name__}: {exc}"
            )

        finally:
            progress_func(index, total)

    if mode == "move" and getattr(settings, "cleanup_empty_dirs", True):
        try:
            _remove_empty_dirs(Path(settings.source_root), log_func)
        except Exception as exc:
            log_func(f"ERR cleanup_empty_dirs_failed | {exc}")

    return OpResult(ok=ok, skipped=skipped, locked=locked, errors=errors)
