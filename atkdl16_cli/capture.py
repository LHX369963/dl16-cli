from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import ProtocolError

_MAX_U40 = (1 << 40) - 1
_DL16_START = 0x0A
_DL16_TRAILER = b"\x00\x0b"
_DL16_PACKET_TYPES = frozenset(range(1, 7))


@dataclass(frozen=True)
class Dl16CapturePacket:
    """One losslessly decoded packet returned by the DL16 Analysis parser."""

    packet_type: int
    payload: bytes
    raw: bytes

    @property
    def metadata0(self) -> int | None:
        return self.payload[0] if self.payload else None

    @property
    def metadata1(self) -> int | None:
        return self.payload[1] if len(self.payload) >= 2 else None

    @property
    def body(self) -> bytes:
        return self.payload[2:]


class Dl16StreamParser:
    """Incrementally split arbitrary USB chunks using the recovered DL16 framing."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes | bytearray | memoryview) -> list[Dl16CapturePacket]:
        self._buffer.extend(data)
        packets: list[Dl16CapturePacket] = []
        while True:
            marker = self._buffer.find(_DL16_START)
            if marker < 0:
                self._buffer.clear()
                break
            if marker:
                del self._buffer[:marker]
            if len(self._buffer) < 4:
                break
            packet_type = self._buffer[1]
            if packet_type not in _DL16_PACKET_TYPES:
                del self._buffer[0]
                continue
            payload_length = int.from_bytes(self._buffer[2:4], "little")
            total_length = payload_length + 6
            if len(self._buffer) < total_length:
                break
            if self._buffer[4 + payload_length : total_length] != _DL16_TRAILER:
                del self._buffer[0]
                continue
            raw = bytes(self._buffer[:total_length])
            payload = raw[4 : 4 + payload_length]
            packets.append(Dl16CapturePacket(packet_type=packet_type, payload=payload, raw=raw))
            del self._buffer[:total_length]
        return packets


@dataclass(frozen=True)
class SamplingParameters:
    set_time: float
    set_hz: int
    trigger_position_percent: float
    threshold_level: float
    sample_index: int
    is_rle: bool = False
    is_buffer: bool = False
    collect_type: int = 1


def _threshold_byte(level: float) -> int:
    if not math.isfinite(level) or abs(level) > 12.7:
        raise ProtocolError(f"threshold_level must be finite and within -12.7..12.7 V, got {level!r}")
    magnitude = math.floor(abs(level * 10.0) + 0.5)
    return magnitude + (0x80 if level < 0 else 0)


def build_parameter_setting_payload(params: SamplingParameters) -> bytes:
    if not math.isfinite(params.set_time) or params.set_time < 0:
        raise ProtocolError(f"set_time must be finite and non-negative, got {params.set_time!r}")
    if not isinstance(params.set_hz, int) or params.set_hz < 1_000:
        raise ProtocolError(f"set_hz must be an integer >= 1000, got {params.set_hz!r}")
    if not math.isfinite(params.trigger_position_percent) or not 0 <= params.trigger_position_percent <= 100:
        raise ProtocolError(
            f"trigger_position_percent must be within 0..100, got {params.trigger_position_percent!r}"
        )
    if not isinstance(params.sample_index, int) or not 0 <= params.sample_index <= 0xFF:
        raise ProtocolError(f"sample_index must be within 0..255, got {params.sample_index!r}")
    if params.collect_type == 3 and (params.is_rle or params.is_buffer):
        raise ProtocolError("stream collect type 3 cannot be combined with RLE or Buffer")

    flags = (0x80 if params.is_rle else 0) + (0x40 if params.is_buffer else 0)
    frequency_khz = int(params.set_hz) // 1_000
    depth = int(params.set_time * frequency_khz)
    trigger_sample = int((depth // 100) * params.trigger_position_percent)
    if not 0 <= depth <= _MAX_U40:
        raise ProtocolError(f"computed sample depth exceeds unsigned 40-bit range: {depth}")
    if not 0 <= trigger_sample <= _MAX_U40:
        raise ProtocolError(f"computed trigger sample exceeds unsigned 40-bit range: {trigger_sample}")

    return (
        bytes((flags, _threshold_byte(params.threshold_level), params.sample_index))
        + depth.to_bytes(5, "little")
        + trigger_sample.to_bytes(5, "little")
    )
