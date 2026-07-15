from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from .capture import Dl16StreamParser, SamplingParameters, decode_channel_packet
from .errors import AtkDl16Error
from .trigger import TriggerState


def stream_capture_to_disk(
    device: Any,
    backend: Any,
    params: SamplingParameters,
    *,
    channels: Sequence[int],
    output_dir: str | Path,
    read_size: int = 16384,
    sleep_fn: Callable[[float], None] = time.sleep,
    initialize: bool = True,
) -> dict:
    """Capture Stream-mode packets directly to disk, retaining partial data on Ctrl-C."""
    channels = list(channels)
    if not channels or len(set(channels)) != len(channels):
        raise AtkDl16Error("stream channels must be non-empty and unique")
    if any(channel < 0 or channel > 15 for channel in channels):
        raise AtkDl16Error("stream channels must be in range 0..15")
    if params.is_buffer or params.is_rle:
        raise AtkDl16Error("incremental stream capture cannot use Buffer or RLE")
    if read_size <= 0 or read_size % 2048:
        raise AtkDl16Error("stream read-size must be a positive multiple of 2048")

    depth = int(params.set_time * (params.set_hz // 1_000))
    expected_bytes = (depth + 7) // 8
    if expected_bytes <= 0:
        raise AtkDl16Error("stream depth must contain at least one sample")
    # Sample bytes precede a firmware-dependent completion trailer in the last
    # packet (8 bytes observed in DL16 Stream, 12 in older captures).  Stop on
    # the requested sample count and discard any same-packet suffix instead of
    # hard-coding its length.
    target_wire_bytes = expected_bytes
    destination = Path(output_dir)
    interrupted = False
    started = False
    parser = Dl16StreamParser()
    written = {channel: 0 for channel in channels}
    discarded_suffix = {channel: 0 for channel in channels}
    wire_bytes = 0

    try:
        destination.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            wire = stack.enter_context((destination / "wire.bin").open("wb"))
            files = {
                channel: stack.enter_context(
                    (destination / f"channel-{channel:02d}.bin").open("w+b")
                )
                for channel in channels
            }
            if initialize:
                device.initialize_connection()
            device.configure_sampling_no_response(params)
            sleep_fn(0.06)
            states = [TriggerState.NULL] * 16
            enabled = [channel in files for channel in range(16)]
            device.configure_simple_trigger_no_response(
                states, enabled=enabled, collect_type=params.collect_type
            )
            started = True
            try:
                while any(count < target_wire_bytes for count in written.values()):
                    chunk = backend.read_chunk(size=read_size)
                    if not chunk:
                        progress = ", ".join(
                            f"CH{channel}={count}/{target_wire_bytes}"
                            for channel, count in written.items()
                        )
                        raise AtkDl16Error(f"stream ended before requested depth ({progress})")
                    for packet in parser.feed(chunk):
                        wire.write(packet.raw)
                        wire_bytes += len(packet.raw)
                        if packet.packet_type != 1 or packet.metadata0 not in files:
                            continue
                        channel = packet.metadata0
                        block = decode_channel_packet(packet)
                        remaining = target_wire_bytes - written[channel]
                        data = block.packed_samples[:remaining]
                        files[channel].write(data)
                        written[channel] += len(data)
                        discarded_suffix[channel] += len(block.packed_samples) - len(data)
                sleep_fn(0.07)
            except KeyboardInterrupt:
                interrupted = True
            finally:
                if started:
                    device.stop_no_response()
                    started = False

            complete = all(count >= target_wire_bytes for count in written.values())
            if complete:
                retained_bytes = expected_bytes
                sample_depth = depth
            else:
                retained_bytes = min(min(written.values()), expected_bytes)
                sample_depth = retained_bytes * 8
            for handle in files.values():
                handle.truncate(retained_bytes)
                handle.flush()
    except AtkDl16Error:
        if started:
            device.stop_no_response()
        raise
    except OSError as exc:
        if started:
            device.stop_no_response()
        raise AtkDl16Error(f"cannot write stream capture to {output_dir!r}: {exc}") from exc

    manifest = {
        "bit_order": "lsb-first",
        "mode": "stream",
        "storage": "incremental-disk",
        "rle": False,
        "sample_rate_hz": params.set_hz,
        "sample_index": params.sample_index,
        "requested_sample_depth": depth,
        "sample_depth": sample_depth,
        "interrupted": interrupted,
        "transport_trailer_bytes_removed": (
            min(discarded_suffix.values()) if sample_depth == depth else 0
        ),
        "requested_channels": channels,
        "wire_bytes": wire_bytes,
        "channels": {
            str(channel): {
                "file": f"channel-{channel:02d}.bin",
                "packed_bytes": retained_bytes,
                "samples": sample_depth,
            }
            for channel in channels
        },
    }
    try:
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    except OSError as exc:
        raise AtkDl16Error(f"cannot write stream manifest: {exc}") from exc
    return manifest
