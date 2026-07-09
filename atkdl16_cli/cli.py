from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .device import AtkDevice
from .errors import AtkDl16Error
from .protocol import SUPPORTED_USB_IDS, parse_hex_payload
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
