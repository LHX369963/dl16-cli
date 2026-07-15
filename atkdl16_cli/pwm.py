from __future__ import annotations

from typing import Literal

from .errors import ProtocolError

PWM_BASE_HZ = 200_000_000


def _validate_channel(channel: int) -> None:
    if not isinstance(channel, int) or not 0 <= channel <= 15:
        raise ProtocolError(f"channel must be in range 0..15, got {channel!r}")


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
    if not isinstance(duty_percent, (int, float)) or not 0 <= float(duty_percent) <= 100:
        raise ProtocolError(f"duty_percent must be in range 0..100, got {duty_percent!r}")

    period_count = int(PWM_BASE_HZ / frequency_hz)
    duty_count = int(period_count * float(duty_percent) / 100.0)
    control = (channel << 4) + 0x11
    return bytes((control,)) + period_count.to_bytes(4, byteorder) + duty_count.to_bytes(4, byteorder)


def build_pwm_stop_payload(channel: int) -> bytes:
    _validate_channel(channel)
    return bytes(((channel + 1) << 4,))
