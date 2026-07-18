from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path

from .capture import Dl16StreamParser, SamplingParameters, decode_channel_packet
from .errors import AtkDl16Error
from .storage import prepare_capture_directory
from .trigger import TriggerState
from .usb import UsbBackend


def _trigger_name(state: TriggerState) -> str:
    return "either" if state == TriggerState.DOUBLE else state.name.lower()


def capture_to_disk(
    device,
    backend: UsbBackend,
    params: SamplingParameters,
    *,
    channels: Sequence[int],
    trigger_state: TriggerState = TriggerState.NULL,
    trigger_channel: int | None = None,
    trigger_states: dict[int, TriggerState] | None = None,
    output_dir: str | Path,
    read_size: int = 16384,
    sleep_fn: Callable[[float], None] = time.sleep,
    initialize: bool = True,
    overwrite: bool = False,
    trigger_timeout_seconds: float = 30.0,
) -> dict:
    """Run a finite Stream/Buffer capture and write decoded channels to disk."""

    channels = list(channels)
    if not channels:
        raise AtkDl16Error("at least one capture channel is required")
    if len(set(channels)) != len(channels):
        raise AtkDl16Error("duplicate channel in capture channel list")
    if any(not 0 <= channel <= 15 for channel in channels):
        raise AtkDl16Error("capture channels must be in range 0..15")
    if trigger_states and trigger_state != TriggerState.NULL:
        raise AtkDl16Error("use either trigger_state or trigger_states, not both")
    if trigger_states:
        invalid = [channel for channel in trigger_states if channel not in channels]
        if invalid:
            raise AtkDl16Error(f"trigger channel {invalid[0]} must be one of the captured channels")
    elif trigger_state != TriggerState.NULL:
        trigger_channel = channels[0] if trigger_channel is None else trigger_channel
        if trigger_channel not in channels:
            raise AtkDl16Error("trigger channel must be one of the captured channels")
    if read_size <= 0 or read_size % 2048:
        raise AtkDl16Error("capture read-size must be a positive multiple of 2048")
    if not math.isfinite(trigger_timeout_seconds) or trigger_timeout_seconds <= 0:
        raise AtkDl16Error("trigger timeout must be positive and finite")

    depth = int(params.set_time * (params.set_hz // 1_000))
    expected_bytes = (depth + 7) // 8
    if expected_bytes == 0:
        raise AtkDl16Error("capture depth must contain at least one sample")

    destination = prepare_capture_directory(output_dir, overwrite=overwrite)
    stack = ExitStack()
    try:
        wire_stream = stack.enter_context((destination / "wire.bin").open("wb"))
        channel_streams = {
            channel: stack.enter_context(
                (destination / f"channel-{channel:02d}.bin").open("w+b")
            )
            for channel in channels
        }
    except OSError as exc:
        stack.close()
        raise AtkDl16Error(f"cannot create capture output {str(output_dir)!r}: {exc}") from exc

    states = [TriggerState.NULL] * 16
    if trigger_states:
        for channel, state in trigger_states.items():
            states[channel] = TriggerState(state)
    elif trigger_state != TriggerState.NULL:
        assert trigger_channel is not None
        states[trigger_channel] = trigger_state
    enabled = [channel in channels for channel in range(16)]
    parser = Dl16StreamParser()
    written = {channel: 0 for channel in channels}
    trailer_bytes = 1 if params.is_rle else 12
    target_wire_bytes = expected_bytes + trailer_bytes
    capture_started = False
    sample_started = False
    hardware_complete = False
    has_trigger = bool(trigger_states) or trigger_state != TriggerState.NULL
    trigger_deadline = time.monotonic() + trigger_timeout_seconds if has_trigger else None
    try:
        if initialize:
            device.initialize_connection()
        capture_started = True
        device.configure_sampling_no_response(params)
        sleep_fn(0.06)
        device.configure_simple_trigger_no_response(
            states, enabled=enabled, collect_type=params.collect_type
        )
        while any(count < target_wire_bytes for count in written.values()):
            if trigger_deadline is not None and not sample_started and time.monotonic() >= trigger_deadline:
                raise AtkDl16Error(
                    f"trigger was not satisfied within {trigger_timeout_seconds:g} seconds"
                )
            chunk = backend.read_chunk(size=read_size)
            if not chunk:
                progress = ", ".join(
                    f"CH{channel}={count}/{target_wire_bytes}" for channel, count in written.items()
                )
                raise AtkDl16Error(f"capture stream ended before all channels completed ({progress})")
            for packet in parser.feed(chunk):
                wire_stream.write(packet.raw)
                if (
                    packet.packet_type == 1
                    and packet.metadata0 in written
                    and written[packet.metadata0] < target_wire_bytes
                ):
                    block = decode_channel_packet(packet, is_rle=params.is_rle)
                    channel = packet.metadata0
                    remaining = target_wire_bytes - written[channel]
                    data = block.packed_samples[:remaining]
                    channel_streams[channel].write(data)
                    written[channel] += len(data)
                    sample_started = True
                elif params.is_rle and sample_started and packet.packet_type == 6:
                    hardware_complete = True
            if hardware_complete:
                break
        sleep_fn(0.07)
    except AtkDl16Error:
        raise
    except OSError as exc:
        raise AtkDl16Error(f"cannot write capture output {str(output_dir)!r}: {exc}") from exc
    finally:
        stack.close()
        if capture_started:
            device.stop_no_response()

    retained: dict[int, int] = {}
    for channel, count in written.items():
        if count >= target_wire_bytes:
            retained[channel] = expected_bytes
        elif params.is_rle and hardware_complete and count > trailer_bytes:
            retained[channel] = count - trailer_bytes
        else:
            retained[channel] = min(count, expected_bytes)
    for channel, count in retained.items():
        if count != expected_bytes and not (params.is_rle and hardware_complete and count):
            raise AtkDl16Error(
                f"CH{channel} returned {count} of {expected_bytes} expected packed sample bytes"
            )
    actual_depth = min(min(count * 8, depth) for count in retained.values())
    shortened = actual_depth < depth
    trigger_manifest = {
        "edge": "none" if trigger_state == TriggerState.NULL else _trigger_name(trigger_state),
        "channel": trigger_channel,
        "position_percent": params.trigger_position_percent,
    }
    if trigger_states:
        trigger_manifest.update({
            "edge": "multiple",
            "channel": None,
            "conditions": {
                str(channel): _trigger_name(TriggerState(state))
                for channel, state in sorted(trigger_states.items())
            },
        })
    manifest = {
        "bit_order": "lsb-first",
        "mode": "buffer" if params.is_buffer else "stream",
        "storage": "incremental-disk",
        "rle": params.is_rle,
        "sample_rate_hz": params.set_hz,
        "sample_index": params.sample_index,
        "requested_sample_depth": depth,
        "sample_depth": actual_depth,
        "capture_shortened_by_hardware": shortened,
        "transport_trailer_bytes_removed": trailer_bytes,
        "requested_channels": channels,
        "trigger": trigger_manifest,
        "channels": {
            str(channel): {
                "file": f"channel-{channel:02d}.bin",
                "packed_bytes": retained[channel],
                "samples": min(retained[channel] * 8, depth),
            }
            for channel in channels
        },
    }
    try:
        for channel, count in retained.items():
            with (destination / f"channel-{channel:02d}.bin").open("r+b") as stream:
                stream.truncate(count)
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    except OSError as exc:
        raise AtkDl16Error(f"cannot write capture output {str(output_dir)!r}: {exc}") from exc
    return manifest
