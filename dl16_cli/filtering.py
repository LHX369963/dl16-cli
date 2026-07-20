from __future__ import annotations

import json
import mmap
import shutil
from contextlib import ExitStack
from pathlib import Path

from .errors import Dl16Error, ProtocolError
from .storage import prepare_capture_directory


def _level(data: mmap.mmap, sample: int) -> int:
    return (data[sample >> 3] >> (sample & 7)) & 1


def _transitions(data: mmap.mmap, depth: int):
    previous = _level(data, 0)
    for byte_index in range((depth + 7) // 8):
        value = data[byte_index]
        valid_bits = min(8, depth - byte_index * 8)
        mask = (1 << valid_bits) - 1
        changed = (value ^ ((value << 1) | previous)) & mask
        if byte_index == 0:
            changed &= ~1
        while changed:
            lowest = changed & -changed
            yield byte_index * 8 + lowest.bit_length() - 1
            changed ^= lowest
        previous = (value >> (valid_bits - 1)) & 1


def _fill_bits(data: mmap.mmap, start: int, end: int, level: int) -> None:
    if start >= end:
        return
    first_byte, first_bit = divmod(start, 8)
    last_byte, last_bit = divmod(end, 8)
    if first_byte == last_byte:
        mask = ((1 << (end - start)) - 1) << first_bit
        data[first_byte] = (data[first_byte] | mask) if level else (data[first_byte] & ~mask)
        return
    if first_bit:
        mask = 0xFF << first_bit & 0xFF
        data[first_byte] = (data[first_byte] | mask) if level else (data[first_byte] & ~mask)
        first_byte += 1
    fill = b"\xff" if level else b"\x00"
    if last_byte > first_byte:
        data[first_byte:last_byte] = fill * (last_byte - first_byte)
    if last_bit:
        mask = (1 << last_bit) - 1
        data[last_byte] = (data[last_byte] | mask) if level else (data[last_byte] & ~mask)


def _filter_channel(source: Path, destination: Path, depth: int, maximum: int) -> int:
    shutil.copyfile(source, destination)
    removed = 0
    with ExitStack() as stack:
        source_file = stack.enter_context(source.open("rb"))
        target_file = stack.enter_context(destination.open("r+b"))
        original = stack.enter_context(mmap.mmap(source_file.fileno(), 0, access=mmap.ACCESS_READ))
        target = stack.enter_context(mmap.mmap(target_file.fileno(), 0, access=mmap.ACCESS_WRITE))
        previous_transition: int | None = None
        for transition in _transitions(original, depth):
            if previous_transition is not None and transition - previous_transition <= maximum:
                _fill_bits(
                    target,
                    previous_transition,
                    transition,
                    _level(original, previous_transition - 1),
                )
                removed += 1
            previous_transition = transition
        target.flush()
    return removed


def filter_glitches(
    capture_dir: str | Path,
    output_dir: str | Path,
    *,
    maximum_samples: int,
    channels: list[int] | None = None,
    overwrite: bool = False,
) -> dict:
    if not isinstance(maximum_samples, int) or maximum_samples <= 0:
        raise ProtocolError("glitch filter maximum_samples must be a positive integer")
    source_root = Path(capture_dir)
    if source_root.resolve() == Path(output_dir).resolve():
        raise ProtocolError("glitch filter output directory must differ from the input directory")
    try:
        manifest = json.loads((source_root / "manifest.json").read_text())
        depth = int(manifest["sample_depth"])
        entries = manifest["channels"]
        available = sorted(int(channel) for channel in entries)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"cannot load capture for glitch filtering: {exc}") from exc
    selected = available if channels is None else channels
    if depth <= 0 or not available:
        raise ProtocolError("glitch filter requires a positive sample depth and channels")
    if not selected or len(set(selected)) != len(selected):
        raise ProtocolError("glitch filter channels must be non-empty and unique")
    missing = [channel for channel in selected if channel not in available]
    if missing:
        raise ProtocolError(f"capture does not contain CH{missing[0]}")
    destination_root = prepare_capture_directory(output_dir, overwrite=overwrite)
    removed: dict[str, int] = {}
    try:
        for channel in available:
            entry = entries[str(channel)]
            source = source_root / entry["file"]
            destination = destination_root / entry["file"]
            if source.stat().st_size < (depth + 7) // 8:
                raise ProtocolError(f"CH{channel} capture file is too short")
            if channel in selected:
                removed[str(channel)] = _filter_channel(source, destination, depth, maximum_samples)
            else:
                shutil.copyfile(source, destination)
        result = dict(manifest)
        result["derived_from"] = str(source_root)
        result["glitch_filter"] = {
            "maximum_samples": maximum_samples,
            "channels": selected,
            "removed_pulses": removed,
        }
        (destination_root / "manifest.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n"
        )
    except (OSError, KeyError, TypeError) as exc:
        raise Dl16Error(f"cannot write filtered capture: {exc}") from exc
    return result
