import csv
import json

import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.export import export_capture


def _capture_dir(tmp_path):
    root = tmp_path / "capture"
    root.mkdir()
    (root / "channel-06.bin").write_bytes(bytes((0b00001100,)))
    (root / "channel-07.bin").write_bytes(bytes((0b11110000,)))
    (root / "manifest.json").write_text(json.dumps({
        "sample_rate_hz": 1_000_000,
        "sample_depth": 8,
        "channels": {
            "6": {"file": "channel-06.bin", "samples": 8},
            "7": {"file": "channel-07.bin", "samples": 8},
        },
    }))
    return root


def test_csv_export_streams_every_sample_with_nanosecond_time(tmp_path):
    root = _capture_dir(tmp_path)
    output = tmp_path / "capture.csv"
    result = export_capture(root, output, format="csv")
    rows = list(csv.reader(output.open()))
    assert rows[0] == ["sample_index", "time_ns", "CH6", "CH7"]
    assert rows[1] == ["0", "0", "0", "0"]
    assert rows[3] == ["2", "2000", "1", "0"]
    assert rows[5] == ["4", "4000", "0", "1"]
    assert result.rows == 8


def test_edge_export_contains_only_transitions(tmp_path):
    root = _capture_dir(tmp_path)
    output = tmp_path / "edges.csv"
    result = export_capture(root, output, format="edges")
    rows = list(csv.reader(output.open()))
    assert rows == [
        ["sample_index", "time_ns", "channel", "level"],
        ["2", "2000", "6", "1"],
        ["4", "4000", "6", "0"],
        ["4", "4000", "7", "1"],
    ]
    assert result.rows == 3


def test_vcd_export_has_initial_values_and_grouped_changes(tmp_path):
    root = _capture_dir(tmp_path)
    output = tmp_path / "capture.vcd"
    result = export_capture(root, output, format="vcd")
    text = output.read_text()
    assert "$timescale 1ns $end" in text
    assert "$var wire 1 ! CH6 $end" in text
    assert "$var wire 1 \" CH7 $end" in text
    assert "#0\n0!\n0\"" in text
    assert "#2000\n1!" in text
    assert "#4000\n0!\n1\"" in text
    assert result.rows == 3


def test_export_rejects_truncated_channel_file(tmp_path):
    root = _capture_dir(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["sample_depth"] = 9
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ProtocolError, match="too short"):
        export_capture(root, tmp_path / "bad.csv", format="csv")


def test_cli_export_is_offline_and_reports_result(monkeypatch, tmp_path, capsys):
    import atkdl16_cli.cli as cli

    root = _capture_dir(tmp_path)
    output = tmp_path / "capture.vcd"
    monkeypatch.setattr(cli, "PyUsbBackend", lambda *args, **kwargs: pytest.fail("USB opened"))
    assert cli.main([
        "capture", "export", "--input-dir", str(root),
        "--output", str(output), "--format", "vcd",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "vcd"
    assert result["channels"] == [6, 7]
    assert result["rows"] == 3
