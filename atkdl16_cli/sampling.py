from __future__ import annotations

from .errors import ProtocolError


# Recovered from the DL16 setting index and verified against looped-back PWM.
# Index 6 was independently confirmed at 20 MHz. Index 7 repeatedly produces
# no sample packets on the connected DL16, so it is intentionally excluded
# rather than borrowing a rate from another model/firmware.
SAMPLE_RATE_TO_INDEX: dict[int, int] = {
    500_000_000: 0,
    1_000_000: 1,
    2_000_000: 2,
    4_000_000: 3,
    5_000_000: 4,
    10_000_000: 5,
    20_000_000: 6,
    40_000_000: 8,
    50_000_000: 9,
    100_000_000: 10,
    200_000_000: 11,
    250_000_000: 12,
}


def resolve_sample_index(sample_rate_hz: int, requested_index: int | None = None) -> int:
    try:
        recovered_index = SAMPLE_RATE_TO_INDEX[sample_rate_hz]
    except KeyError as exc:
        supported = ", ".join(str(rate) for rate in sorted(SAMPLE_RATE_TO_INDEX))
        raise ProtocolError(
            f"unsupported sample rate {sample_rate_hz} Hz; supported rates: {supported}"
        ) from exc
    if requested_index is not None and requested_index != recovered_index:
        raise ProtocolError(
            f"sample index {requested_index} does not match {sample_rate_hz} Hz; "
            f"expected index {recovered_index}"
        )
    return recovered_index


def validate_capture_combination(sample_rate_hz: int, channel_count: int, *, is_buffer: bool) -> None:
    resolve_sample_index(sample_rate_hz)
    if not isinstance(channel_count, int) or not 1 <= channel_count <= 16:
        raise ProtocolError(f"channel count must be in range 1..16, got {channel_count!r}")
    if is_buffer:
        return
    if sample_rate_hz > 100_000_000:
        raise ProtocolError("DL16 Stream mode supports at most 100000000 Hz")
    if sample_rate_hz <= 20_000_000:
        maximum = 16
    elif sample_rate_hz <= 50_000_000:
        maximum = 6
    else:
        maximum = 3
    if channel_count > maximum:
        raise ProtocolError(
            f"DL16 Stream mode at {sample_rate_hz} Hz supports at most {maximum} channels; "
            f"got {channel_count}"
        )
