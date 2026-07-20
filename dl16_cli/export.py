from __future__ import annotations

import csv
import heapq
import json
import mmap
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, TextIO

from .errors import ProtocolError


@dataclass(frozen=True)
class ExportResult:
    format: str
    output: Path
    channels: tuple[int, ...]
    samples: int
    rows: int


def _load_manifest(capture_dir: Path) -> tuple[dict, int, int, list[tuple[int, Path]]]:
    try:
        manifest = json.loads((capture_dir / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"cannot read capture manifest: {exc}") from exc
    try:
        sample_rate = int(manifest["sample_rate_hz"])
        depth = int(manifest["sample_depth"])
        channel_items = manifest["channels"].items()
        channels = sorted(
            (int(number), capture_dir / details["file"])
            for number, details in channel_items
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ProtocolError(f"invalid capture manifest: {exc}") from exc
    if sample_rate <= 0 or depth <= 0 or not channels:
        raise ProtocolError("capture manifest requires a positive rate, depth, and channels")
    if 1_000_000_000 % sample_rate:
        raise ProtocolError(f"sample rate {sample_rate} Hz cannot be represented exactly in nanoseconds")
    if any(channel < 0 or channel > 15 for channel, _ in channels):
        raise ProtocolError("capture manifest channel must be in range 0..15")
    return manifest, sample_rate, depth, channels


def _level(data: mmap.mmap, sample_index: int) -> int:
    return (data[sample_index >> 3] >> (sample_index & 7)) & 1


def _transitions(data: mmap.mmap, depth: int, channel: int) -> Iterator[tuple[int, int, int]]:
    previous = _level(data, 0)
    for index in range(1, depth):
        current = _level(data, index)
        if current != previous:
            yield index, channel, current
            previous = current


def _write_csv(
    output: TextIO, maps: list[mmap.mmap], channels: list[int], depth: int, period_ns: int
) -> int:
    writer = csv.writer(output)
    writer.writerow(("sample_index", "time_ns", *(f"CH{channel}" for channel in channels)))
    for index in range(depth):
        writer.writerow((index, index * period_ns, *(_level(data, index) for data in maps)))
    return depth


def _merged_transitions(
    maps: list[mmap.mmap], channels: list[int], depth: int
) -> Iterator[tuple[int, int, int]]:
    return heapq.merge(*(_transitions(data, depth, channel) for data, channel in zip(maps, channels)))


def _write_edges(
    output: TextIO, maps: list[mmap.mmap], channels: list[int], depth: int, period_ns: int
) -> int:
    writer = csv.writer(output)
    writer.writerow(("sample_index", "time_ns", "channel", "level"))
    rows = 0
    for index, channel, level in _merged_transitions(maps, channels, depth):
        writer.writerow((index, index * period_ns, channel, level))
        rows += 1
    return rows


def _write_vcd(
    output: TextIO, maps: list[mmap.mmap], channels: list[int], depth: int, period_ns: int
) -> int:
    symbols = [chr(33 + index) for index in range(len(channels))]
    output.write("$timescale 1ns $end\n$scope module dl16 $end\n")
    for channel, symbol in zip(channels, symbols):
        output.write(f"$var wire 1 {symbol} CH{channel} $end\n")
    output.write("$upscope $end\n$enddefinitions $end\n#0\n")
    for data, symbol in zip(maps, symbols):
        output.write(f"{_level(data, 0)}{symbol}\n")

    rows = 0
    previous_index: int | None = None
    for index, channel, level in _merged_transitions(maps, channels, depth):
        if index != previous_index:
            output.write(f"#{index * period_ns}\n")
            previous_index = index
        output.write(f"{level}{symbols[channels.index(channel)]}\n")
        rows += 1
    return rows


def export_capture(
    capture_dir: str | Path, output: str | Path, *, format: str
) -> ExportResult:
    """Export a decoded capture without loading the sample arrays into memory."""
    capture_dir = Path(capture_dir)
    output_path = Path(output)
    _, sample_rate, depth, channel_files = _load_manifest(capture_dir)
    channels = [channel for channel, _ in channel_files]
    required_bytes = (depth + 7) // 8

    if format not in {"csv", "edges", "vcd"}:
        raise ProtocolError(f"unsupported export format: {format}")

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            maps: list[mmap.mmap] = []
            for channel, path in channel_files:
                handle = stack.enter_context(path.open("rb"))
                size = path.stat().st_size
                if size < required_bytes:
                    raise ProtocolError(
                        f"channel {channel} file is too short: {size} bytes, need {required_bytes}"
                    )
                maps.append(stack.enter_context(mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)))
            destination = stack.enter_context(output_path.open("w", newline=""))
            period_ns = 1_000_000_000 // sample_rate
            if format == "csv":
                rows = _write_csv(destination, maps, channels, depth, period_ns)
            elif format == "edges":
                rows = _write_edges(destination, maps, channels, depth, period_ns)
            else:
                rows = _write_vcd(destination, maps, channels, depth, period_ns)
    except ProtocolError:
        raise
    except OSError as exc:
        raise ProtocolError(f"cannot export capture: {exc}") from exc

    return ExportResult(format, output_path, tuple(channels), depth, rows)
