from __future__ import annotations

from pathlib import Path
import os
import time

from filesorter.config import load_config
from filesorter.core.models import Settings
from filesorter.core.planner import build_plan


def _touch(p: Path, mtime: float) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    os.utime(p, times=(mtime, mtime))


def test_conflict_replace_if_source_newer(tmp_path: Path) -> None:
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()

    src = a / "sub" / "file.irz"
    dst = b / "sub" / "file.irz"

    now = time.time()
    _touch(dst, now - 100)
    _touch(src, now)

    cfg = load_config(tmp_path / "no-config.json")
    settings = Settings(
        source_root=a,
        dest_root=b,
        mode="copy",
        patterns=["*.irz"],
        dry_run=True,
        mapping_mode="relative",
        cleanup_empty_dirs=True,
    )

    plan = build_plan(settings, cfg)
    assert len(plan) == 1
    op = plan[0]
    assert op.action == "copy"
    assert op.reason == "replace_src_newer"


def test_conflict_skip_if_dest_newer_or_equal(tmp_path: Path) -> None:
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()

    src = a / "file.irz"
    dst = b / "file.irz"

    now = time.time()
    _touch(src, now - 100)
    _touch(dst, now)

    cfg = load_config(tmp_path / "no-config.json")
    settings = Settings(
        source_root=a,
        dest_root=b,
        mode="copy",
        patterns=["*.irz"],
        dry_run=True,
        mapping_mode="relative",
        cleanup_empty_dirs=True,
    )

    plan = build_plan(settings, cfg)
    assert len(plan) == 1
    op = plan[0]
    assert op.action == "skip"
    assert op.reason == "skip_dest_newer_or_equal"
