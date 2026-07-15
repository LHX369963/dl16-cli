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
    null_nibble: int = 0x7,
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
        high_state = TriggerState(states[index])
        high = (null_nibble if high_state == TriggerState.NULL else _NIBBLE[high_state]) if enabled[index] else 0
        low = 0
        if index + 1 < len(states):
            low_state = TriggerState(states[index + 1])
            low = (null_nibble if low_state == TriggerState.NULL else _NIBBLE[low_state]) if enabled[index + 1] else 0
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
    return pack_trigger_states(
        states, enabled=enabled, channel_offset=channel_offset, null_nibble=0xF
    ) + bytes(
        (1 if collect_type == 2 else 0, 1 if collect_type == 3 else 0)
    )


from dataclasses import dataclass


@dataclass(frozen=True)
class StageCondition:
    states: Sequence[TriggerState]
    counter: int
    contiguous: bool


@dataclass(frozen=True)
class SerialTriggerConfig:
    value_channel: int
    value_width: int
    value_data: int
    time_channel: int
    time_edge: int
    start_states: Sequence[TriggerState]
    stop_states: Sequence[TriggerState]
    channel_offset: int = 0
    enabled: Sequence[bool] | None = None


def build_stage_trigger_payload(
    stages: Sequence[StageCondition],
    *,
    trigger_level: int,
    enabled: Sequence[bool] | None = None,
    channel_offset: int = 0,
) -> bytes:
    if not stages:
        raise ProtocolError("at least one trigger stage is required")
    if len(stages) > 0xFF:
        raise ProtocolError("stage count must fit in one byte")
    if not 0 <= trigger_level <= 0xFF:
        raise ProtocolError(f"trigger_level must fit in one byte, got {trigger_level}")

    output = bytearray()
    state_count: int | None = None
    for index, stage in enumerate(stages, start=1):
        if not 0 <= stage.counter <= 0xFFFF:
            raise ProtocolError(f"stage counter must fit in uint16, got {stage.counter}")
        if state_count is None:
            state_count = len(stage.states)
        elif len(stage.states) != state_count:
            raise ProtocolError("all stages must contain the same number of channel states")
        packed = pack_trigger_states(stage.states, enabled=enabled, channel_offset=channel_offset)
        output.extend((index, trigger_level))
        output.extend(stage.counter.to_bytes(2, "little"))
        output.append(0x00 if stage.contiguous else 0x40)
        output.extend(packed)
    return bytes(output)


def build_serial_trigger_payload(config: SerialTriggerConfig) -> bytes:
    for name, value in (
        ("value_channel", config.value_channel),
        ("value_width", config.value_width),
        ("time_channel", config.time_channel),
        ("time_edge", config.time_edge),
    ):
        if not isinstance(value, int) or not 0 <= value <= 0xFF:
            raise ProtocolError(f"{name} must fit in one byte, got {value!r}")
    if not 0 <= config.value_data <= 0xFFFF:
        raise ProtocolError(f"value_data must fit in uint16, got {config.value_data}")
    if config.channel_offset < 0 or config.channel_offset % 2:
        raise ProtocolError("channel_offset must be a non-negative even number")
    if config.value_channel + config.channel_offset > 0xFF:
        raise ProtocolError("value channel plus offset exceeds one byte")
    if config.time_channel + config.channel_offset > 0xFF:
        raise ProtocolError("time channel plus offset exceeds one byte")
    if len(config.start_states) != len(config.stop_states):
        raise ProtocolError("start and stop state counts must match")

    start = pack_trigger_states(
        config.start_states,
        enabled=config.enabled,
        channel_offset=config.channel_offset,
    )
    stop = pack_trigger_states(
        config.stop_states,
        enabled=config.enabled,
        channel_offset=config.channel_offset,
    )
    return (
        bytes((config.value_channel + config.channel_offset, config.value_width))
        + config.value_data.to_bytes(2, "little")
        + bytes((config.time_channel + config.channel_offset, config.time_edge))
        + start
        + stop
    )
