from __future__ import annotations

from pathlib import Path

from filesorter.core.executor import cleanup_empty_dirs


def test_cleanup_empty_dirs_removes_nested_empty_dirs(tmp_path: Path) -> None:
    root = tmp_path / "A"
    nested = root / "x" / "y" / "z"
    nested.mkdir(parents=True, exist_ok=True)

    keep_dir = root / "keep"
    keep_dir.mkdir()
    (keep_dir / "data.txt").write_text("1", encoding="utf-8")

    logs: list[str] = []
    cleanup_empty_dirs(root, log=logs.append)

    assert (root / "x").exists() is False
    assert keep_dir.exists()
