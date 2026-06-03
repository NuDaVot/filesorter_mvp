from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ParsedName:
    field: str | None
    cluster: str | None
    well: str | None


@dataclass(frozen=True)
class MapResult:
    dst_rel: Path
    reason: str = "found_existing_folder"


def _normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("ё", "е")
    text = text.replace("_", "-")
    text = text.replace(" ", "")
    return text


def parse_file_name(filename: str) -> ParsedName:
    """
    Достаёт месторождение / куст / скважину из имени файла.

    Поддерживает:
    - Местор7 куст8 скв801
    - MECT-7 KYCT-37 CKB-3704
    - Куст_15 Скв_2232
    """

    name = _normalize(filename)

    field = None
    cluster = None
    well = None

    # Местор7
    m = re.search(r"местор[-]?(\d+[а-яa-z0-9]*)", name)
    if m:
        field = m.group(1)

    # MECT-7
    m = re.search(r"mect[-]?(\d+[a-zа-я0-9]*)", name)
    if m:
        field = m.group(1)

    # куст8 / куст-15Б / куст_15
    m = re.search(r"куст[-]?(\d+[а-яa-z0-9]*)", name)
    if m:
        cluster = m.group(1)

    # KYCT-37
    m = re.search(r"kyct[-]?(\d+[a-zа-я0-9]*)", name)
    if m:
        cluster = m.group(1)

    # скв801 / скв-2232
    m = re.search(r"скв[-]?(\d+[а-яa-z0-9]*)", name)
    if m:
        well = m.group(1)

    # CKB-3704
    m = re.search(r"ckb[-]?(\d+[a-zа-я0-9]*)", name)
    if m:
        well = m.group(1)

    return ParsedName(field=field, cluster=cluster, well=well)


def _cluster_matches(folder_name: str, cluster: str) -> bool:
    """
    Проверяем папку куста.

    Пример:
    cluster = 15
    подходит:
    - Куст-15
    - Куст-15Б
    - куст-15б
    """

    folder = _normalize(folder_name)
    cluster = _normalize(cluster)

    return (
        folder == f"куст-{cluster}"
        or folder == f"куст{cluster}"
        or folder.startswith(f"куст-{cluster}")
        or folder.startswith(f"куст{cluster}")
    )


def _well_matches(folder_name: str, well: str) -> bool:
    """
    Проверяем папку скважины.

    Пример:
    well = 801
    подходит:
    - 801
    - 801В
    - 801в
    """

    folder = _normalize(folder_name)
    well = _normalize(well)

    return folder == well or folder.startswith(well)


def find_existing_target_folder(dest_root: Path, parsed: ParsedName) -> Path | None:
    """
    Ищет уже существующую папку назначения в Б.

    ВАЖНО:
    - папки НЕ создаются
    - если найдено несколько вариантов, возвращаем None,
      чтобы не положить файл не туда
    """

    if not parsed.well:
        return None

    candidates: list[Path] = []

    for path in dest_root.rglob("*"):
        if not path.is_dir():
            continue

        # Ищем папку скважины
        if not _well_matches(path.name, parsed.well):
            continue

        # Если известен куст — проверяем родительскую папку
        if parsed.cluster:
            parent = path.parent
            if not _cluster_matches(parent.name, parsed.cluster):
                continue

        candidates.append(path)

    if len(candidates) == 1:
        return candidates[0]

    # 0 вариантов — не нашли
    # больше 1 — неоднозначно
    return None


def map_destination(src_file: Path, source_root: Path, dest_root: Path) -> MapResult | None:
    """
    Главная функция.

    Возвращает путь назначения ТОЛЬКО если нужная папка уже существует в Б.
    Новые папки не создаёт.
    """

    parsed = parse_file_name(src_file.name)

    target_folder = find_existing_target_folder(dest_root, parsed)

    if target_folder is None:
        return None

    dst = target_folder / src_file.name

    return MapResult(
        dst_rel=dst.relative_to(dest_root),
        reason="found_existing_folder",
    )