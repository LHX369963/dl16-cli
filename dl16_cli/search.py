from __future__ import annotations

import json
import mmap
from contextlib import ExitStack
from pathlib import Path

from .errors import ProtocolError
from .trigger import TriggerState


def search_capture(
    capture_dir: str | Path,
    *,
    conditions: dict[int, TriggerState],
    start_sample: int = 0,
    end_sample: int | None = None,
    limit: int = 1000,
) -> dict:
    if not conditions or all(state == TriggerState.NULL for state in conditions.values()):
        raise ProtocolError("search requires at least one active condition")
    if not isinstance(limit, int) or limit <= 0:
        raise ProtocolError("search limit must be a positive integer")
    root = Path(capture_dir)
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        rate = int(manifest["sample_rate_hz"])
        depth = int(manifest["sample_depth"])
        entries = manifest["channels"]
        paths = {channel: root / entries[str(channel)]["file"] for channel in conditions}
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"cannot load capture for search: {exc}") from exc
    end = depth if end_sample is None else end_sample
    if rate <= 0 or depth <= 0 or not 0 <= start_sample < end <= depth:
        raise ProtocolError("search range must satisfy 0 <= start < end <= sample depth")
    required = (depth + 7) // 8
    matches: list[dict[str, int]] = []
    edge_condition = any(
        state in {TriggerState.RISING, TriggerState.FALLING, TriggerState.DOUBLE}
        for state in conditions.values()
    )
    try:
        with ExitStack() as stack:
            maps = {}
            for channel, path in paths.items():
                if path.stat().st_size < required:
                    raise ProtocolError(f"CH{channel} capture file is too short")
                source = stack.enter_context(path.open("rb"))
                maps[channel] = stack.enter_context(
                    mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)
                )
            for byte_index in range(start_sample // 8, (end + 7) // 8):
                byte_start = byte_index * 8
                valid_bits = min(8, depth - byte_start)
                valid_mask = (1 << valid_bits) - 1
                matched = valid_mask
                for channel, state in conditions.items():
                    value = maps[channel][byte_index] & valid_mask
                    if byte_index:
                        previous = (maps[channel][byte_index - 1] >> 7) & 1
                    else:
                        previous = value & 1
                    previous_bits = ((value << 1) | previous) & valid_mask
                    if state == TriggerState.HIGH:
                        condition_mask = value
                    elif state == TriggerState.LOW:
                        condition_mask = ~value & valid_mask
                    elif state == TriggerState.RISING:
                        condition_mask = value & ~previous_bits & valid_mask
                    elif state == TriggerState.FALLING:
                        condition_mask = ~value & previous_bits & valid_mask
                    elif state == TriggerState.DOUBLE:
                        condition_mask = value ^ previous_bits
                    else:
                        condition_mask = valid_mask
                    matched &= condition_mask
                if byte_index == 0 and edge_condition:
                    matched &= ~1
                if byte_start < start_sample:
                    matched &= ~((1 << (start_sample - byte_start)) - 1)
                if byte_start + valid_bits > end:
                    matched &= (1 << (end - byte_start)) - 1
                while matched:
                    lowest = matched & -matched
                    sample = byte_start + lowest.bit_length() - 1
                    matches.append({"sample": sample, "time_ns": sample * 1_000_000_000 // rate})
                    matched ^= lowest
                    if len(matches) > limit:
                        break
                if len(matches) > limit:
                    break
    except ProtocolError:
        raise
    except OSError as exc:
        raise ProtocolError(f"cannot search capture: {exc}") from exc
    truncated = len(matches) > limit
    return {
        "sample_rate_hz": rate,
        "sample_depth": depth,
        "range": {"start_sample": start_sample, "end_sample": end},
        "conditions": {
            str(channel): ("either" if state == TriggerState.DOUBLE else state.name.lower())
            for channel, state in sorted(conditions.items())
        },
        "matches": matches[:limit],
        "truncated": truncated,
    }
