from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Sequence

from .capture import SamplingParameters
from .device import AtkDevice
from .errors import AtkDl16Error
from .protocol import SUPPORTED_USB_IDS, parse_hex_payload
from .trigger import SerialTriggerConfig, StageCondition, parse_trigger_states
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    vid_pid = parse_usb_id(args.vid_pid) if args.vid_pid else None
    backend = create_backend(args.dry_run, vid_pid, args.timeout_ms)
    device = AtkDevice(backend)

    try:
        if args.command == "list":
            for info in backend.list_devices():
                print(f"{info.usb_id} path={info.path} speed={info.speed}")
            return 0

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
