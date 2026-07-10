from atkdl16_cli.cli import main


def test_cli_list_dry_run_prints_supported_ids(capsys):
    rc = main(["--dry-run", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1a86:ffcc" in out
    assert "1a86:6a6b" in out
    assert "04b4:6a6a" in out


def test_cli_info_dry_run_prints_get_device_data_frame(capsys):
    rc = main(["--dry-run", "info"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "GET_DEVICE_DATA" in out
    assert "00000000000000000a1001" in out


def test_cli_pwm_start_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "pwm", "start", "--channel", "0", "--freq", "1000", "--duty", "50"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PWM_START" in out
    assert "170a11a086010050c30000" in out


def test_cli_pwm_stop_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "pwm", "stop", "--channel", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PWM_STOP" in out
    assert "170240" in out


def test_cli_stop_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "stop", "--channel", "2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "STOP" in out
    assert "150202" in out

class CliFakeBackend:
    instances = []

    def __init__(self):
        self.sent_frames = []
        self.devices = []
        CliFakeBackend.instances.append(self)

    def list_devices(self):
        return self.devices

    def send_frame(self, frame: bytes):
        self.sent_frames.append(frame)
        return b"\x99"


def test_create_backend_non_dry_run_can_be_monkeypatched(monkeypatch, capsys):
    import atkdl16_cli.cli as cli

    CliFakeBackend.instances.clear()
    monkeypatch.setattr(cli, "PyUsbBackend", lambda vid_pid=None, timeout_ms=1000: CliFakeBackend())
    rc = cli.main(["--vid-pid", "1a86:ffcc", "--timeout-ms", "250", "info"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "GET_DEVICE_DATA response: 99" in out
    assert len(CliFakeBackend.instances[0].sent_frames) == 1


def test_cli_non_dry_run_stop_uses_backend_factory(monkeypatch, capsys):
    import atkdl16_cli.cli as cli

    CliFakeBackend.instances.clear()
    monkeypatch.setattr(cli, "PyUsbBackend", lambda vid_pid=None, timeout_ms=1000: CliFakeBackend())
    rc = cli.main(["stop", "--channel", "2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "STOP response: 99" in out
    assert len(CliFakeBackend.instances[0].sent_frames) == 1


def test_cli_non_dry_run_pwm_start_uses_backend_factory(monkeypatch, capsys):
    import atkdl16_cli.cli as cli

    CliFakeBackend.instances.clear()
    monkeypatch.setattr(cli, "PyUsbBackend", lambda vid_pid=None, timeout_ms=1000: CliFakeBackend())
    rc = cli.main(["pwm", "start", "--channel", "0", "--freq", "1000", "--duty", "50"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PWM_START response: 99" in out
    assert len(CliFakeBackend.instances[0].sent_frames) == 1


def test_cli_raw_parameter_setting_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "raw", "parameter-setting", "--payload-hex", "11 22"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PARAMETER_SETTING" in out
    assert "11031122" in out


def test_cli_raw_trigger_dry_run_prints_frames(capsys):
    commands = [
        ("simple-trigger", "SIMPLE_TRIGGER", "1202aa"),
        ("stage-trigger", "STAGE_TRIGGER", "1302aa"),
        ("serial-trigger", "SERIAL_TRIGGER", "1402aa"),
    ]
    for subcommand, label, inner in commands:
        rc = main(["--dry-run", "raw", subcommand, "--payload-hex", "aa"])
        out = capsys.readouterr().out
        assert rc == 0
        assert label in out
        assert inner in out


def test_cli_raw_non_dry_run_uses_backend_factory(monkeypatch, capsys):
    import atkdl16_cli.cli as cli

    CliFakeBackend.instances.clear()
    monkeypatch.setattr(cli, "PyUsbBackend", lambda vid_pid=None, timeout_ms=1000: CliFakeBackend())
    rc = cli.main(["raw", "simple-trigger", "--payload-hex", "aa"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SIMPLE_TRIGGER response: 99" in out
    assert len(CliFakeBackend.instances[0].sent_frames) == 1


def test_cli_capture_configure_dry_run_prints_recovered_payload(capsys):
    rc = main([
        "--dry-run", "capture", "configure",
        "--set-time", "10", "--set-hz", "100000000",
        "--trigger-position", "25", "--threshold", "-1.2",
        "--sample-index", "3", "--rle", "--collect-type", "1",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PARAMETER_SETTING" in out
    assert "110e808c03" in out
    assert (1_000_000).to_bytes(5, "little").hex() in out
    assert (250_000).to_bytes(5, "little").hex() in out


def test_cli_capture_configure_non_dry_run_uses_backend(monkeypatch, capsys):
    import atkdl16_cli.cli as cli

    CliFakeBackend.instances.clear()
    monkeypatch.setattr(cli, "PyUsbBackend", lambda vid_pid=None, timeout_ms=1000: CliFakeBackend())
    rc = cli.main([
        "capture", "configure", "--set-time", "1", "--set-hz", "1000000",
        "--trigger-position", "50", "--threshold", "1.0", "--sample-index", "2",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PARAMETER_SETTING response: 99" in out
    assert len(CliFakeBackend.instances[0].sent_frames) == 1


def test_cli_trigger_simple_dry_run(capsys):
    rc = main(["--dry-run", "trigger", "simple", "--states", "rising,high", "--collect-type", "1"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SIMPLE_TRIGGER" in out
    assert "1204140000" in out


def test_cli_trigger_stage_json_dry_run(tmp_path, capsys):
    path = tmp_path / "stage.json"
    path.write_text('{"triggerLevel":2,"enabled":[true,true],"stages":[{"states":["rising","high"],"counter":4660,"contiguous":false}]}')
    rc = main(["--dry-run", "trigger", "stage", "--file", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "STAGE_TRIGGER" in out
    assert "1307010234124014" in out


def test_cli_trigger_serial_json_dry_run(tmp_path, capsys):
    path = tmp_path / "serial.json"
    path.write_text('{"valueChannel":1,"valueWidth":8,"valueData":4660,"timeChannel":2,"timeEdge":1,"channelOffset":2,"startStates":["rising","high"],"stopStates":["falling","low"]}')
    rc = main(["--dry-run", "trigger", "serial", "--file", str(path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "SERIAL_TRIGGER" in out
    assert "140b03083412040100140020" in out
