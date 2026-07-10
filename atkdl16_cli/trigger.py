from __future__ import annotations

from enum import IntEnum
from typing import Sequence

from .errors import ProtocolError


class TriggerState(IntEnum):
    NULL = 0
    RISING = 1
    HIGH = 2
    FALLING = 3
    LOW = 4
    DOUBLE = 5


_NIBBLE = {
    TriggerState.NULL: 0x7,
    TriggerState.RISING: 0x1,
    TriggerState.HIGH: 0x4,
    TriggerState.FALLING: 0x2,
    TriggerState.LOW: 0x0,
    TriggerState.DOUBLE: 0x3,
}

_NAME_MAP = {
    "null": TriggerState.NULL,
    "x": TriggerState.NULL,
    "dont-care": TriggerState.NULL,
    "don't-care": TriggerState.NULL,
    "rising": TriggerState.RISING,
    "r": TriggerState.RISING,
    "high": TriggerState.HIGH,
    "1": TriggerState.HIGH,
    "falling": TriggerState.FALLING,
    "f": TriggerState.FALLING,
    "low": TriggerState.LOW,
    "0": TriggerState.LOW,
    "double": TriggerState.DOUBLE,
    "c": TriggerState.DOUBLE,
}


def parse_trigger_states(text: str) -> list[TriggerState]:
    if not text.strip():
        raise ProtocolError("trigger state list cannot be empty")
    result: list[TriggerState] = []
    for raw in text.split(","):
        name = raw.strip().lower()
        if name not in _NAME_MAP:
            raise ProtocolError(f"unknown trigger state: {raw!r}")
        result.append(_NAME_MAP[name])
    return result


def pack_trigger_states(
    states: Sequence[TriggerState],
    *,
    enabled: Sequence[bool] | None = None,
    channel_offset: int = 0,
) -> bytes:
    if channel_offset < 0 or channel_offset % 2:
        raise ProtocolError(f"channel_offset must be a non-negative even number, got {channel_offset}")
    if enabled is None:
        enabled = [True] * len(states)
    if len(enabled) != len(states):
        raise ProtocolError("enabled mask length must match trigger state count")
    if not states:
        raise ProtocolError("at least one trigger state is required")

    output = bytearray(channel_offset // 2)
    for index in range(0, len(states), 2):
        high = _NIBBLE[TriggerState(states[index])] if enabled[index] else 0
        low = 0
        if index + 1 < len(states):
            low = _NIBBLE[TriggerState(states[index + 1])] if enabled[index + 1] else 0
        output.append((high << 4) | low)
    return bytes(output)


def build_simple_trigger_payload(
    states: Sequence[TriggerState],
    *,
    enabled: Sequence[bool] | None = None,
    collect_type: int = 1,
    channel_offset: int = 0,
) -> bytes:
    if not 0 <= collect_type <= 0xFF:
        raise ProtocolError(f"collect_type must fit in one byte, got {collect_type}")
    return pack_trigger_states(states, enabled=enabled, channel_offset=channel_offset) + bytes(
        (1 if collect_type == 2 else 0, 1 if collect_type == 3 else 0)
    )
