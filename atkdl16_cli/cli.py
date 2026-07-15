from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from collections.abc import Sequence

from .capture import (
    Dl16CapturePacket,
    Dl16StreamParser,
    SamplingParameters,
    decode_channel_packet,
    interpret_capture_packet,
)
from .device import AtkDevice
from .decoders import decode_i2c_capture, decode_spi_capture, decode_uart_capture
from .errors import AtkDl16Error
from .export import export_capture
from .firmware import (
    FirmwareTarget,
    McuTransportMode,
    build_enter_bootloader_frame,
    build_enter_update_frame,
    build_get_mcu_version_frame,
    build_restart_mcu_frame,
    firmware_data_frames,
    flash_firmware,
)
from .protocol import SUPPORTED_USB_IDS, parse_hex_payload
from .sampling import resolve_sample_index, validate_capture_combination
from .session import Dl16Session, run_json_session
from .streaming import stream_capture_to_disk
from .trigger import SerialTriggerConfig, StageCondition, TriggerState, parse_trigger_states
from .usb import DeviceInfo, DryRunBackend, PyUsbBackend, UsbBackend, parse_usb_id


def _print_frame(label: str, frame: bytes) -> None:
    print(f"{label} frame: {frame.hex()}")


def _print_response(label: str, response: bytes) -> None:
    print(f"{label} response: {response.hex()}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atkdl16")
    parser.add_argument("--dry-run", action="store_true", help="print frames without accessing USB hardware")
    parser.add_argument("--vid-pid", default=None, help="select USB device as VID:PID hex, for example 1a86:ffcc")
    parser.add_argument("--timeout-ms", type=int, default=1000, help="USB timeout in milliseconds")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list supported or attached devices")
    sub.add_parser("info", help="print device info query frame or query a device")
    session = sub.add_parser("session", help="run newline-delimited JSON commands over one persistent link")
    session.add_argument("--commands", default="-", help="JSONL command file; '-' reads standard input")

    stop = sub.add_parser("stop", help="send stop command")
    stop.add_argument("--channel", type=int, default=None)

    pwm = sub.add_parser("pwm", help="PWM commands")
    pwm_sub = pwm.add_subparsers(dest="pwm_command", required=True)
    pwm_start = pwm_sub.add_parser("start", help="start PWM")
    pwm_start.add_argument("--channel", type=int, required=True)
    pwm_start.add_argument("--freq", type=int, required=True)
    pwm_start.add_argument("--duty", type=float, required=True)
    pwm_stop = pwm_sub.add_parser("stop", help="stop PWM")
    pwm_stop.add_argument("--channel", type=int, required=True)

    capture = sub.add_parser("capture", help="capture configuration and acquisition")
    capture_sub = capture.add_subparsers(dest="capture_command", required=True)
    configure = capture_sub.add_parser("configure", help="send recovered sampling parameters")
    configure.add_argument("--set-time", type=float, required=True, help="original settingData.setTime value")
    configure.add_argument("--set-hz", type=int, required=True, help="sampling frequency in Hz")
    configure.add_argument("--trigger-position", type=float, required=True, help="trigger position percent")
    configure.add_argument("--threshold", type=float, required=True, help="threshold level in volts")
    configure.add_argument("--sample-index", type=int, required=True, help="original settingData.index value")
    configure.add_argument("--rle", action="store_true", help="enable hardware RLE flag")
    configure.add_argument("--buffer", action="store_true", help="enable buffer mode flag")
    configure.add_argument("--collect-type", type=int, default=1, help="original collectType value")
    parse_capture = capture_sub.add_parser("parse", help="parse a saved raw DL16 receive stream")
    parse_capture.add_argument("--input", required=True, help="input file containing concatenated wire packets")
    read_capture = capture_sub.add_parser("read", help="read and losslessly save DL16 packets from USB")
    read_capture.add_argument("--packets", type=int, required=True, help="number of complete packets to read")
    read_capture.add_argument("--output", required=True, help="output file for concatenated raw wire packets")
    read_capture.add_argument("--read-size", type=int, default=None, help="optional USB bulk-IN read size")
    decode_capture = capture_sub.add_parser("decode", help="decode type-1 packets into per-channel packed samples")
    decode_capture.add_argument("--input", required=True)
    decode_capture.add_argument("--output-dir", required=True)
    decode_capture.add_argument("--rle", action="store_true", help="expand recovered value/count RLE pairs")
    export = capture_sub.add_parser("export", help="export decoded channels as CSV, edge CSV, or VCD")
    export.add_argument("--input-dir", required=True, help="decoded capture directory containing manifest.json")
    export.add_argument("--output", required=True, help="destination file")
    export.add_argument("--format", required=True, choices=("csv", "edges", "vcd"))
    run_capture = capture_sub.add_parser(
        "run", help="initialize, configure, trigger, acquire and decode in one process"
    )
    channel_selection = run_capture.add_mutually_exclusive_group(required=True)
    channel_selection.add_argument("--channel", type=int, help="single input channel, 0..15")
    channel_selection.add_argument("--channels", help="comma-separated input channels, for example 0,3,6")
    run_capture.add_argument("--set-time", type=float, required=True, help="capture time in milliseconds")
    run_capture.add_argument(
        "--set-hz", "--sample-rate", dest="set_hz", type=int, required=True,
        help="sampling frequency in Hz; the hardware index is selected automatically",
    )
    run_capture.add_argument("--trigger-position", type=float, required=True, help="trigger position percent")
    run_capture.add_argument(
        "--trigger", choices=("none", "rising", "falling"), default="none",
        help="optional simple edge trigger",
    )
    run_capture.add_argument(
        "--trigger-channel", type=int, default=None,
        help="edge-trigger channel; defaults to the first captured channel",
    )
    run_capture.add_argument("--threshold", type=float, required=True, help="threshold level in volts")
    run_capture.add_argument(
        "--sample-index", type=int, default=None,
        help="optional recovered index assertion; normally selected automatically",
    )
    run_capture.add_argument("--buffer", action="store_true", help="use hardware Buffer acquisition mode")
    run_capture.add_argument("--rle", action="store_true", help="enable Buffer hardware RLE compression")
    run_capture.add_argument("--output-dir", required=True)
    run_capture.add_argument("--read-size", type=int, default=16384)
    stream_capture = capture_sub.add_parser(
        "stream", help="capture Stream mode incrementally to disk; Ctrl-C retains synchronized data"
    )
    stream_selection = stream_capture.add_mutually_exclusive_group(required=True)
    stream_selection.add_argument("--channel", type=int, help="single input channel, 0..15")
    stream_selection.add_argument("--channels", help="comma-separated input channels")
    stream_capture.add_argument(
        "--duration", type=float, default=None,
        help="capture duration in seconds; omit to run until Ctrl-C or the 40-bit depth limit",
    )
    stream_capture.add_argument(
        "--set-hz", "--sample-rate", dest="set_hz", type=int, required=True,
        help="sampling frequency in Hz",
    )
    stream_capture.add_argument("--threshold", type=float, default=1.2, help="threshold level in volts")
    stream_capture.add_argument("--sample-index", type=int, default=None)
    stream_capture.add_argument("--output-dir", required=True)
    stream_capture.add_argument("--read-size", type=int, default=16384)
    uart = capture_sub.add_parser("uart", help="offline UART decode from a capture directory")
    uart.add_argument("--input-dir", required=True)
    uart.add_argument("--channel", type=int, required=True)
    uart.add_argument("--baud", type=int, required=True)
    uart.add_argument("--data-bits", type=int, default=8)
    uart.add_argument("--parity", choices=("none", "even", "odd"), default="none")
    uart.add_argument("--stop-bits", type=int, choices=(1, 2), default=1)
    uart.add_argument("--inverted", action="store_true")
    uart.add_argument("--output", default=None, help="optional JSON output file")
    i2c = capture_sub.add_parser("i2c", help="offline I2C decode from a capture directory")
    i2c.add_argument("--input-dir", required=True)
    i2c.add_argument("--scl", type=int, required=True, help="SCL channel")
    i2c.add_argument("--sda", type=int, required=True, help="SDA channel")
    i2c.add_argument("--output", default=None, help="optional JSON output file")
    spi = capture_sub.add_parser("spi", help="offline SPI decode from a capture directory")
    spi.add_argument("--input-dir", required=True)
    spi.add_argument("--clock", type=int, required=True)
    spi.add_argument("--mosi", type=int, default=None)
    spi.add_argument("--miso", type=int, default=None)
    spi.add_argument("--cs", type=int, default=None)
    spi.add_argument("--mode", type=int, choices=range(4), default=0)
    spi.add_argument("--bits-per-word", type=int, default=8)
    spi.add_argument("--bit-order", choices=("msb", "lsb"), default="msb")
    spi.add_argument("--output", default=None, help="optional JSON output file")

    trigger = sub.add_parser("trigger", help="configure recovered trigger modes")
    trigger_sub = trigger.add_subparsers(dest="trigger_command", required=True)
    simple = trigger_sub.add_parser("simple", help="configure simple per-channel trigger")
    simple.add_argument("--states", required=True, help="comma-separated states in channel order")
    simple.add_argument("--enabled", default=None, help="optional comma-separated 1/0 channel mask")
    simple.add_argument("--collect-type", type=int, default=1)
    simple.add_argument("--channel-offset", type=int, default=0)
    stage = trigger_sub.add_parser("stage", help="configure staged trigger from JSON")
    stage.add_argument("--file", required=True)
    serial = trigger_sub.add_parser("serial", help="configure serial trigger from JSON")
    serial.add_argument("--file", required=True)

    raw = sub.add_parser("raw", help="send recovered command IDs with raw hex payloads")
    raw_sub = raw.add_subparsers(dest="raw_command", required=True)
    for name in ("parameter-setting", "simple-trigger", "stage-trigger", "serial-trigger"):
        raw_cmd = raw_sub.add_parser(name, help=f"send raw {name} payload")
        raw_cmd.add_argument("--payload-hex", required=True, help="payload bytes as hexadecimal, spaces allowed")

    firmware = sub.add_parser("firmware", help="inspect or execute the recovered MCU update protocol")
    firmware_sub = firmware.add_subparsers(dest="firmware_command", required=True)
    version = firmware_sub.add_parser("version", help="query MCU/bootloader version")
    version.add_argument("--mode", default=McuTransportMode.FRAMED_510.value, choices=[mode.value for mode in McuTransportMode])
    bootloader = firmware_sub.add_parser("enter-bootloader", help="request application-to-bootloader transition")
    bootloader.add_argument("--mode", default=McuTransportMode.FRAMED_510.value, choices=[mode.value for mode in McuTransportMode])
    bootloader.add_argument("--i-understand-this-can-brick", action="store_true")
    for name in ("plan", "flash"):
        item = firmware_sub.add_parser(name)
        item.add_argument("--file", required=True)
        item.add_argument("--target", required=True, choices=[target.value for target in FirmwareTarget])
        item.add_argument(
            "--mode",
            default=McuTransportMode.FRAMED_510.value,
            choices=[mode.value for mode in McuTransportMode],
        )
        if name == "plan":
            item.add_argument("--output-dir", required=True)
        else:
            item.add_argument("--i-understand-this-can-brick", action="store_true")

    return parser


def _dry_backend() -> DryRunBackend:
    devices = [DeviceInfo(vid=item.vid, pid=item.pid, path="supported-id", speed="unknown") for item in SUPPORTED_USB_IDS]
    return DryRunBackend(devices=devices)


def create_backend(dry_run: bool, vid_pid: tuple[int, int] | None, timeout_ms: int) -> UsbBackend:
    if dry_run:
        return _dry_backend()
    return PyUsbBackend(vid_pid=vid_pid, timeout_ms=timeout_ms)


def _send_raw_command(device: AtkDevice, raw_command: str, payload: bytes) -> tuple[str, bytes]:
    if raw_command == "parameter-setting":
        return "PARAMETER_SETTING", device.parameter_setting_raw(payload)
    if raw_command == "simple-trigger":
        return "SIMPLE_TRIGGER", device.simple_trigger_raw(payload)
    if raw_command == "stage-trigger":
        return "STAGE_TRIGGER", device.stage_trigger_raw(payload)
    if raw_command == "serial-trigger":
        return "SERIAL_TRIGGER", device.serial_trigger_raw(payload)
    raise AssertionError(f"unsupported raw command: {raw_command}")


def _parse_enabled(text: str | None) -> list[bool] | None:
    if text is None:
        return None
    values = [item.strip() for item in text.split(",")]
    if any(item not in {"0", "1"} for item in values):
        raise AtkDl16Error("enabled mask must contain only comma-separated 0/1 values")
    return [item == "1" for item in values]


def _parse_capture_channels(single: int | None, multiple: str | None) -> list[int]:
    if multiple is None:
        channels = [single] if single is not None else []
    else:
        raw_values = [item.strip() for item in multiple.split(",")]
        if not raw_values or any(not item for item in raw_values):
            raise AtkDl16Error("channels must be a non-empty comma-separated list")
        try:
            channels = [int(item, 10) for item in raw_values]
        except ValueError as exc:
            raise AtkDl16Error("channels must contain decimal channel numbers") from exc
    if not channels:
        raise AtkDl16Error("at least one capture channel is required")
    if len(set(channels)) != len(channels):
        raise AtkDl16Error("duplicate channel in capture channel list")
    invalid = [channel for channel in channels if not 0 <= channel <= 15]
    if invalid:
        raise AtkDl16Error(f"channel must be in range 0..15, got {invalid[0]}")
    return sorted(channels)


def _load_json_object(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise AtkDl16Error(f"cannot read trigger JSON {path!r}: {exc}") from exc
    if not isinstance(value, dict):
        raise AtkDl16Error("trigger JSON root must be an object")
    return value


def _states_from_json(values: object):
    if not isinstance(values, list) or not values:
        raise AtkDl16Error("trigger state field must be a non-empty array")
    return parse_trigger_states(",".join(str(item) for item in values))


def _packet_summary(index: int, packet: Dl16CapturePacket) -> dict[str, object]:
    summary: dict[str, object] = {
        "index": index,
        "payload_length": len(packet.payload),
        "body_length": len(packet.body),
    }
    summary.update(interpret_capture_packet(packet))
    return summary


def _print_packet_summary(index: int, packet: Dl16CapturePacket) -> None:
    print(json.dumps(_packet_summary(index, packet), sort_keys=True))


def _parse_capture_file(path: str) -> list[Dl16CapturePacket]:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise AtkDl16Error(f"cannot read capture file {path!r}: {exc}") from exc
    return Dl16StreamParser().feed(data)


def _read_capture_packets(
    backend: UsbBackend, *, packet_count: int, output: str, read_size: int | None
) -> list[Dl16CapturePacket]:
    if packet_count <= 0:
        raise AtkDl16Error(f"packets must be positive, got {packet_count}")
    if read_size is not None and read_size <= 0:
        raise AtkDl16Error(f"read-size must be positive, got {read_size}")
    parser = Dl16StreamParser()
    packets: list[Dl16CapturePacket] = []
    try:
        stream = Path(output).open("wb")
    except OSError as exc:
        raise AtkDl16Error(f"cannot open capture output {output!r}: {exc}") from exc
    with stream:
        while len(packets) < packet_count:
            chunk = backend.read_chunk(size=read_size)
            if not chunk:
                raise AtkDl16Error(
                    f"USB receive stream ended before {packet_count} packet(s); got {len(packets)}"
                )
            decoded = parser.feed(chunk)
            remaining = packet_count - len(packets)
            for packet in decoded[:remaining]:
                stream.write(packet.raw)
                packets.append(packet)
    return packets


def _decode_capture_file(input_path: str, output_dir: str, *, is_rle: bool) -> dict:
    channel_data: dict[int, bytearray] = {}
    metadata: dict[int, list[int | None]] = {}
    for packet in _parse_capture_file(input_path):
        if packet.packet_type != 1:
            continue
        block = decode_channel_packet(packet, is_rle=is_rle)
        channel_data.setdefault(block.channel, bytearray()).extend(block.packed_samples)
        metadata.setdefault(block.channel, []).append(block.metadata1)
    if not channel_data:
        raise AtkDl16Error("capture contains no type-1 channel sample packets")
    destination = Path(output_dir)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        channels = {}
        for channel in sorted(channel_data):
            filename = f"channel-{channel:02d}.bin"
            packed = bytes(channel_data[channel])
            (destination / filename).write_bytes(packed)
            channels[str(channel)] = {
                "file": filename,
                "packed_bytes": len(packed),
                "samples": len(packed) * 8,
                "metadata1": metadata[channel],
            }
        manifest = {"bit_order": "lsb-first", "rle": is_rle, "channels": channels}
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise AtkDl16Error(f"cannot write decoded capture to {output_dir!r}: {exc}") from exc
    return manifest


def _emit_protocol_decode(result: dict, output: str | None) -> None:
    if output is not None:
        try:
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        except OSError as exc:
            raise AtkDl16Error(f"cannot write protocol decode {output!r}: {exc}") from exc
    print(json.dumps(result, sort_keys=True))


def _run_multi_channel_capture(
    device: AtkDevice,
    backend: UsbBackend,
    params: SamplingParameters,
    *,
    channels: Sequence[int],
    trigger_state: TriggerState = TriggerState.NULL,
    trigger_channel: int | None = None,
    output_dir: str,
    read_size: int,
) -> dict:
    channels = list(channels)
    if not channels:
        raise AtkDl16Error("at least one capture channel is required")
    if len(set(channels)) != len(channels):
        raise AtkDl16Error("duplicate channel in capture channel list")
    if any(not 0 <= channel <= 15 for channel in channels):
        raise AtkDl16Error("capture channels must be in range 0..15")
    if trigger_state != TriggerState.NULL:
        if trigger_channel is None:
            trigger_channel = channels[0]
        if trigger_channel not in channels:
            raise AtkDl16Error("trigger channel must be one of the captured channels")
    if read_size <= 0 or read_size % 2048:
        raise AtkDl16Error("capture run read-size must be a positive multiple of 2048")

    depth = int(params.set_time * (params.set_hz // 1_000))
    expected_bytes = (depth + 7) // 8
    if expected_bytes == 0:
        raise AtkDl16Error("capture depth must contain at least one sample")

    destination = Path(output_dir)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        wire_stream = (destination / "wire.bin").open("wb")
    except OSError as exc:
        raise AtkDl16Error(f"cannot create capture output {output_dir!r}: {exc}") from exc

    device.initialize_connection()
    states = [TriggerState.NULL] * 16
    if trigger_state != TriggerState.NULL:
        assert trigger_channel is not None
        states[trigger_channel] = trigger_state
    enabled = [False] * 16
    for channel in channels:
        enabled[channel] = True
    parser = Dl16StreamParser()
    packed = {channel: bytearray() for channel in channels}
    trailer_bytes = 1 if params.is_rle else 12
    target_wire_bytes = expected_bytes + trailer_bytes
    capture_started = False
    sample_started = False
    hardware_complete = False
    try:
        device.configure_sampling_no_response(params)
        time.sleep(0.06)
        device.configure_simple_trigger_no_response(
            states, enabled=enabled, collect_type=params.collect_type
        )
        capture_started = True
        while any(len(data) < target_wire_bytes for data in packed.values()):
            chunk = backend.read_chunk(size=read_size)
            if not chunk:
                progress = ", ".join(
                    f"CH{channel}={len(data)}/{target_wire_bytes}"
                    for channel, data in packed.items()
                )
                raise AtkDl16Error(
                    f"capture stream ended before all channels completed ({progress})"
                )
            for packet in parser.feed(chunk):
                wire_stream.write(packet.raw)
                if (
                    packet.packet_type == 1
                    and packet.metadata0 in packed
                    and len(packed[packet.metadata0]) < target_wire_bytes
                ):
                    block = decode_channel_packet(packet, is_rle=params.is_rle)
                    packed[packet.metadata0].extend(block.packed_samples)
                    sample_started = True
                elif params.is_rle and sample_started and packet.packet_type == 6:
                    # In RLE mode the hardware buffer can fill before the
                    # requested depth.  The original receiver accepts the
                    # resulting shorter acquisition; type 6 marks completion.
                    hardware_complete = True
            if hardware_complete:
                break
        # The original receive thread leaves about 65 ms between the final
        # sample block and STOP, allowing the FPGA completion path to settle.
        time.sleep(0.07)
    finally:
        wire_stream.close()
        if capture_started:
            device.stop_no_response()

    samples: dict[int, bytes] = {}
    for channel, data in packed.items():
        if len(data) >= target_wire_bytes:
            samples[channel] = bytes(data[:expected_bytes])
        elif params.is_rle and hardware_complete and len(data) > trailer_bytes:
            samples[channel] = bytes(data[:-trailer_bytes])
        else:
            samples[channel] = bytes(data[:expected_bytes])
    for channel, data in samples.items():
        if len(data) != expected_bytes and not (params.is_rle and hardware_complete and data):
            raise AtkDl16Error(
                f"CH{channel} returned {len(data)} of {expected_bytes} expected packed sample bytes"
            )
    actual_depth = min(min(len(data) * 8, depth) for data in samples.values())
    shortened = actual_depth < depth
    manifest = {
        "bit_order": "lsb-first",
        "mode": "buffer" if params.is_buffer else "stream",
        "rle": params.is_rle,
        "sample_rate_hz": params.set_hz,
        "sample_index": params.sample_index,
        "requested_sample_depth": depth,
        "sample_depth": actual_depth,
        "capture_shortened_by_hardware": shortened,
        "transport_trailer_bytes_removed": trailer_bytes,
        "requested_channels": channels,
        "trigger": {
            "edge": trigger_state.name.lower(),
            "channel": trigger_channel,
            "position_percent": params.trigger_position_percent,
        },
        "channels": {
            str(channel): {
                "file": f"channel-{channel:02d}.bin",
                "packed_bytes": len(samples[channel]),
                "samples": min(len(samples[channel]) * 8, depth),
            }
            for channel in channels
        },
    }
    try:
        for channel, data in samples.items():
            (destination / f"channel-{channel:02d}.bin").write_bytes(data)
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    except OSError as exc:
        raise AtkDl16Error(f"cannot write capture output {output_dir!r}: {exc}") from exc
    return manifest


def _run_single_channel_capture(
    device: AtkDevice,
    backend: UsbBackend,
    params: SamplingParameters,
    *,
    channel: int,
    output_dir: str,
    read_size: int,
) -> dict:
    """Backward-compatible wrapper for callers using the original private helper."""

    return _run_multi_channel_capture(
        device,
        backend,
        params,
        channels=[channel],
        trigger_state=TriggerState.NULL,
        trigger_channel=None,
        output_dir=output_dir,
        read_size=read_size,
    )


def _read_binary_file(path: str, label: str) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as exc:
        raise AtkDl16Error(f"cannot read {label} file {path!r}: {exc}") from exc


def _write_firmware_plan(
    firmware: bytes,
    output_dir: str,
    *,
    target: FirmwareTarget,
    mode: McuTransportMode,
) -> dict:
    destination = Path(output_dir)
    transfer_size = 64 if mode == McuTransportMode.DIRECT_64 else 510
    enter = build_enter_update_frame(target)[:transfer_size]
    restart = build_restart_mcu_frame()[:transfer_size]
    data_frames = firmware_data_frames(firmware, target=target, mode=mode)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "enter.bin").write_bytes(enter)
        for index, frame in enumerate(data_frames):
            (destination / f"data-{index:04d}.bin").write_bytes(frame)
        (destination / "restart.bin").write_bytes(restart)
        manifest = {
            "target": target.value,
            "mode": mode.value,
            "firmware_bytes": len(firmware),
            "data_frames": len(data_frames),
            "final_delay_seconds": 1 if target == FirmwareTarget.MCU else 5,
            "ack_retries": 6,
            "ack_retry_delay_seconds": 0.05,
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        raise AtkDl16Error(f"cannot write firmware plan to {output_dir!r}: {exc}") from exc
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        run_channels: list[int] | None = None
        run_sample_index: int | None = None
        run_trigger_state = TriggerState.NULL
        run_trigger_channel: int | None = None
        stream_channels: list[int] | None = None
        stream_sample_index: int | None = None
        stream_set_time: float | None = None
        if args.command == "capture" and args.capture_command == "run":
            run_channels = _parse_capture_channels(args.channel, args.channels)
            if args.rle and not args.buffer:
                raise AtkDl16Error("capture run --rle requires --buffer")
            run_sample_index = resolve_sample_index(args.set_hz, args.sample_index)
            validate_capture_combination(args.set_hz, len(run_channels), is_buffer=args.buffer)
            if args.trigger == "rising":
                run_trigger_state = TriggerState.RISING
            elif args.trigger == "falling":
                run_trigger_state = TriggerState.FALLING
            run_trigger_channel = args.trigger_channel
            if run_trigger_state != TriggerState.NULL:
                run_trigger_channel = run_trigger_channel if run_trigger_channel is not None else run_channels[0]
                if run_trigger_channel not in run_channels:
                    raise AtkDl16Error("trigger channel must be one of the captured channels")
            elif run_trigger_channel is not None:
                raise AtkDl16Error("--trigger-channel requires --trigger rising or falling")
        if args.command == "capture" and args.capture_command == "stream":
            stream_channels = _parse_capture_channels(args.channel, args.channels)
            stream_sample_index = resolve_sample_index(args.set_hz, args.sample_index)
            validate_capture_combination(args.set_hz, len(stream_channels), is_buffer=False)
            if args.duration is not None:
                if not math.isfinite(args.duration) or args.duration <= 0:
                    raise AtkDl16Error("stream duration must be a positive finite number")
                stream_set_time = args.duration * 1000.0
            else:
                stream_set_time = ((1 << 40) - 1) // (args.set_hz // 1_000)
        if args.command == "capture":
            if args.capture_command == "parse":
                for index, packet in enumerate(_parse_capture_file(args.input)):
                    _print_packet_summary(index, packet)
                return 0
            if args.capture_command == "decode":
                print(json.dumps(_decode_capture_file(args.input, args.output_dir, is_rle=args.rle), sort_keys=True))
                return 0
            if args.capture_command == "export":
                result = export_capture(args.input_dir, args.output, format=args.format)
                print(json.dumps({
                    "format": result.format,
                    "output": str(result.output),
                    "channels": list(result.channels),
                    "samples": result.samples,
                    "rows": result.rows,
                }, sort_keys=True))
                return 0
            if args.capture_command == "uart":
                result = decode_uart_capture(
                    args.input_dir, channel=args.channel, baud=args.baud,
                    data_bits=args.data_bits, parity=args.parity,
                    stop_bits=args.stop_bits, inverted=args.inverted,
                )
                _emit_protocol_decode(result, args.output)
                return 0
            if args.capture_command == "i2c":
                result = decode_i2c_capture(
                    args.input_dir, scl_channel=args.scl, sda_channel=args.sda
                )
                _emit_protocol_decode(result, args.output)
                return 0
            if args.capture_command == "spi":
                result = decode_spi_capture(
                    args.input_dir, clock_channel=args.clock,
                    mosi_channel=args.mosi, miso_channel=args.miso,
                    cs_channel=args.cs, mode=args.mode,
                    bits_per_word=args.bits_per_word, bit_order=args.bit_order,
                )
                _emit_protocol_decode(result, args.output)
                return 0
            if args.capture_command == "run" and args.dry_run:
                raise AtkDl16Error("capture run requires connected hardware; use capture configure for dry-run")
            if args.capture_command == "stream" and args.dry_run:
                raise AtkDl16Error("capture stream requires connected hardware")

        if args.command == "firmware" and args.firmware_command == "plan":
            target = FirmwareTarget(args.target)
            mode = McuTransportMode(args.mode)
            manifest = _write_firmware_plan(
                _read_binary_file(args.file, "firmware"),
                args.output_dir,
                target=target,
                mode=mode,
            )
            print(json.dumps(manifest, sort_keys=True))
            return 0

        if args.command == "session" and args.dry_run:
            raise AtkDl16Error("session requires connected hardware")

        if args.command == "firmware" and args.firmware_command == "flash":
            if not args.i_understand_this_can_brick:
                raise AtkDl16Error("firmware flash requires --i-understand-this-can-brick")
            if args.dry_run:
                raise AtkDl16Error("use firmware plan for offline frame generation; flash cannot use --dry-run")
        if args.command == "firmware" and args.firmware_command == "enter-bootloader":
            if not args.i_understand_this_can_brick:
                raise AtkDl16Error("enter-bootloader requires --i-understand-this-can-brick")
            if args.dry_run:
                raise AtkDl16Error("enter-bootloader cannot use --dry-run")

        vid_pid = parse_usb_id(args.vid_pid) if args.vid_pid else None
        backend = create_backend(args.dry_run, vid_pid, args.timeout_ms)
        device = AtkDevice(backend)

        if args.command == "session":
            if args.commands == "-":
                return run_json_session(Dl16Session(backend, device=device), sys.stdin, sys.stdout)
            try:
                with Path(args.commands).open(encoding="utf-8") as source:
                    return run_json_session(Dl16Session(backend, device=device), source, sys.stdout)
            except OSError as exc:
                raise AtkDl16Error(f"cannot read session commands {args.commands!r}: {exc}") from exc

        if args.command == "list":
            for info in backend.list_devices():
                print(f"{info.usb_id} path={info.path} speed={info.speed}")
            return 0

        if (
            not args.dry_run
            and args.command in {"info", "stop", "pwm"}
            and callable(getattr(backend, "recover_ffcc_link", None))
        ):
            device.initialize_connection()

        if args.command == "info":
            if args.dry_run:
                _print_frame("GET_DEVICE_DATA", device.get_device_data_frame())
            else:
                _print_response("GET_DEVICE_DATA", device.get_device_data())
            return 0

        if args.command == "stop":
            frame = device.stop(channel=args.channel)
            if args.dry_run:
                _print_frame("STOP", frame)
            else:
                _print_response("STOP", device.last_response)
            return 0

        if args.command == "pwm" and args.pwm_command == "start":
            frame = device.pwm_start(args.channel, args.freq, args.duty)
            if args.dry_run:
                _print_frame("PWM_START", frame)
            else:
                _print_response("PWM_START", device.last_response)
            return 0

        if args.command == "pwm" and args.pwm_command == "stop":
            frame = device.pwm_stop(args.channel)
            if args.dry_run:
                _print_frame("PWM_STOP", frame)
            else:
                _print_response("PWM_STOP", device.last_response)
            return 0

        if args.command == "trigger" and args.trigger_command == "simple":
            frame = device.configure_simple_trigger(
                parse_trigger_states(args.states),
                enabled=_parse_enabled(args.enabled),
                collect_type=args.collect_type,
                channel_offset=args.channel_offset,
            )
            if args.dry_run:
                _print_frame("SIMPLE_TRIGGER", frame)
            else:
                _print_response("SIMPLE_TRIGGER", device.last_response)
            return 0

        if args.command == "trigger" and args.trigger_command == "stage":
            data = _load_json_object(args.file)
            raw_stages = data.get("stages")
            if not isinstance(raw_stages, list) or not raw_stages:
                raise AtkDl16Error("stage trigger JSON requires a non-empty stages array")
            stages = []
            for item in raw_stages:
                if not isinstance(item, dict):
                    raise AtkDl16Error("each stage must be an object")
                stages.append(StageCondition(
                    _states_from_json(item.get("states")),
                    int(item.get("counter", 0)),
                    bool(item.get("contiguous", True)),
                ))
            frame = device.configure_stage_trigger(
                stages,
                trigger_level=int(data.get("triggerLevel", 0)),
                enabled=data.get("enabled"),
                channel_offset=int(data.get("channelOffset", 0)),
            )
            if args.dry_run:
                _print_frame("STAGE_TRIGGER", frame)
            else:
                _print_response("STAGE_TRIGGER", device.last_response)
            return 0

        if args.command == "trigger" and args.trigger_command == "serial":
            data = _load_json_object(args.file)
            config = SerialTriggerConfig(
                value_channel=int(data["valueChannel"]),
                value_width=int(data["valueWidth"]),
                value_data=int(data["valueData"]),
                time_channel=int(data["timeChannel"]),
                time_edge=int(data["timeEdge"]),
                start_states=_states_from_json(data.get("startStates")),
                stop_states=_states_from_json(data.get("stopStates")),
                channel_offset=int(data.get("channelOffset", 0)),
                enabled=data.get("enabled"),
            )
            frame = device.configure_serial_trigger(config)
            if args.dry_run:
                _print_frame("SERIAL_TRIGGER", frame)
            else:
                _print_response("SERIAL_TRIGGER", device.last_response)
            return 0

        if args.command == "capture" and args.capture_command == "configure":
            params = SamplingParameters(
                set_time=args.set_time,
                set_hz=args.set_hz,
                trigger_position_percent=args.trigger_position,
                threshold_level=args.threshold,
                sample_index=args.sample_index,
                is_rle=args.rle,
                is_buffer=args.buffer,
                collect_type=args.collect_type,
            )
            frame = device.configure_sampling(params)
            if args.dry_run:
                _print_frame("PARAMETER_SETTING", frame)
            else:
                _print_response("PARAMETER_SETTING", device.last_response)
            return 0

        if args.command == "capture" and args.capture_command == "run":
            params = SamplingParameters(
                set_time=args.set_time,
                set_hz=args.set_hz,
                trigger_position_percent=args.trigger_position,
                threshold_level=args.threshold,
                sample_index=run_sample_index,
                is_rle=args.rle,
                is_buffer=args.buffer,
                collect_type=1,
            )
            assert run_channels is not None
            assert run_sample_index is not None
            manifest = _run_multi_channel_capture(
                device,
                backend,
                params,
                channels=run_channels,
                trigger_state=run_trigger_state,
                trigger_channel=run_trigger_channel,
                output_dir=args.output_dir,
                read_size=args.read_size,
            )
            print(json.dumps(manifest, sort_keys=True))
            return 0

        if args.command == "capture" and args.capture_command == "stream":
            assert stream_channels is not None
            assert stream_sample_index is not None
            assert stream_set_time is not None
            params = SamplingParameters(
                set_time=stream_set_time,
                set_hz=args.set_hz,
                trigger_position_percent=0,
                threshold_level=args.threshold,
                sample_index=stream_sample_index,
                collect_type=1,
            )
            manifest = stream_capture_to_disk(
                device, backend, params,
                channels=stream_channels,
                output_dir=args.output_dir,
                read_size=args.read_size,
                sleep_fn=time.sleep,
            )
            print(json.dumps(manifest, sort_keys=True))
            return 0

        if args.command == "capture" and args.capture_command == "read":
            packets = _read_capture_packets(
                backend,
                packet_count=args.packets,
                output=args.output,
                read_size=args.read_size,
            )
            for index, packet in enumerate(packets):
                _print_packet_summary(index, packet)
            return 0

        if args.command == "firmware" and args.firmware_command == "flash":
            result = flash_firmware(
                backend,
                _read_binary_file(args.file, "firmware"),
                target=FirmwareTarget(args.target),
                mode=McuTransportMode(args.mode),
            )
            print(json.dumps({
                "target": result.target.value,
                "mode": result.mode.value,
                "firmware_bytes": result.firmware_bytes,
                "data_frames": result.data_frames,
            }, sort_keys=True))
            return 0

        if args.command == "firmware" and args.firmware_command == "version":
            mode = McuTransportMode(args.mode)
            size = 64 if mode == McuTransportMode.DIRECT_64 else 510
            backend.write_chunk(build_get_mcu_version_frame()[:size])
            _print_response("MCU_VERSION", backend.read_chunk(size=size))
            return 0

        if args.command == "firmware" and args.firmware_command == "enter-bootloader":
            mode = McuTransportMode(args.mode)
            size = 64 if mode == McuTransportMode.DIRECT_64 else 510
            backend.write_chunk(build_enter_bootloader_frame()[:size])
            print("enter-bootloader sent; wait for the USB device to re-enumerate before firmware flash")
            return 0

        if args.command == "raw":
            payload = parse_hex_payload(args.payload_hex)
            label, frame = _send_raw_command(device, args.raw_command, payload)
            if args.dry_run:
                _print_frame(label, frame)
            else:
                _print_response(label, device.last_response)
            return 0

        parser.error(f"unsupported command combination: {args}")
        return 2
    except AtkDl16Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
