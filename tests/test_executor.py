from __future__ import annotations

from pathlib import Path
import os
import time

from filesorter.config import load_config
from filesorter.core.models import Settings, PlannedOp
from filesorter.core.executor import execute_plan


def test_execute_plan_dry_run_does_not_create_files(tmp_path: Path) -> None:
    a = tmp_path / "A"
    b = tmp_path / "B"
    a.mkdir()
    b.mkdir()

    src = a / "file.irz"
    src.write_text("hello", encoding="utf-8")
    os.utime(src, times=(time.time(), time.time()))

    dst = b / "file.irz"
    op = PlannedOp(src=src, dst=dst, action="copy", reason="new", src_mtime=src.stat().st_mtime, dst_mtime=None)

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

    lines: list[str] = []
    result = execute_plan([op], settings, cfg, log=lines.append)
    assert not dst.exists()
    assert result.ok == 0
    assert any(l.startswith("DRY") for l in lines)
