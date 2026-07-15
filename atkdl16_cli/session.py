from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, TextIO

from .capture import SamplingParameters
from .device import AtkDevice
from .errors import AtkDl16Error
from .sampling import resolve_sample_index, validate_capture_combination
from .streaming import stream_capture_to_disk


class Dl16Session:
    """A reusable DL16 connection that avoids reset/recovery between commands."""

    def __init__(self, backend: Any, *, device: AtkDevice | Any | None = None) -> None:
        self.backend = backend
        self.device = device if device is not None else AtkDevice(backend)
        self.is_open = False

    def open(self) -> "Dl16Session":
        if not self.is_open:
            self.device.initialize_connection()
            self.is_open = True
        return self

    def close(self) -> None:
        if self.is_open:
            self.device.stop_no_response()
            self.is_open = False

    def __enter__(self) -> "Dl16Session":
        return self.open()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _require_open(self) -> None:
        if not self.is_open:
            raise AtkDl16Error("DL16 session is not open")

    def pwm_start(self, channel: int, frequency_hz: int, duty_percent: float) -> None:
        self._require_open()
        self.device.pwm_start(channel, frequency_hz, duty_percent)

    def pwm_stop(self, channel: int) -> None:
        self._require_open()
        self.device.pwm_stop(channel)

    def stream(
        self,
        *,
        channels: list[int],
        sample_rate_hz: int,
        output_dir: str | Path,
        duration_seconds: float | None = None,
        threshold: float = 1.2,
        sample_index: int | None = None,
        read_size: int = 16384,
    ) -> dict:
        self._require_open()
        validate_capture_combination(sample_rate_hz, len(channels), is_buffer=False)
        resolved_index = resolve_sample_index(sample_rate_hz, sample_index)
        if duration_seconds is None:
            set_time = ((1 << 40) - 1) // (sample_rate_hz // 1_000)
        else:
            if not math.isfinite(duration_seconds) or duration_seconds <= 0:
                raise AtkDl16Error("session stream duration_seconds must be positive and finite")
            set_time = duration_seconds * 1000.0
        params = SamplingParameters(
            set_time=set_time,
            set_hz=sample_rate_hz,
            trigger_position_percent=0,
            threshold_level=threshold,
            sample_index=resolved_index,
            collect_type=1,
        )
        return stream_capture_to_disk(
            self.device,
            self.backend,
            params,
            channels=channels,
            output_dir=output_dir,
            read_size=read_size,
            initialize=False,
        )


def _emit(output: TextIO, value: dict) -> None:
    output.write(json.dumps(value, sort_keys=True) + "\n")
    output.flush()


def run_json_session(session: Dl16Session, source: TextIO, output: TextIO) -> int:
    """Run a newline-delimited JSON command loop over one initialized USB link."""
    with session:
        _emit(output, {"ok": True, "op": "ready"})
        for line in source:
            if not line.strip():
                continue
            try:
                command = json.loads(line)
                if not isinstance(command, dict):
                    raise AtkDl16Error("session command must be a JSON object")
                op = command.get("op")
                if op == "quit":
                    _emit(output, {"ok": True, "op": op})
                    break
                if op == "pwm_start":
                    session.pwm_start(
                        int(command["channel"]),
                        int(command["frequency_hz"]),
                        float(command["duty_percent"]),
                    )
                    result: Any = None
                elif op == "pwm_stop":
                    session.pwm_stop(int(command["channel"]))
                    result = None
                elif op == "stream":
                    result = session.stream(
                        channels=[int(value) for value in command["channels"]],
                        sample_rate_hz=int(command["sample_rate_hz"]),
                        duration_seconds=(
                            float(command["duration_seconds"])
                            if command.get("duration_seconds") is not None else None
                        ),
                        threshold=float(command.get("threshold", 1.2)),
                        sample_index=(
                            int(command["sample_index"])
                            if command.get("sample_index") is not None else None
                        ),
                        read_size=int(command.get("read_size", 16384)),
                        output_dir=command["output_dir"],
                    )
                elif op == "stop":
                    session.device.stop_no_response()
                    result = None
                else:
                    raise AtkDl16Error(f"unknown session operation: {op!r}")
                _emit(output, {"ok": True, "op": op, "result": result})
            except (AtkDl16Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                _emit(output, {"ok": False, "error": str(exc)})
    return 0
