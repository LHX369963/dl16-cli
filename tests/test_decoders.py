import json

from dl16_cli.decoders import decode_i2c_capture, decode_spi_capture, decode_uart_capture


def _write_capture(tmp_path, rate, signals):
    root = tmp_path / "capture"
    root.mkdir()
    depth = len(next(iter(signals.values())))
    channels = {}
    for channel, levels in signals.items():
        packed = bytearray((depth + 7) // 8)
        for index, level in enumerate(levels):
            packed[index // 8] |= int(level) << (index % 8)
        name = f"channel-{channel:02d}.bin"
        (root / name).write_bytes(packed)
        channels[str(channel)] = {"file": name, "samples": depth}
    (root / "manifest.json").write_text(json.dumps({
        "sample_rate_hz": rate, "sample_depth": depth, "channels": channels,
    }))
    return root


def test_uart_8n1_decodes_lsb_first_byte(tmp_path):
    levels = [1] * 10 + [0] * 10
    for bit in range(8):
        levels += [((0xA5 >> bit) & 1)] * 10
    levels += [1] * 20
    root = _write_capture(tmp_path, 1_000_000, {6: levels})
    result = decode_uart_capture(root, channel=6, baud=100_000)
    assert result["protocol"] == "uart"
    assert [(frame["value"], frame["valid"]) for frame in result["frames"]] == [(0xA5, True)]


def test_i2c_decodes_address_data_and_ack(tmp_path):
    scl = [1] * 5
    sda = [1] * 5

    def hold(clock, data, count=2):
        scl.extend([clock] * count)
        sda.extend([data] * count)

    hold(1, 0)  # START
    for value, ack in ((0xA0, 0), (0x5A, 0)):
        for bit in range(7, -1, -1):
            level = (value >> bit) & 1
            hold(0, level)
            hold(1, level)
        hold(0, ack)
        hold(1, ack)
    hold(0, 0)
    hold(1, 0)
    hold(1, 1)  # STOP
    root = _write_capture(tmp_path, 1_000_000, {0: scl, 1: sda})
    result = decode_i2c_capture(root, scl_channel=0, sda_channel=1)
    tx = result["transactions"][0]
    assert tx["address"] == 0x50
    assert tx["read"] is False
    assert [(item["value"], item["ack"]) for item in tx["bytes"]] == [(0xA0, True), (0x5A, True)]


def test_spi_mode0_decodes_mosi_on_rising_edges(tmp_path):
    clock = [0] * 4
    mosi = [0] * 4
    cs = [1] * 2 + [0] * 2
    for bit in range(7, -1, -1):
        level = (0x3C >> bit) & 1
        clock += [0, 0, 1, 1]
        mosi += [level] * 4
        cs += [0] * 4
    clock += [0] * 4
    mosi += [0] * 4
    cs += [0, 0, 1, 1]
    root = _write_capture(tmp_path, 1_000_000, {2: clock, 3: mosi, 4: cs})
    result = decode_spi_capture(root, clock_channel=2, mosi_channel=3, cs_channel=4, mode=0)
    assert result["transactions"][0]["mosi"] == [0x3C]


def test_cli_uart_decode_is_offline_and_can_write_json(monkeypatch, tmp_path, capsys):
    import dl16_cli.cli as cli

    levels = [1] * 10 + [0] * 10
    for bit in range(8):
        levels += [((0x55 >> bit) & 1)] * 10
    levels += [1] * 20
    root = _write_capture(tmp_path, 1_000_000, {6: levels})
    output = tmp_path / "uart.json"
    monkeypatch.setattr(cli, "PyUsbBackend", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("USB opened")))
    assert cli.main([
        "capture", "uart", "--input-dir", str(root), "--channel", "6",
        "--baud", "100000", "--output", str(output),
    ]) == 0
    assert json.loads(output.read_text())["frames"][0]["value"] == 0x55
    assert json.loads(capsys.readouterr().out)["protocol"] == "uart"
