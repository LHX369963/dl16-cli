import json

import pytest

from atkdl16_cli.measure import measure_pwm_capture


def _write_pwm(tmp_path, *, rate=1_000_000, period=100, high=25, periods=20):
    depth = period * periods
    packed = bytearray((depth + 7) // 8)
    for index in range(depth):
        if index % period < high:
            packed[index >> 3] |= 1 << (index & 7)
    (tmp_path / "channel-07.bin").write_bytes(packed)
    (tmp_path / "manifest.json").write_text(json.dumps({
        "sample_rate_hz": rate,
        "sample_depth": depth,
        "channels": {"7": {"file": "channel-07.bin", "samples": depth}},
    }))


def test_measure_pwm_uses_complete_rising_edge_periods(tmp_path):
    _write_pwm(tmp_path)
    result = measure_pwm_capture(tmp_path, channel=7)
    assert result["frequency_hz"] == 10_000
    assert result["duty_percent"] == 25
    assert result["complete_periods"] == 18
    assert result["rising_edges"] == 19
    assert result["falling_edges"] == 20
    assert result["median_period_samples"] == 100
    assert result["min_frequency_hz"] == result["max_frequency_hz"] == 10_000


def test_cli_measure_is_offline(tmp_path, monkeypatch, capsys):
    import atkdl16_cli.cli as cli

    _write_pwm(tmp_path, high=75)
    monkeypatch.setattr(cli, "PyUsbBackend", lambda **kwargs: pytest.fail("USB opened"))
    assert cli.main(["capture", "measure", "--input-dir", str(tmp_path), "--channel", "7"]) == 0
    assert json.loads(capsys.readouterr().out)["duty_percent"] == 75
