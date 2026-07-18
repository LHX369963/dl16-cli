from __future__ import annotations

import json
import mmap
from collections import Counter
from fractions import Fraction
from pathlib import Path

from .errors import ProtocolError


def _histogram_median(values: Counter) -> int | float | Fraction:
    total = values.total()
    targets = ((total - 1) // 2, total // 2)
    selected = []
    seen = 0
    target_index = 0
    for value, count in sorted(values.items()):
        while target_index < 2 and targets[target_index] < seen + count:
            selected.append(value)
            target_index += 1
        seen += count
        if target_index == 2:
            break
    return (selected[0] + selected[1]) / 2


def _scan_pwm(
    data: mmap.mmap, depth: int
) -> tuple[int, int, int, Counter[int], Counter[Fraction]]:
    ones = 0
    previous = 0
    edge_count = 0
    falling_count = 0
    previous_edge: int | None = None
    previous_prefix: int | None = None
    periods: Counter[int] = Counter()
    duties: Counter[Fraction] = Counter()
    byte_count = (depth + 7) // 8
    for byte_index in range(byte_count):
        value = data[byte_index]
        valid_bits = min(8, depth - byte_index * 8)
        mask = (1 << valid_bits) - 1
        value &= mask
        previous_bits = ((value << 1) | previous) & mask
        rising = value & ~previous_bits & mask
        falling = ~value & previous_bits & mask
        if byte_index == 0:
            rising &= ~1
            falling &= ~1
        falling_count += falling.bit_count()
        while rising:
            lowest = rising & -rising
            bit = lowest.bit_length() - 1
            edge = byte_index * 8 + bit
            prefix = ones + (value & (lowest - 1)).bit_count()
            edge_count += 1
            if previous_edge is not None and previous_prefix is not None:
                period = edge - previous_edge
                high = prefix - previous_prefix
                periods[period] += 1
                duties[Fraction(100 * high, period)] += 1
            previous_edge = edge
            previous_prefix = prefix
            rising ^= lowest
        ones += value.bit_count()
        previous = (value >> (valid_bits - 1)) & 1
    return edge_count, falling_count, ones, periods, duties


def measure_pwm_capture(capture_dir: str | Path, *, channel: int) -> dict:
    """Measure frequency and duty cycle from complete rising-edge periods."""

    root = Path(capture_dir)
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        rate = int(manifest["sample_rate_hz"])
        depth = int(manifest["sample_depth"])
        entry = manifest["channels"][str(channel)]
        path = root / entry["file"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"cannot load CH{channel} capture: {exc}") from exc
    if rate <= 0 or depth <= 0 or not 0 <= channel <= 15:
        raise ProtocolError("measurement requires a valid channel, sample rate, and sample depth")
    required = (depth + 7) // 8
    try:
        if path.stat().st_size < required:
            raise ProtocolError(f"CH{channel} capture file is too short")
        with path.open("rb") as source, mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as data:
            edge_count, falling_count, ones, periods, duties = _scan_pwm(data, depth)
    except ProtocolError:
        raise
    except OSError as exc:
        raise ProtocolError(f"cannot read CH{channel} capture: {exc}") from exc

    result = {
        "channel": channel,
        "sample_rate_hz": rate,
        "sample_depth": depth,
        "rising_edges": edge_count,
        "falling_edges": falling_count,
        "complete_periods": periods.total(),
        "frequency_hz": None,
        "duty_percent": 100.0 * ones / depth,
    }
    if periods:
        median_period = _histogram_median(periods)
        result.update({
            "frequency_hz": rate / median_period,
            "min_frequency_hz": rate / max(periods),
            "max_frequency_hz": rate / min(periods),
            "duty_percent": float(_histogram_median(duties)),
            "median_period_samples": median_period,
            "min_period_samples": min(periods),
            "max_period_samples": max(periods),
        })
    return result
