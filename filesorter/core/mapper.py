from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import re


@dataclass(frozen=True)
class ParsedName:
    field: str | None
    cluster: str | None
    well: str | None
    file_dt: datetime | None


@dataclass(frozen=True)
class MapResult:
    dst: Path
    reason: str


def _norm(text: str) -> str:
    return (
        text.lower()
        .replace("ё", "е")
        .replace("_", "-")
        .strip()
    )


def _well_base(value: str | None) -> str | None:
    """
    CKB-2332, CKB-2332в, Скв-2332А -> 2332
    """
    if not value:
        return None

    value = _norm(value)

    m = re.search(r"(\d+)", value)
    if not m:
        return None

    return m.group(1)


def _cluster_base(value: str | None) -> str | None:
    """
    Куст-35, Куст-35Б, KYCT-35 -> 35
    """
    if not value:
        return None

    value = _norm(value)

    m = re.search(r"(\d+)", value)
    if not m:
        return None

    return m.group(1)


def extract_datetime_from_filename(filename: str) -> datetime | None:
    """
    Достаёт дату/время из имени файла.

    Поддерживает:
    - 03_02_2026 10-37
    - 03_02_2026 09-52
    - 2026_2_3 16ч50м54с
    - 2026_02_03 17-46-43
    - 10ч39м8с
    """

    name = filename

    # Формат YYYY_M_D HH-MM-SS / YYYY_M_D HHчMMмSSс
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

    # Формат DD_MM_YYYY HH-MM-SS
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


def parse_file_name(filename: str) -> ParsedName:
    name = _norm(filename)

    field = None
    cluster = None
    well = None

    m = re.search(r"(?:местор|mect)[\s_-]*(\d+[a-zа-я]?)", name)
    if m:
        field = m.group(1)

    m = re.search(r"(?:куст|kyct)[\s_-]*(\d+[a-zа-я]?)", name)
    if m:
        cluster = m.group(1)

    m = re.search(r"(?:скв|ckb)[\s_-]*(\d+[a-zа-я]?)", name)
    if m:
        well = m.group(1)

    return ParsedName(
        field=field,
        cluster=cluster,
        well=well,
        file_dt=extract_datetime_from_filename(filename),
    )

def _parse_well_folder(folder_name: str) -> tuple[str | None, bool]:
    """
    Возвращает:
    - well_base
    - is_messy

    Нормально:
    - Скв-2332
    - Скв-2332в
    - CKB-2332
    - CKB-2332в
    - 2332
    - 2332в

    Мятая скважина:
    - CKB-2332в какие-то буквы
    - Скв-2332А лишний текст
    """

    raw = _norm(folder_name)

    m = re.match(
        r"^(?:скв|ckb)?[\s_-]*(?P<num>\d+)(?P<letter>[a-zа-я])?(?P<tail>.*)$",
        raw,
        re.IGNORECASE,
    )

    if not m:
        return None, False

    number = m.group("num")
    tail = (m.group("tail") or "").strip()

    if tail:
        return number, True

    return number, False


def _cluster_matches(folder_name: str, cluster: str) -> bool:
    folder = _norm(folder_name)
    cluster_base = _cluster_base(cluster)

    if not cluster_base:
        return False

    m = re.match(r"^(?:куст|kyct)?[\s_-]*(\d+)", folder)
    if not m:
        return False

    return m.group(1) == cluster_base

def _preferred_root_names(src_name: str, parsed: ParsedName) -> list[str]:
    """
    Чтобы Журналы искались в B\\Журнал,
    а MECT/Местор — в B\\Местор4.
    """

    name = _norm(src_name)

    if name.startswith("журнал"):
        return ["журнал"]

    if parsed.field:
        field_base = _cluster_base(parsed.field)
        if field_base:
            return [f"местор{field_base}", f"местор-{field_base}"]

    return []


def find_existing_target_folder(
    dest_root: Path,
    src_name: str,
    parsed: ParsedName,
) -> tuple[Path | None, str]:
    """
    Ищет существующую папку в B.

    Если папка скважины мятая — возвращает ошибку messy_well_folder.
    """

    if not parsed.well:
        return None, "well_not_found_in_filename"

    well_base = _well_base(parsed.well)
    cluster_base = _cluster_base(parsed.cluster)

    if not well_base:
        return None, "well_not_found_in_filename"

    candidates: list[Path] = []
    messy_candidates: list[Path] = []

    preferred_roots = _preferred_root_names(src_name, parsed)

    for path in dest_root.rglob("*"):
        if not path.is_dir():
            continue

        folder_well, is_messy = _parse_well_folder(path.name)

        if folder_well != well_base:
            continue

        if is_messy:
            messy_candidates.append(path)
            continue

        if cluster_base:
            if not _cluster_matches(path.parent.name, cluster_base):
                continue

        candidates.append(path)

    if messy_candidates and not candidates:
        return None, "Мятая скважина"

    if preferred_roots:
        preferred = []

        for candidate in candidates:
            parts = [_norm(part) for part in candidate.parts]

            if any(root in parts for root in preferred_roots):
                preferred.append(candidate)

        if len(preferred) == 1:
            return preferred[0], "target_found"

        if len(preferred) > 1:
            return None, "ambiguous_target_folder"

    if len(candidates) == 1:
        return candidates[0], "target_found"

    if len(candidates) > 1:
        return None, "ambiguous_target_folder"

    return None, "target_folder_not_found"


def map_destination(src_file: Path, source_root: Path, dest_root: Path) -> MapResult:
    parsed = parse_file_name(src_file.name)

    target_folder, reason = find_existing_target_folder(
        dest_root=dest_root,
        src_name=src_file.name,
        parsed=parsed,
    )

    if target_folder is None:
        # ВАЖНО: Не обработанно создаём в A
        return MapResult(
            dst=source_root / "Не обработанно" / src_file.name,
            reason=reason,
        )

    return MapResult(
        dst=target_folder / src_file.name,
        reason=reason,
    )