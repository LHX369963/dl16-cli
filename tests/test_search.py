import json

import pytest

from dl16_cli.search import search_capture
from dl16_cli.trigger import TriggerState


def _write_capture(tmp_path):
    (tmp_path / "channel-07.bin").write_bytes(bytes((0b00001100, 0b00001111)))
    (tmp_path / "channel-15.bin").write_bytes(b"\xaa\x55")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "sample_rate_hz": 1_000_000,
        "sample_depth": 16,
        "channels": {
            "7": {"file": "channel-07.bin", "samples": 16},
            "15": {"file": "channel-15.bin", "samples": 16},
        },
    }))


def test_search_finds_edges_with_sample_and_time(tmp_path):
    _write_capture(tmp_path)
    result = search_capture(tmp_path, conditions={7: TriggerState.RISING})
    assert result["matches"] == [
        {"sample": 2, "time_ns": 2000},
        {"sample": 8, "time_ns": 8000},
    ]
    assert result["truncated"] is False


def test_search_combines_channel_conditions_and_honors_limit(tmp_path):
    _write_capture(tmp_path)
    result = search_capture(
        tmp_path,
        conditions={7: TriggerState.HIGH, 15: TriggerState.HIGH},
        limit=2,
    )
    assert [item["sample"] for item in result["matches"]] == [3, 8]
    assert result["truncated"] is True


def test_cli_search_is_offline(monkeypatch, tmp_path, capsys):
    import dl16_cli.cli as cli

    _write_capture(tmp_path)
    monkeypatch.setattr(cli, "PyUsbBackend", lambda **kwargs: pytest.fail("USB opened"))
    assert cli.main([
        "capture", "search", "--input-dir", str(tmp_path),
        "--conditions", "7=rising", "--limit", "10",
    ]) == 0
    assert [item["sample"] for item in json.loads(capsys.readouterr().out)["matches"]] == [2, 8]
