import io
import json

from dl16_cli.session import Dl16Session, run_json_session


class FakeBackend:
    def __init__(self):
        self.sent = []

    def send_frame(self, frame):
        self.sent.append(bytes(frame))
        return b"ok"

    def write_frame(self, frame):
        self.sent.append(bytes(frame))
        return len(frame)


class FakeDevice:
    def __init__(self):
        self.opens = 0
        self.stops = 0
        self.pwms = []

    def initialize_connection(self):
        self.opens += 1
        return b"DL16"

    def stop_no_response(self):
        self.stops += 1

    def pwm_start(self, channel, frequency_hz, duty_percent):
        self.pwms.append((channel, frequency_hz, duty_percent))

    def pwm_stop(self, channel):
        self.pwms.append((channel, "stop"))


def test_session_initializes_once_across_multiple_operations(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "dl16_cli.session.stream_capture_to_disk",
        lambda device, backend, params, **kwargs: calls.append((params, kwargs)) or {"sample_depth": 8},
    )
    device = FakeDevice()
    with Dl16Session(FakeBackend(), device=device) as session:
        session.pwm_start(0, 1_000_000, 75)
        result = session.stream(
            channels=[6], sample_rate_hz=1_000_000, duration_seconds=0.001,
            threshold=1.2, output_dir=tmp_path,
        )
    assert device.opens == 1
    assert device.pwms == [(0, 1_000_000, 75)]
    assert result["sample_depth"] == 8
    assert calls[0][1]["initialize"] is False
    assert device.stops == 1


def test_json_session_processes_commands_and_returns_one_json_line_each(monkeypatch):
    device = FakeDevice()
    session = Dl16Session(FakeBackend(), device=device)
    source = io.StringIO(
        '{"op":"pwm_start","channel":0,"frequency_hz":1000,"duty_percent":25}\n'
        '{"op":"pwm_stop","channel":0}\n'
        '{"op":"quit"}\n'
    )
    output = io.StringIO()
    assert run_json_session(session, source, output) == 0
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row["op"] for row in rows] == ["ready", "pwm_start", "pwm_stop", "quit"]
    assert all(row["ok"] for row in rows)
    assert device.opens == 1
    assert device.stops == 1


def test_session_capture_supports_buffer_without_reinitializing(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        "dl16_cli.session.capture_to_disk",
        lambda device, backend, params, **kwargs: calls.append((params, kwargs)) or {"mode": "buffer"},
    )
    device = FakeDevice()
    with Dl16Session(FakeBackend(), device=device) as session:
        result = session.capture(
            channels=[7, 15], sample_rate_hz=250_000_000, duration_ms=1,
            output_dir=tmp_path, buffer=True, trigger="rising", trigger_channel=7,
        )
    assert result == {"mode": "buffer"}
    assert device.opens == 1
    assert calls[0][0].is_buffer is True
    assert calls[0][1]["initialize"] is False
    assert calls[0][1]["channels"] == [7, 15]


def test_cli_session_reads_jsonl_command_file_over_one_connection(monkeypatch, tmp_path, capsys):
    import dl16_cli.cli as cli

    backend = FakeBackend()
    opens = []
    monkeypatch.setattr(cli, "PyUsbBackend", lambda vid_pid=None, timeout_ms=1000: backend)
    monkeypatch.setattr(
        cli.Dl16Device, "initialize_connection", lambda self: opens.append(True) or b"DL16"
    )
    commands = tmp_path / "commands.jsonl"
    commands.write_text('{"op":"pwm_start","channel":0,"frequency_hz":1000,"duty_percent":25}\n{"op":"quit"}\n')
    assert cli.main(["session", "--commands", str(commands)]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["op"] for row in rows] == ["ready", "pwm_start", "quit"]
    assert opens == [True]
