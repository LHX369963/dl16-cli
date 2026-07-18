import json

import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.filtering import filter_glitches


def _write_capture(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    # CH7 has a 2-sample pulse at 2..3 and a 4-sample pulse at 8..11.
    (source / "channel-07.bin").write_bytes(bytes((0b00001100, 0b00001111)))
    (source / "channel-15.bin").write_bytes(b"\xaa\x55")
    (source / "manifest.json").write_text(json.dumps({
        "sample_rate_hz": 1_000_000,
        "sample_depth": 16,
        "channels": {
            "7": {"file": "channel-07.bin", "samples": 16},
            "15": {"file": "channel-15.bin", "samples": 16},
        },
    }))
    return source


def test_glitch_filter_removes_only_bounded_pulses_at_or_below_limit(tmp_path):
    source = _write_capture(tmp_path)
    output = tmp_path / "filtered"
    result = filter_glitches(source, output, maximum_samples=2, channels=[7])
    assert (output / "channel-07.bin").read_bytes() == bytes((0, 0b00001111))
    assert (output / "channel-15.bin").read_bytes() == b"\xaa\x55"
    assert result["glitch_filter"]["removed_pulses"] == {"7": 1}
    assert json.loads((output / "manifest.json").read_text())["derived_from"] == str(source)


def test_glitch_filter_refuses_in_place_operation(tmp_path):
    source = _write_capture(tmp_path)
    with pytest.raises(ProtocolError, match="must differ"):
        filter_glitches(source, source, maximum_samples=2, overwrite=True)


def test_cli_glitch_filter_is_offline(monkeypatch, tmp_path, capsys):
    import atkdl16_cli.cli as cli

    source = _write_capture(tmp_path)
    monkeypatch.setattr(cli, "PyUsbBackend", lambda **kwargs: pytest.fail("USB opened"))
    assert cli.main([
        "capture", "filter", "--input-dir", str(source),
        "--output-dir", str(tmp_path / "cli-filtered"),
        "--max-samples", "2", "--channels", "7",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["removed_pulses"] == {"7": 1}
