from pathlib import Path

from filesorter.config import load_config, with_mapping_mode
from filesorter.core.mapper import map_destination


def test_map_destination_relative(tmp_path: Path):
    cfg = with_mapping_mode(load_config(tmp_path / "no-config.json"), "relative")
    a = tmp_path / "A"
    f = a / "sub" / "file.irz"
    # файл можно не создавать: map_destination I/O не делает
    res = map_destination(f, a, cfg)
    assert res.dst_rel.as_posix().endswith("sub/file.irz")


def test_map_destination_regex_unsorted_when_no_match(tmp_path: Path):
    cfg = with_mapping_mode(load_config(tmp_path / "no-config.json"), "regex")
    a = tmp_path / "A"
    f = a / "file_without_tokens.irz"
    res = map_destination(f, a, cfg)
    # если нет совпадения, кладем в unsorted_folder
    assert res.dst_rel.parts[0] == cfg.mapping.unsorted_folder
