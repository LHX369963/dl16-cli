import json

from atkdl16_cli.capture import SamplingParameters
from atkdl16_cli.streaming import stream_capture_to_disk


def _packet(channel, data):
    payload = bytes((channel, 0)) + data
    return b"\x0a\x01" + len(payload).to_bytes(2, "little") + payload + b"\x00\x0b"


class FakeDevice:
    def __init__(self):
        self.calls = []

    def initialize_connection(self):
        self.calls.append("initialize")

    def configure_sampling_no_response(self, params):
        self.calls.append(("sampling", params))

    def configure_simple_trigger_no_response(self, states, *, enabled, collect_type):
        self.calls.append(("trigger", states, enabled, collect_type))

    def stop_no_response(self):
        self.calls.append("stop")


class FakeBackend:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read_chunk(self, size=None):
        del size
        return self.chunks.pop(0) if self.chunks else b""


def _params():
    return SamplingParameters(1, 1_000_000, 0, 1.2, 1)


def test_stream_capture_writes_interleaved_channels_incrementally(tmp_path):
    ch6 = b"\x66" * 125 + b"\xa6" * 12
    ch7 = b"\x77" * 125 + b"\xa7" * 12
    backend = FakeBackend([
        _packet(6, ch6[:70]) + _packet(7, ch7[:80]),
        _packet(6, ch6[70:]) + _packet(7, ch7[80:]),
    ])
    device = FakeDevice()
    result = stream_capture_to_disk(
        device, backend, _params(), channels=[6, 7], output_dir=tmp_path,
        read_size=2048, sleep_fn=lambda _: None,
    )
    assert (tmp_path / "channel-06.bin").read_bytes() == b"\x66" * 125
    assert (tmp_path / "channel-07.bin").read_bytes() == b"\x77" * 125
    assert result["sample_depth"] == 1000
    assert result["storage"] == "incremental-disk"
    assert result["interrupted"] is False
    assert device.calls[0] == "initialize"
    assert device.calls[-1] == "stop"


def test_stream_capture_ctrl_c_keeps_only_common_complete_bytes(tmp_path):
    class InterruptBackend(FakeBackend):
        def read_chunk(self, size=None):
            if self.chunks:
                return super().read_chunk(size)
            raise KeyboardInterrupt

    backend = InterruptBackend([_packet(6, b"\x66" * 20) + _packet(7, b"\x77" * 18)])
    result = stream_capture_to_disk(
        FakeDevice(), backend, _params(), channels=[6, 7], output_dir=tmp_path,
        read_size=2048, sleep_fn=lambda _: None,
    )
    assert (tmp_path / "channel-06.bin").stat().st_size == 18
    assert (tmp_path / "channel-07.bin").stat().st_size == 18
    assert result["sample_depth"] == 144
    assert result["interrupted"] is True
    assert json.loads((tmp_path / "manifest.json").read_text())["sample_depth"] == 144
