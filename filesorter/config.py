from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any
import json
import re


DEFAULT_CONFIG: Dict[str, Any] = {
    "ui": {
        "remember_last_paths": True
    },
    "mapping": {
        "mode": "relative",
        "unsorted_folder": "_UNSORTED",
        "regex_rules": [
            {
                "name": "MECT-KYCT-CKB latin",
                "pattern": r"MECT-(?P<field>\d+)\s+KYCT-(?P<cluster>[\wА-Яа-яЁё-]+)\s+CKB-(?P<well>[\wА-Яа-яЁё-]+)",
                "dest_template": "Местор{field}/Куст-{cluster}/Скв-{well}",
            },
            {
                "name": "Местор куст скв cyrillic",
                "pattern": r"Местор\s*(?P<field>\d+)\s+куст\s*(?P<cluster>[\wА-Яа-яЁё-]+)\s+скв\s*(?P<well>[\wА-Яа-яЁё-]+)",
                "dest_template": "Местор{field}/Куст-{cluster}/Скв-{well}",
            },
        ],
    },
    "errors": {
        "stop_on_network_winerrors": [53, 64, 67, 121, 1231, 1222],
        "locked_file_winerrors": [32, 33],
    }
}


@dataclass(frozen=True)
class MappingRule:
    name: str
    pattern: str
    dest_template: str

    def compile(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE)


@dataclass(frozen=True)
class MappingConfig:
    mode: str
    unsorted_folder: str
    regex_rules: List[MappingRule]


@dataclass(frozen=True)
class ErrorConfig:
    stop_on_network_winerrors: List[int]
    locked_file_winerrors: List[int]


@dataclass(frozen=True)
class AppConfig:
    mapping: MappingConfig
    errors: ErrorConfig


def load_config(path: Path) -> AppConfig:
    data: Dict[str, Any] = DEFAULT_CONFIG
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            data = deep_merge(DEFAULT_CONFIG, loaded)
        except Exception:
            data = DEFAULT_CONFIG

    mapping_raw = data.get("mapping", {})
    rules = [
        MappingRule(
            name=str(r.get("name", "rule")),
            pattern=str(r.get("pattern", "")),
            dest_template=str(r.get("dest_template", "")),
        )
        for r in mapping_raw.get("regex_rules", [])
        if r.get("pattern") and r.get("dest_template")
    ]
    mapping = MappingConfig(
        mode=str(mapping_raw.get("mode", "relative")).strip().lower(),
        unsorted_folder=str(mapping_raw.get("unsorted_folder", "_UNSORTED")),
        regex_rules=rules,
    )

    errors_raw = data.get("errors", {})
    errors = ErrorConfig(
        stop_on_network_winerrors=list(errors_raw.get("stop_on_network_winerrors", [])),
        locked_file_winerrors=list(errors_raw.get("locked_file_winerrors", [])),
    )
    return AppConfig(mapping=mapping, errors=errors)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def parse_patterns(raw: str) -> List[str]:
    parts = [p.strip() for p in (raw or "").split(";")]
    patterns: List[str] = []
    for p in parts:
        if not p:
            continue
        if "*" not in p and "?" not in p and "[" not in p:
            if p.startswith("."):
                patterns.append(f"*{p}")
            else:
                patterns.append(f"*.{p}")
        else:
            patterns.append(p)
    seen = set()
    res = []
    for p in patterns:
        if p.lower() in seen:
            continue
        seen.add(p.lower())
        res.append(p)
    return res


def with_mapping_mode(cfg: AppConfig, mode: str) -> AppConfig:
    mode = (mode or "").strip().lower()
    if not mode:
        return cfg
    mapping = MappingConfig(
        mode=mode,
        unsorted_folder=cfg.mapping.unsorted_folder,
        regex_rules=cfg.mapping.regex_rules,
    )
    return AppConfig(mapping=mapping, errors=cfg.errors)
