from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .device import AtkDevice
from .errors import AtkDl16Error
from .protocol import SUPPORTED_USB_IDS
from .usb import DeviceInfo, DryRunBackend


def _print_frame(label: str, frame: bytes) -> None:
    print(f"{label} frame: {frame.hex()}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atkdl16")
    parser.add_argument("--dry-run", action="store_true", help="print frames without accessing USB hardware")
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

    return parser


def _dry_backend() -> DryRunBackend:
    devices = [DeviceInfo(vid=item.vid, pid=item.pid, path="supported-id", speed="unknown") for item in SUPPORTED_USB_IDS]
    return DryRunBackend(devices=devices)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.dry_run:
        parser.error("only --dry-run is available in this implementation plan")

    backend = _dry_backend()
    device = AtkDevice(backend)

    try:
        if args.command == "list":
            for info in backend.list_devices():
                print(f"{info.usb_id} path={info.path} speed={info.speed}")
            return 0

        if args.command == "info":
            _print_frame("GET_DEVICE_DATA", device.get_device_data_frame())
            return 0

        if args.command == "stop":
            _print_frame("STOP", device.stop(channel=args.channel))
            return 0

        if args.command == "pwm" and args.pwm_command == "start":
            _print_frame("PWM_START", device.pwm_start(args.channel, args.freq, args.duty))
            return 0

        if args.command == "pwm" and args.pwm_command == "stop":
            _print_frame("PWM_STOP", device.pwm_stop(args.channel))
            return 0

        parser.error(f"unsupported command combination: {args}")
        return 2
    except AtkDl16Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
