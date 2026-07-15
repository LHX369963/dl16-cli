from __future__ import annotations

import json
import math
from pathlib import Path

from .errors import ProtocolError


class _Signal:
    def __init__(self, data: bytes, depth: int) -> None:
        self.data = data
        self.depth = depth

    def __getitem__(self, index: int) -> int:
        return (self.data[index >> 3] >> (index & 7)) & 1


def _load(capture_dir: str | Path, requested: list[int]) -> tuple[int, int, dict[int, _Signal]]:
    root = Path(capture_dir)
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        rate = int(manifest["sample_rate_hz"])
        depth = int(manifest["sample_depth"])
        entries = manifest["channels"]
        signals = {}
        for channel in requested:
            entry = entries[str(channel)]
            data = (root / entry["file"]).read_bytes()
            if len(data) < (depth + 7) // 8:
                raise ProtocolError(f"CH{channel} capture file is too short")
            signals[channel] = _Signal(data, depth)
    except ProtocolError:
        raise
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ProtocolError(f"cannot load decoded capture: {exc}") from exc
    if rate <= 0 or depth <= 0:
        raise ProtocolError("decoded capture requires positive sample rate and depth")
    return rate, depth, signals


def _time_ns(sample: int, rate: int) -> int:
    return sample * 1_000_000_000 // rate


def decode_uart_capture(
    capture_dir: str | Path,
    *,
    channel: int,
    baud: int,
    data_bits: int = 8,
    parity: str = "none",
    stop_bits: int = 1,
    inverted: bool = False,
) -> dict:
    rate, depth, signals = _load(capture_dir, [channel])
    if baud <= 0 or baud > rate / 2:
        raise ProtocolError("UART baud must be positive and sampled at least twice per bit")
    if data_bits not in range(5, 10) or stop_bits not in (1, 2):
        raise ProtocolError("UART supports 5..9 data bits and 1 or 2 stop bits")
    if parity not in {"none", "even", "odd"}:
        raise ProtocolError("UART parity must be none, even, or odd")
    signal = signals[channel]
    samples_per_bit = rate / baud

    def level(index: int) -> int:
        return signal[index] ^ int(inverted)

    frames = []
    index = 1
    parity_bits = 0 if parity == "none" else 1
    frame_bits = 1 + data_bits + parity_bits + stop_bits
    while index < depth:
        if level(index - 1) == 1 and level(index) == 0:
            start = index
            final_center = start + (data_bits + parity_bits + stop_bits + 0.5) * samples_per_bit
            if final_center >= depth:
                break
            start_ok = level(round(start + 0.5 * samples_per_bit)) == 0
            bits = [
                level(round(start + (1.5 + bit) * samples_per_bit))
                for bit in range(data_bits)
            ]
            value = sum(bit << position for position, bit in enumerate(bits))
            parity_ok = True
            if parity_bits:
                parity_level = level(round(start + (1.5 + data_bits) * samples_per_bit))
                expected = sum(bits) & 1
                if parity == "odd":
                    expected ^= 1
                parity_ok = parity_level == expected
            stop_offset = 1.5 + data_bits + parity_bits
            stop_ok = all(
                level(round(start + (stop_offset + bit) * samples_per_bit)) == 1
                for bit in range(stop_bits)
            )
            frames.append({
                "start_sample": start,
                "start_time_ns": _time_ns(start, rate),
                "value": value,
                "hex": f"0x{value:0{(data_bits + 3) // 4}X}",
                "valid": start_ok and parity_ok and stop_ok,
                "parity_ok": parity_ok,
                "stop_ok": stop_ok,
            })
            index = max(index + 1, round(start + frame_bits * samples_per_bit))
        else:
            index += 1
    return {
        "protocol": "uart", "channel": channel, "sample_rate_hz": rate,
        "baud": baud, "data_bits": data_bits, "parity": parity,
        "stop_bits": stop_bits, "inverted": inverted, "frames": frames,
    }


def decode_i2c_capture(
    capture_dir: str | Path, *, scl_channel: int, sda_channel: int
) -> dict:
    rate, depth, signals = _load(capture_dir, [scl_channel, sda_channel])
    scl, sda = signals[scl_channel], signals[sda_channel]
    transactions: list[dict] = []
    active: dict | None = None
    bits: list[int] = []

    def finish(stop_sample: int | None, repeated: bool = False) -> None:
        nonlocal active, bits
        if active is None:
            return
        active["stop_sample"] = stop_sample
        active["repeated_start"] = repeated
        if active["bytes"]:
            first = active["bytes"][0]["value"]
            active["address"] = first >> 1
            active["read"] = bool(first & 1)
        transactions.append(active)
        active = None
        bits = []

    for index in range(1, depth):
        sda_falling = sda[index - 1] == 1 and sda[index] == 0 and scl[index] == 1
        sda_rising = sda[index - 1] == 0 and sda[index] == 1 and scl[index] == 1
        if sda_falling:
            if active is not None:
                finish(index, repeated=True)
            active = {
                "start_sample": index,
                "start_time_ns": _time_ns(index, rate),
                "bytes": [],
            }
            continue
        if sda_rising and active is not None:
            finish(index)
            continue
        if active is not None and scl[index - 1] == 0 and scl[index] == 1:
            bits.append(sda[index])
            if len(bits) == 9:
                value = 0
                for bit in bits[:8]:
                    value = (value << 1) | bit
                active["bytes"].append({
                    "value": value, "hex": f"0x{value:02X}", "ack": bits[8] == 0,
                    "sample": index,
                })
                bits = []
    if active is not None:
        finish(None)
    return {
        "protocol": "i2c", "sample_rate_hz": rate,
        "scl_channel": scl_channel, "sda_channel": sda_channel,
        "transactions": transactions,
    }


def decode_spi_capture(
    capture_dir: str | Path,
    *,
    clock_channel: int,
    mosi_channel: int | None = None,
    miso_channel: int | None = None,
    cs_channel: int | None = None,
    mode: int = 0,
    bits_per_word: int = 8,
    bit_order: str = "msb",
) -> dict:
    if mosi_channel is None and miso_channel is None:
        raise ProtocolError("SPI decode requires MOSI and/or MISO")
    if mode not in range(4) or bits_per_word < 1 or bits_per_word > 32:
        raise ProtocolError("SPI mode must be 0..3 and bits_per_word 1..32")
    if bit_order not in {"msb", "lsb"}:
        raise ProtocolError("SPI bit_order must be msb or lsb")
    requested = [clock_channel]
    requested += [channel for channel in (mosi_channel, miso_channel, cs_channel) if channel is not None]
    rate, depth, signals = _load(capture_dir, requested)
    clock = signals[clock_channel]
    cpol, cpha = mode >> 1, mode & 1
    sample_rising = (cpol == 0) if cpha == 0 else (cpol == 1)
    transactions = []
    active = cs_channel is None or signals[cs_channel][0] == 0
    current = {"start_sample": 0, "mosi": [], "miso": []} if active else None
    pending = {"mosi": [], "miso": []}

    def append_bit(name: str, bit: int) -> None:
        assert current is not None
        pending[name].append(bit)
        if len(pending[name]) == bits_per_word:
            value = 0
            if bit_order == "msb":
                for item in pending[name]:
                    value = (value << 1) | item
            else:
                value = sum(item << offset for offset, item in enumerate(pending[name]))
            current[name].append(value)
            pending[name] = []

    def finish(index: int) -> None:
        nonlocal current
        if current is not None:
            current["end_sample"] = index
            current["partial_bits"] = {key: list(value) for key, value in pending.items() if value}
            transactions.append(current)
            current = None
        pending["mosi"] = []
        pending["miso"] = []

    for index in range(1, depth):
        if cs_channel is not None:
            cs = signals[cs_channel]
            if cs[index - 1] == 1 and cs[index] == 0:
                active = True
                current = {"start_sample": index, "mosi": [], "miso": []}
            elif cs[index - 1] == 0 and cs[index] == 1:
                finish(index)
                active = False
                continue
        rising = clock[index - 1] == 0 and clock[index] == 1
        falling = clock[index - 1] == 1 and clock[index] == 0
        if active and ((sample_rising and rising) or (not sample_rising and falling)):
            if mosi_channel is not None:
                append_bit("mosi", signals[mosi_channel][index])
            if miso_channel is not None:
                append_bit("miso", signals[miso_channel][index])
    if active and current is not None:
        finish(depth - 1)
    return {
        "protocol": "spi", "sample_rate_hz": rate, "mode": mode,
        "clock_channel": clock_channel, "mosi_channel": mosi_channel,
        "miso_channel": miso_channel, "cs_channel": cs_channel,
        "bits_per_word": bits_per_word, "bit_order": bit_order,
        "transactions": transactions,
    }
