"""One-call PWM generation, capture planning, and verification."""

from __future__ import annotations

import re
import sys
import tempfile
import time
from pathlib import Path

from .acquisition import capture_to_disk
from .capture import SamplingParameters
from .device import Dl16Device
from .errors import Dl16Error
from .measure import measure_pwm_capture
from .sampling import resolve_sample_index, validate_capture_combination
from .usb import UsbBackend


def _parse_pwm_verify_spec(value: str) -> tuple[int, float]:
    try:
        frequency_text, duty_text = (part.strip() for part in value.split(",", 1))
    except ValueError as exc:
        raise Dl16Error("PWM verify values use frequency,duty") from exc
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*([kKmM]?[hH][zZ])?",
        frequency_text,
    )
    if match is None:
        raise Dl16Error(f"invalid PWM frequency {frequency_text!r}")
    scale = {None: 1.0, "hz": 1.0, "khz": 1e3, "mhz": 1e6}[match.group(2).lower() if match.group(2) else None]
    frequency = round(float(match.group(1)) * scale)
    try:
        duty = float(duty_text.removesuffix("%"))
    except ValueError as exc:
        raise Dl16Error(f"invalid PWM duty {duty_text!r}") from exc
    return min(20_000_000, max(1, frequency)), min(100.0, max(0.0, duty))


def _pwm_verify_plan(requests: list[tuple[int, int, int, float]]) -> tuple[int, float]:
    fastest = max(frequency for _, _, frequency, _ in requests)
    slowest = min(frequency for _, _, frequency, _ in requests)
    target_rate = fastest * 50
    rates = (1, 2, 4, 5, 10, 20, 40, 50, 100, 200, 250, 500)
    sample_rate = next((rate * 1_000_000 for rate in rates if rate * 1_000_000 >= target_rate), 500_000_000)
    duration_ms = max(2.0, 20_000.0 / slowest)
    return sample_rate, duration_ms


def _verify_pwm_pair(
    device: Dl16Device, backend: UsbBackend, requests: list[tuple[int, int, int, float]],
) -> list[dict]:
    device.initialize_connection()
    for pwm_channel, _, frequency, duty in requests:
        device.pwm_start(pwm_channel, frequency, duty)
    combined_rate, combined_duration = _pwm_verify_plan(requests)
    groups = (
        [requests]
        if combined_rate * combined_duration / 1000 <= 50_000_000
        else [[request] for request in requests]
    )
    measured: dict[int, dict] = {}
    with tempfile.TemporaryDirectory(prefix="dl16-pwm-") as directory:
        for index, group in enumerate(groups):
            sample_rate, duration_ms = _pwm_verify_plan(group)
            validate_capture_combination(sample_rate, len(group), is_buffer=True)
            params = SamplingParameters(
                set_time=duration_ms,
                set_hz=sample_rate,
                trigger_position_percent=0,
                threshold_level=1.2,
                sample_index=resolve_sample_index(sample_rate, None),
                is_buffer=True,
                collect_type=1,
            )
            capture_dir = Path(directory) / str(index)
            capture_to_disk(
                device,
                backend,
                params,
                channels=[input_channel for _, input_channel, _, _ in group],
                output_dir=capture_dir,
                read_size=16384,
                sleep_fn=time.sleep,
                initialize=False,
                overwrite=True,
            )
            for _, input_channel, _, _ in group:
                measured[input_channel] = measure_pwm_capture(capture_dir, channel=input_channel)
    results = [measured[input_channel] for _, input_channel, _, _ in requests]
    warnings: list[str] = []
    for (_, input_channel, expected_frequency, expected_duty), result in zip(requests, results, strict=False):
        frequency = result.get("frequency_hz")
        duty = result.get("duty_percent")
        if frequency is None:
            warnings.append(f"CH{input_channel}=no-period")
            continue
        min_frequency = float(result.get("min_frequency_hz", frequency))
        max_frequency = float(result.get("max_frequency_hz", frequency))
        min_duty = float(result.get("min_duty_percent", duty))
        max_duty = float(result.get("max_duty_percent", duty))
        if abs(float(frequency) - expected_frequency) > expected_frequency * 0.02:
            warnings.append(f"CH{input_channel}.freq={float(frequency):.6g}")
        elif max_frequency - min_frequency > float(frequency) * 0.02:
            warnings.append(f"CH{input_channel}.freq={min_frequency:.6g}..{max_frequency:.6g}")
        if abs(float(duty) - expected_duty) > 1.0:
            warnings.append(f"CH{input_channel}.duty={float(duty):.6g}")
        elif max_duty - min_duty > 2.0:
            warnings.append(f"CH{input_channel}.duty={min_duty:.6g}..{max_duty:.6g}")
    if warnings:
        print("warning: " + " ".join(warnings), file=sys.stderr)
    return results


