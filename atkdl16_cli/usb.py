from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import ProtocolError, UsbBackendError
from .protocol import SUPPORTED_USB_IDS


@dataclass(frozen=True)
class DeviceInfo:
    vid: int
    pid: int
    bus: int | None = None
    address: int | None = None
    path: str | None = None
    speed: str | None = None

    @property
    def usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"


class PyUsbUnavailableError(UsbBackendError):
    """Raised when pyusb is required but unavailable."""


def parse_usb_id(text: str) -> tuple[int, int]:
    parts = text.split(":")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ProtocolError(f"USB ID must be VID:PID hex, got {text!r}")
    try:
        vid = int(parts[0], 16)
        pid = int(parts[1], 16)
    except ValueError as exc:
        raise ProtocolError(f"USB ID must be VID:PID hex, got {text!r}") from exc
    if not 0 <= vid <= 0xFFFF or not 0 <= pid <= 0xFFFF:
        raise ProtocolError(f"USB ID components must be 16-bit values, got {text!r}")
    return vid, pid


def is_supported_usb_id(vid: int, pid: int) -> bool:
    return any(item.vid == vid and item.pid == pid for item in SUPPORTED_USB_IDS)


class UsbBackend(Protocol):
    def list_devices(self) -> list[DeviceInfo]:
        raise NotImplementedError

    def send_frame(self, frame: bytes) -> bytes:
        raise NotImplementedError


class DryRunBackend:
    def __init__(self, devices: list[DeviceInfo] | None = None) -> None:
        self._devices = list(devices or [])
        self.sent_frames: list[bytes] = []

    def list_devices(self) -> list[DeviceInfo]:
        return list(self._devices)

    def send_frame(self, frame: bytes) -> bytes:
        self.sent_frames.append(bytes(frame))
        return b""
