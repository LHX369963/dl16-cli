from __future__ import annotations

import contextlib
import json
import math
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .acquisition import capture_to_disk
from .arguments import build_parser
from .capture import (
    Dl16CapturePacket,
    Dl16StreamParser,
    SamplingParameters,
    decode_channel_packet,
    interpret_capture_packet,
)
from .decoders import decode_i2c_capture, decode_spi_capture, decode_uart_capture
from .device import Dl16Device
from .errors import Dl16Error
from .export import export_capture
from .filtering import filter_glitches
from .measure import measure_pwm_capture
from .protocol import SUPPORTED_USB_IDS, parse_hex_payload
from .pwm_verify import _parse_pwm_verify_spec, _verify_pwm_pair
from .sampling import resolve_sample_index, validate_capture_combination
from .search import search_capture
from .session import Dl16Session, run_json_session
from .sigrok import decode_with_sigrok, list_sigrok_decoders, show_sigrok_decoder
from .streaming import stream_capture_to_disk
from .trigger import (
    SerialTriggerConfig,
    StageCondition,
    TriggerState,
    parse_trigger_state,
    parse_trigger_states,
)
from .usb import DeviceInfo, DryRunBackend, PyUsbBackend, UsbBackend, parse_usb_id


def _print_frame(label: str, frame: bytes) -> None:
    print(f"{label} frame: {frame.hex()}")


def _print_response(label: str, response: bytes) -> None:
    print(f"{label} response: {response.hex()}")


def _print_device_info(response: bytes, *, include_raw: bool = False) -> None:
    packets = Dl16StreamParser().feed(response)
    info = next((interpret_capture_packet(packet) for packet in packets if packet.packet_type == 2), None)
    if info is None:
        info = {"response_bytes": len(response), "response_prefix_hex": response[:64].hex()}
    if include_raw:
        info["raw_response_hex"] = response.hex()
    print(json.dumps(info, sort_keys=True))


def _dry_backend() -> DryRunBackend:
    devices = [DeviceInfo(vid=item.vid, pid=item.pid, path="supported-id", speed="unknown") for item in SUPPORTED_USB_IDS]
    return DryRunBackend(devices=devices)


def create_backend(dry_run: bool, vid_pid: tuple[int, int] | None, timeout_ms: int) -> UsbBackend:
    if timeout_ms <= 0:
        raise Dl16Error(f"timeout-ms must be positive, got {timeout_ms}")
    if dry_run:
        return _dry_backend()
    return PyUsbBackend(vid_pid=vid_pid, timeout_ms=timeout_ms)


def _send_raw_command(device: Dl16Device, raw_command: str, payload: bytes) -> tuple[str, bytes]:
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
        raise Dl16Error("enabled mask must contain only comma-separated 0/1 values")
    return [item == "1" for item in values]


def _parse_capture_channels(single: int | None, multiple: str | None) -> list[int]:
    if multiple is None:
        channels = [single] if single is not None else []
    else:
        raw_values = [item.strip() for item in multiple.split(",")]
        if not raw_values or any(not item for item in raw_values):
            raise Dl16Error("channels must be a non-empty comma-separated list")
        try:
            channels = [int(item, 10) for item in raw_values]
        except ValueError as exc:
            raise Dl16Error("channels must contain decimal channel numbers") from exc
    if not channels:
        raise Dl16Error("at least one capture channel is required")
    if len(set(channels)) != len(channels):
        raise Dl16Error("duplicate channel in capture channel list")
    invalid = [channel for channel in channels if not 0 <= channel <= 15]
    if invalid:
        raise Dl16Error(f"channel must be in range 0..15, got {invalid[0]}")
    return sorted(channels)


def _parse_trigger_conditions(text: str, channels: Sequence[int]) -> dict[int, TriggerState]:
    result: dict[int, TriggerState] = {}
    for item in text.split(","):
        parts = item.split("=", 1)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise Dl16Error("trigger-states must use CH=STATE comma-separated syntax")
        try:
            channel = int(parts[0], 10)
        except ValueError as exc:
            raise Dl16Error(f"invalid trigger channel: {parts[0]!r}") from exc
        if channel in result:
            raise Dl16Error(f"duplicate trigger channel: {channel}")
        if channel not in channels:
            raise Dl16Error(f"trigger channel {channel} must be one of the captured channels")
        result[channel] = parse_trigger_state(parts[1])
    if not result or all(state == TriggerState.NULL for state in result.values()):
        raise Dl16Error("trigger-states requires at least one active condition")
    return result


def _load_json_object(path: str) -> dict:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise Dl16Error(f"cannot read trigger JSON {path!r}: {exc}") from exc
    if not isinstance(value, dict):
        raise Dl16Error("trigger JSON root must be an object")
    return value


def _states_from_json(values: object):
    if not isinstance(values, list) or not values:
        raise Dl16Error("trigger state field must be a non-empty array")
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
        raise Dl16Error(f"cannot read capture file {path!r}: {exc}") from exc
    return Dl16StreamParser().feed(data)


def _read_capture_packets(
    backend: UsbBackend, *, packet_count: int, output: str, read_size: int | None
) -> list[Dl16CapturePacket]:
    if packet_count <= 0:
        raise Dl16Error(f"packets must be positive, got {packet_count}")
    if read_size is not None and read_size <= 0:
        raise Dl16Error(f"read-size must be positive, got {read_size}")
    parser = Dl16StreamParser()
    packets: list[Dl16CapturePacket] = []
    try:
        stream = Path(output).open("wb")  # noqa: SIM115 - translated before context use
    except OSError as exc:
        raise Dl16Error(f"cannot open capture output {output!r}: {exc}") from exc
    with stream:
        while len(packets) < packet_count:
            chunk = backend.read_chunk(size=read_size)
            if not chunk:
                raise Dl16Error(
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
        raise Dl16Error("capture contains no type-1 channel sample packets")
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
        raise Dl16Error(f"cannot write decoded capture to {output_dir!r}: {exc}") from exc
    return manifest


def _emit_protocol_decode(result: dict, output: str | None) -> None:
    if output is not None:
        try:
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        except OSError as exc:
            raise Dl16Error(f"cannot write protocol decode {output!r}: {exc}") from exc
    print(json.dumps(result, sort_keys=True))


def _run_multi_channel_capture(
    device: Dl16Device,
    backend: UsbBackend,
    params: SamplingParameters,
    *,
    channels: Sequence[int],
    trigger_state: TriggerState = TriggerState.NULL,
    trigger_channel: int | None = None,
    output_dir: str,
    read_size: int,
) -> dict:
    return capture_to_disk(
        device,
        backend,
        params,
        channels=channels,
        trigger_state=trigger_state,
        trigger_channel=trigger_channel,
        output_dir=output_dir,
        read_size=read_size,
        sleep_fn=time.sleep,
        overwrite=True,
    )


def _run_single_channel_capture(
    device: Dl16Device,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    backend: UsbBackend | None = None
    try:
        run_channels: list[int] | None = None
        run_sample_index: int | None = None
        run_trigger_state = TriggerState.NULL
        run_trigger_channel: int | None = None
        run_trigger_states: dict[int, TriggerState] | None = None
        stream_channels: list[int] | None = None
        stream_sample_index: int | None = None
        stream_set_time: float | None = None
        if args.command == "capture" and args.capture_command == "run":
            run_channels = _parse_capture_channels(args.channel, args.channels)
            if args.rle and not args.buffer:
                raise Dl16Error("capture run --rle requires --buffer")
            run_sample_index = resolve_sample_index(args.set_hz, args.sample_index)
            validate_capture_combination(args.set_hz, len(run_channels), is_buffer=args.buffer)
            trigger_map = {
                "none": TriggerState.NULL,
                "rising": TriggerState.RISING,
                "high": TriggerState.HIGH,
                "falling": TriggerState.FALLING,
                "low": TriggerState.LOW,
                "either": TriggerState.DOUBLE,
            }
            run_trigger_state = trigger_map[args.trigger]
            if args.trigger_states is not None:
                if args.trigger != "none" or args.trigger_channel is not None:
                    raise Dl16Error("--trigger-states cannot be combined with --trigger or --trigger-channel")
                run_trigger_states = _parse_trigger_conditions(args.trigger_states, run_channels)
            run_trigger_channel = args.trigger_channel
            if run_trigger_states is not None:
                run_trigger_channel = None
            elif run_trigger_state != TriggerState.NULL:
                run_trigger_channel = run_trigger_channel if run_trigger_channel is not None else run_channels[0]
                if run_trigger_channel not in run_channels:
                    raise Dl16Error("trigger channel must be one of the captured channels")
            elif run_trigger_channel is not None:
                raise Dl16Error("--trigger-channel requires --trigger rising or falling")
        if args.command == "capture" and args.capture_command == "stream":
            stream_channels = _parse_capture_channels(args.channel, args.channels)
            stream_sample_index = resolve_sample_index(args.set_hz, args.sample_index)
            validate_capture_combination(args.set_hz, len(stream_channels), is_buffer=False)
            if args.duration is not None:
                if not math.isfinite(args.duration) or args.duration <= 0:
                    raise Dl16Error("stream duration must be a positive finite number")
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
            if args.capture_command == "measure":
                result = measure_pwm_capture(args.input_dir, channel=args.channel)
                if args.json:
                    print(json.dumps(result, sort_keys=True))
                else:
                    print(f"{result['frequency_hz']} {result['duty_percent']}")
                return 0
            if args.capture_command == "sigrok":
                if args.list:
                    output = list_sigrok_decoders()
                elif args.show is not None:
                    output = show_sigrok_decoder(args.show)
                else:
                    if args.input_dir is None or args.decoder is None:
                        raise Dl16Error("capture sigrok requires --input-dir and --decoder")
                    output = decode_with_sigrok(
                        args.input_dir, decoder=args.decoder, channels=args.channel,
                        options=args.option, annotations=args.annotations,
                    )
                if args.output is not None:
                    try:
                        destination = Path(args.output)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_text(output)
                    except OSError as exc:
                        raise Dl16Error(f"cannot write sigrok output {args.output!r}: {exc}") from exc
                else:
                    print(output, end="" if output.endswith("\n") else "\n")
                return 0
            if args.capture_command == "filter":
                filter_channels = (
                    _parse_capture_channels(None, args.channels) if args.channels is not None else None
                )
                result = filter_glitches(
                    args.input_dir, args.output_dir, maximum_samples=args.max_samples,
                    channels=filter_channels, overwrite=args.force,
                )
                print(json.dumps(result["glitch_filter"], sort_keys=True))
                return 0
            if args.capture_command == "search":
                result = search_capture(
                    args.input_dir,
                    conditions=_parse_trigger_conditions(args.conditions, range(16)),
                    start_sample=args.start_sample,
                    end_sample=args.end_sample,
                    limit=args.limit,
                )
                encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
                if args.output is not None:
                    try:
                        destination = Path(args.output)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_text(encoded)
                    except OSError as exc:
                        raise Dl16Error(f"cannot write search output {args.output!r}: {exc}") from exc
                else:
                    print(encoded, end="")
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
                raise Dl16Error("capture run requires connected hardware; use capture configure for dry-run")
            if args.capture_command == "stream" and args.dry_run:
                raise Dl16Error("capture stream requires connected hardware")

        if args.command == "session" and args.dry_run:
            raise Dl16Error("session requires connected hardware")

        vid_pid = parse_usb_id(args.vid_pid) if args.vid_pid else None
        backend = create_backend(args.dry_run, vid_pid, args.timeout_ms)
        device = Dl16Device(backend)

        if args.command == "session":
            if args.commands == "-":
                return run_json_session(Dl16Session(backend, device=device), sys.stdin, sys.stdout)
            try:
                with Path(args.commands).open(encoding="utf-8") as source:
                    return run_json_session(Dl16Session(backend, device=device), source, sys.stdout)
            except OSError as exc:
                raise Dl16Error(f"cannot read session commands {args.commands!r}: {exc}") from exc

        if args.command == "list":
            for info in backend.list_devices():
                print(f"{info.usb_id} path={info.path} speed={info.speed}")
            return 0

        if args.command == "pwm" and args.pwm_command == "verify":
            if args.dry_run:
                raise Dl16Error("pwm verify requires connected hardware")
            requests: list[tuple[int, int, int, float]] = []
            if args.pwm0 is not None:
                if args.input0 is None:
                    raise Dl16Error("--pwm0 requires --input0")
                frequency, duty = _parse_pwm_verify_spec(args.pwm0)
                requests.append((0, args.input0, frequency, duty))
            if args.pwm1 is not None:
                if args.input1 is None:
                    raise Dl16Error("--pwm1 requires --input1")
                frequency, duty = _parse_pwm_verify_spec(args.pwm1)
                requests.append((1, args.input1, frequency, duty))
            if not requests:
                raise Dl16Error("pwm verify requires --pwm0 and/or --pwm1")
            inputs = [input_channel for _, input_channel, _, _ in requests]
            if any(not 0 <= channel <= 15 for channel in inputs):
                raise Dl16Error("PWM verify inputs must be in range 0..15")
            if len(set(inputs)) != len(inputs):
                raise Dl16Error("PWM verify inputs must be distinct")
            results = _verify_pwm_pair(device, backend, requests)
            for result in results:
                print(f"{result['frequency_hz']} {result['duty_percent']}")
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
                _print_device_info(device.get_device_data(), include_raw=args.raw)
            return 0

        if args.command == "stop":
            frame = device.stop(channel=args.channel)
            if args.dry_run:
                _print_frame("STOP", frame)
            return 0

        if args.command == "pwm" and args.pwm_command == "start":
            frame = device.pwm_start(args.channel, args.freq, args.duty)
            if args.dry_run:
                _print_frame("PWM_START", frame)
            return 0

        if args.command == "pwm" and args.pwm_command == "stop":
            frame = device.pwm_stop(args.channel)
            if args.dry_run:
                _print_frame("PWM_STOP", frame)
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
            return 0

        if args.command == "trigger" and args.trigger_command == "stage":
            data = _load_json_object(args.file)
            raw_stages = data.get("stages")
            if not isinstance(raw_stages, list) or not raw_stages:
                raise Dl16Error("stage trigger JSON requires a non-empty stages array")
            stages = []
            for item in raw_stages:
                if not isinstance(item, dict):
                    raise Dl16Error("each stage must be an object")
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
            capture_to_disk(
                device,
                backend,
                params,
                channels=run_channels,
                trigger_state=run_trigger_state,
                trigger_channel=run_trigger_channel,
                trigger_states=run_trigger_states,
                output_dir=args.output_dir,
                read_size=args.read_size,
                sleep_fn=time.sleep,
                overwrite=args.force,
                trigger_timeout_seconds=args.trigger_timeout,
            )
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
            stream_capture_to_disk(
                device, backend, params,
                channels=stream_channels,
                output_dir=args.output_dir,
                read_size=args.read_size,
                sleep_fn=time.sleep,
                overwrite=args.force,
            )
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
    except Dl16Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    finally:
        close = getattr(backend, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):
                close()


if __name__ == "__main__":
    raise SystemExit(main())
