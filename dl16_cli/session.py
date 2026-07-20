from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, TextIO

from .acquisition import capture_to_disk
from .capture import SamplingParameters
from .device import Dl16Device
from .errors import Dl16Error
from .sampling import resolve_sample_index, validate_capture_combination
from .streaming import stream_capture_to_disk
from .trigger import TriggerState, parse_trigger_state


class Dl16Session:
    """A reusable DL16 connection that avoids reset/recovery between commands."""

    def __init__(self, backend: Any, *, device: Dl16Device | Any | None = None) -> None:
        self.backend = backend
        self.device = device if device is not None else Dl16Device(backend)
        self.is_open = False

    def open(self) -> "Dl16Session":
        if not self.is_open:
            self.device.initialize_connection()
            self.is_open = True
        return self

    def close(self) -> None:
        if self.is_open:
            try:
                self.device.stop_no_response()
            finally:
                self.is_open = False

    def __enter__(self) -> "Dl16Session":
        return self.open()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _require_open(self) -> None:
        if not self.is_open:
            raise Dl16Error("DL16 session is not open")

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
        overwrite: bool = False,
    ) -> dict:
        self._require_open()
        validate_capture_combination(sample_rate_hz, len(channels), is_buffer=False)
        resolved_index = resolve_sample_index(sample_rate_hz, sample_index)
        if duration_seconds is None:
            set_time = ((1 << 40) - 1) // (sample_rate_hz // 1_000)
        else:
            if not math.isfinite(duration_seconds) or duration_seconds <= 0:
                raise Dl16Error("session stream duration_seconds must be positive and finite")
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
            overwrite=overwrite,
        )

    def capture(
        self,
        *,
        channels: list[int],
        sample_rate_hz: int,
        duration_ms: float,
        output_dir: str | Path,
        buffer: bool = False,
        rle: bool = False,
        trigger: str = "none",
        trigger_channel: int | None = None,
        trigger_states: dict[int, str] | None = None,
        trigger_position_percent: float = 0,
        threshold: float = 1.2,
        sample_index: int | None = None,
        read_size: int = 16384,
        overwrite: bool = False,
        trigger_timeout_seconds: float = 30.0,
    ) -> dict:
        self._require_open()
        if rle and not buffer:
            raise Dl16Error("session capture rle requires buffer")
        if not math.isfinite(duration_ms) or duration_ms <= 0:
            raise Dl16Error("session capture duration_ms must be positive and finite")
        validate_capture_combination(sample_rate_hz, len(channels), is_buffer=buffer)
        if trigger == "none":
            trigger_state = TriggerState.NULL
        elif trigger == "either":
            trigger_state = TriggerState.DOUBLE
        else:
            trigger_state = parse_trigger_state(trigger)
        parsed_trigger_states = (
            {int(channel): parse_trigger_state(state) for channel, state in trigger_states.items()}
            if trigger_states else None
        )
        if parsed_trigger_states and (trigger_state != TriggerState.NULL or trigger_channel is not None):
            raise Dl16Error("session trigger_states cannot be combined with trigger or trigger_channel")
        if parsed_trigger_states and all(
            state == TriggerState.NULL for state in parsed_trigger_states.values()
        ):
            raise Dl16Error("session trigger_states requires at least one active condition")
        if trigger_state == TriggerState.NULL and trigger_channel is not None:
            raise Dl16Error("session trigger_channel requires rising or falling trigger")
        params = SamplingParameters(
            set_time=duration_ms,
            set_hz=sample_rate_hz,
            trigger_position_percent=trigger_position_percent,
            threshold_level=threshold,
            sample_index=resolve_sample_index(sample_rate_hz, sample_index),
            is_rle=rle,
            is_buffer=buffer,
            collect_type=1,
        )
        return capture_to_disk(
            self.device,
            self.backend,
            params,
            channels=channels,
            trigger_state=trigger_state,
            trigger_channel=trigger_channel,
            trigger_states=parsed_trigger_states,
            output_dir=output_dir,
            read_size=read_size,
            initialize=False,
            overwrite=overwrite,
            trigger_timeout_seconds=trigger_timeout_seconds,
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
                    raise Dl16Error("session command must be a JSON object")
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
                        overwrite=bool(command.get("overwrite", False)),
                    )
                elif op == "capture":
                    raw_trigger_states = command.get("trigger_states")
                    if raw_trigger_states is not None and not isinstance(raw_trigger_states, dict):
                        raise Dl16Error("session trigger_states must be a JSON object")
                    result = session.capture(
                        channels=[int(value) for value in command["channels"]],
                        sample_rate_hz=int(command["sample_rate_hz"]),
                        duration_ms=float(command["duration_ms"]),
                        output_dir=command["output_dir"],
                        buffer=bool(command.get("buffer", False)),
                        rle=bool(command.get("rle", False)),
                        trigger=str(command.get("trigger", "none")),
                        trigger_channel=(
                            int(command["trigger_channel"])
                            if command.get("trigger_channel") is not None else None
                        ),
                        trigger_states=(
                            {int(channel): str(state) for channel, state in raw_trigger_states.items()}
                            if raw_trigger_states is not None else None
                        ),
                        trigger_position_percent=float(command.get("trigger_position_percent", 0)),
                        threshold=float(command.get("threshold", 1.2)),
                        sample_index=(
                            int(command["sample_index"])
                            if command.get("sample_index") is not None else None
                        ),
                        read_size=int(command.get("read_size", 16384)),
                        overwrite=bool(command.get("overwrite", False)),
                        trigger_timeout_seconds=float(command.get("trigger_timeout_seconds", 30.0)),
                    )
                elif op == "stop":
                    session.device.stop_no_response()
                    result = None
                else:
                    raise Dl16Error(f"unknown session operation: {op!r}")
                _emit(output, {"ok": True, "op": op, "result": result})
            except (Dl16Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                _emit(output, {"ok": False, "error": str(exc)})
    return 0
