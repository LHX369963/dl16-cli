from __future__ import annotations

import math
from typing import Literal

from .errors import ProtocolError

PWM_BASE_HZ = 200_000_000


def _validate_channel(channel: int) -> None:
    if not isinstance(channel, int) or not 0 <= channel <= 1:
        raise ProtocolError(f"channel must be in range 0..1, got {channel!r}")


def _validate_byteorder(byteorder: str) -> None:
    if byteorder not in {"little", "big"}:
        raise ProtocolError(f"unsupported byte order: {byteorder!r}")


def build_pwm_start_payload(
    channel: int,
    frequency_hz: int,
    duty_percent: float,
    byteorder: Literal["little", "big"] = "little",
) -> bytes:
    _validate_channel(channel)
    _validate_byteorder(byteorder)
    if not isinstance(frequency_hz, int) or not 1 <= frequency_hz <= PWM_BASE_HZ:
        raise ProtocolError(f"frequency_hz must be an integer in range 1..{PWM_BASE_HZ}, got {frequency_hz!r}")
    if not isinstance(duty_percent, (int, float)):
        raise ProtocolError(f"duty_percent must be in range 0..100, got {duty_percent!r}")
    duty = float(duty_percent)
    if not math.isfinite(duty):
        raise ProtocolError(f"duty_percent must be finite, got {duty_percent!r}")
    if not 0 <= duty <= 100:
        raise ProtocolError(f"duty_percent must be in range 0..100, got {duty_percent!r}")

    # The original binary adds 0.5 and truncates both positive results.
    period_count = math.floor(PWM_BASE_HZ / frequency_hz + 0.5)
    duty_count = math.floor(period_count * duty / 100.0 + 0.5)
    control = (channel << 4) + 0x11
    return bytes((control,)) + period_count.to_bytes(4, byteorder) + duty_count.to_bytes(4, byteorder)


def build_pwm_stop_payload(channel: int) -> bytes:
    _validate_channel(channel)
    return bytes(((channel + 1) << 4,))
