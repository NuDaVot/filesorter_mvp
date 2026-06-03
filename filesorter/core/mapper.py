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
    return (
        text.lower()
        .replace("ё", "е")
        .replace("_", "-")
        .replace(" ", "")
    )


def parse_file_name(filename: str) -> ParsedName:
    name = filename.lower().replace("ё", "е")

    field = None
    cluster = None
    well = None

    # Местор4 / Местор 4 / Местор-4
    m = re.search(r"местор[\s_-]*(\d+[а-яa-z]?)", name, re.IGNORECASE)
    if m:
        field = m.group(1)

    # MECT-4
    m = re.search(r"mect[\s_-]*(\d+[a-zа-я]?)", name, re.IGNORECASE)
    if m:
        field = m.group(1)

    # куст28 / Куст_28 / Куст-28
    m = re.search(r"куст[\s_-]*(\d+[а-яa-z]?)", name, re.IGNORECASE)
    if m:
        cluster = m.group(1)

    # KYCT-35
    m = re.search(r"kyct[\s_-]*(\d+[a-zа-я]?)", name, re.IGNORECASE)
    if m:
        cluster = m.group(1)

    # скв2198 / Скв_2203 / Скв-2332
    m = re.search(r"скв[\s_-]*(\d+[а-яa-z]?)", name, re.IGNORECASE)
    if m:
        well = m.group(1)

    # CKB-2332
    m = re.search(r"ckb[\s_-]*(\d+[a-zа-я]?)", name, re.IGNORECASE)
    if m:
        well = m.group(1)

    return ParsedName(field=field, cluster=cluster, well=well)


def _field_matches(folder_name: str, field: str | None) -> bool:
    if not field:
        return True

    folder = _normalize(folder_name)
    field = _normalize(field)

    return folder == f"местор{field}" or folder.startswith(f"местор{field}")


def _cluster_matches(folder_name: str, cluster: str | None) -> bool:
    if not cluster:
        return True

    folder = _normalize(folder_name)
    cluster = _normalize(cluster)

    return (
        folder == f"куст-{cluster}"
        or folder == f"куст{cluster}"
        or folder.startswith(f"куст-{cluster}")
        or folder.startswith(f"куст{cluster}")
    )


def _well_matches(folder_name: str, well: str) -> bool:
    folder = _normalize(folder_name)
    well = _normalize(well)

    variants = [
        well,
        f"скв-{well}",
        f"скв{well}",
    ]

    return any(folder == v or folder.startswith(v) for v in variants)


def find_existing_target_folder(dest_root: Path, parsed: ParsedName) -> Path | None:
    if not parsed.well:
        return None

    candidates: list[Path] = []

    for path in dest_root.rglob("*"):
        if not path.is_dir():
            continue

        if not _well_matches(path.name, parsed.well):
            continue

        if parsed.cluster and not _cluster_matches(path.parent.name, parsed.cluster):
            continue

        if parsed.field:
            if not any(_field_matches(parent.name, parsed.field) for parent in path.parents):
                continue

        candidates.append(path)

    if len(candidates) == 1:
        return candidates[0]

    return None


def map_destination(src_file: Path, source_root: Path, dest_root: Path) -> MapResult | None:
    parsed = parse_file_name(src_file.name)
    target_folder = find_existing_target_folder(dest_root, parsed)

    if target_folder is None:
        return None

    return MapResult(
        dst_rel=(target_folder / src_file.name).relative_to(dest_root)
    )