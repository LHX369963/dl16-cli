import pytest

from dl16_cli.errors import Dl16Error
from dl16_cli.sigrok import decode_with_sigrok


def test_sigrok_bridge_exports_vcd_and_builds_safe_decoder_spec(monkeypatch, tmp_path):
    calls = []

    def fake_export(capture_dir, output, *, format):
        calls.append((capture_dir, format))
        output.write_text("$timescale 1ns $end\n")

    monkeypatch.setattr("dl16_cli.sigrok.export_capture", fake_export)
    monkeypatch.setattr(
        "dl16_cli.sigrok._run",
        lambda arguments: calls.append(arguments) or "decoded\n",
    )
    assert decode_with_sigrok(
        tmp_path, decoder="uart", channels=["rx=7"],
        options=["baudrate=115200", "format=hex"],
    ) == "decoded\n"
    assert calls[0] == (tmp_path, "vcd")
    assert calls[1][4:7] == ["-P", "uart:rx=CH7:baudrate=115200:format=hex", "-A"]


@pytest.mark.parametrize("mapping", ["rx", "rx=", "rx=16", "rx=-1", "rx=x"])
def test_sigrok_bridge_rejects_invalid_channel_mapping(mapping, tmp_path):
    with pytest.raises(Dl16Error):
        decode_with_sigrok(tmp_path, decoder="uart", channels=[mapping])


def test_cli_sigrok_show_is_offline(monkeypatch, capsys):
    import dl16_cli.cli as cli

    monkeypatch.setattr(cli, "show_sigrok_decoder", lambda decoder: f"ID: {decoder}\n")
    monkeypatch.setattr(cli, "PyUsbBackend", lambda **kwargs: pytest.fail("USB opened"))
    assert cli.main(["capture", "sigrok", "--show", "can"]) == 0
    assert capsys.readouterr().out == "ID: can\n"
