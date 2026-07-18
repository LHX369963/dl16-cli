from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import time

from .errors import ProtocolError, UsbBackendError
from .protocol import SUPPORTED_USB_IDS

NORMAL_COMMAND_TRANSFER_SIZE = 0x800


def _usb_error_message(action: str, exc: Exception) -> str:
    text = str(exc)
    errno = getattr(exc, "errno", None)
    if errno in {1, 13} or "access" in text.lower() or "permission" in text.lower():
        return (
            f"USB {action} failed: permission denied. Install udev/99-atk-dl16.rules, "
            f"reload udev rules, and reconnect the DL16 ({text})"
        )
    return f"USB {action} failed: {text}"


def _require_ffcc_block_size(data: bytes) -> bytes:
    data = bytes(data)
    if len(data) % NORMAL_COMMAND_TRANSFER_SIZE:
        raise ProtocolError(
            f"FFCC transport data must be a multiple of {NORMAL_COMMAND_TRANSFER_SIZE} bytes, "
            f"got {len(data)}"
        )
    return data


def encode_ffcc_transport(data: bytes) -> bytes:
    data = _require_ffcc_block_size(data)
    encoded = bytearray(len(data))
    for block_start in range(0, len(data), NORMAL_COMMAND_TRANSFER_SIZE):
        block = data[block_start : block_start + NORMAL_COMMAND_TRANSFER_SIZE]
        words = [block[offset : offset + 2] for offset in range(0, len(block), 2)]
        encoded[block_start : block_start + NORMAL_COMMAND_TRANSFER_SIZE] = b"".join(
            word for lane in range(4) for word in words[lane::4]
        )
    return bytes(encoded)


def decode_ffcc_transport(data: bytes) -> bytes:
    data = _require_ffcc_block_size(data)
    decoded = bytearray(len(data))
    words_per_lane = NORMAL_COMMAND_TRANSFER_SIZE // 2 // 4
    lane_size = words_per_lane * 2
    for block_start in range(0, len(data), NORMAL_COMMAND_TRANSFER_SIZE):
        block = data[block_start : block_start + NORMAL_COMMAND_TRANSFER_SIZE]
        lanes = [
            [
                block[lane_start + offset : lane_start + offset + 2]
                for offset in range(0, lane_size, 2)
            ]
            for lane_start in range(0, NORMAL_COMMAND_TRANSFER_SIZE, lane_size)
        ]
        words = [lanes[index % 4][index // 4] for index in range(words_per_lane * 4)]
        decoded[block_start : block_start + NORMAL_COMMAND_TRANSFER_SIZE] = b"".join(words)
    return bytes(decoded)


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

    def write_frame(self, frame: bytes) -> int:
        raise NotImplementedError

    def read_chunk(self, size: int | None = None, timeout_ms: int | None = None) -> bytes:
        raise NotImplementedError

    def write_chunk(self, data: bytes, timeout_ms: int | None = None) -> int:
        raise NotImplementedError


class DryRunBackend:
    def __init__(
        self,
        devices: list[DeviceInfo] | None = None,
        read_chunks: list[bytes] | None = None,
    ) -> None:
        self._devices = list(devices or [])
        self._read_chunks = [bytes(chunk) for chunk in (read_chunks or [])]
        self.sent_frames: list[bytes] = []
        self.written_chunks: list[bytes] = []

    def list_devices(self) -> list[DeviceInfo]:
        return list(self._devices)

    def send_frame(self, frame: bytes) -> bytes:
        self.sent_frames.append(bytes(frame))
        return b""

    def write_frame(self, frame: bytes) -> int:
        frame = bytes(frame)
        self.sent_frames.append(frame)
        return len(frame)

    def read_chunk(self, size: int | None = None, timeout_ms: int | None = None) -> bytes:
        del size, timeout_ms
        return self._read_chunks.pop(0) if self._read_chunks else b""

    def write_chunk(self, data: bytes, timeout_ms: int | None = None) -> int:
        del timeout_ms
        chunk = bytes(data)
        self.written_chunks.append(chunk)
        return len(chunk)


class PyUsbBackend:
    def __init__(
        self,
        device: Any | None = None,
        usb_core: Any | None = None,
        usb_util: Any | None = None,
        timeout_ms: int = 1000,
        vid_pid: tuple[int, int] | None = None,
    ) -> None:
        self.device = device
        self.timeout_ms = timeout_ms
        self.vid_pid = vid_pid
        self.usb_core = usb_core
        self.usb_util = usb_util
        self.write_endpoint: Any | None = None
        self.read_endpoint: Any | None = None
        self._claimed = False
        if self.usb_core is None or self.usb_util is None:
            try:
                import usb.core  # type: ignore[import-not-found]
                import usb.util  # type: ignore[import-not-found]
            except ImportError as exc:
                raise PyUsbUnavailableError("pyusb is not installed; install with python3 -m pip install -e '.[usb]'") from exc
            self.usb_core = self.usb_core or usb.core
            self.usb_util = self.usb_util or usb.util

    def list_devices(self) -> list[DeviceInfo]:
        devices = []
        try:
            for item in self.usb_core.find(find_all=True):
                vid = int(getattr(item, "idVendor"))
                pid = int(getattr(item, "idProduct"))
                if self.vid_pid is not None and (vid, pid) != self.vid_pid:
                    continue
                if is_supported_usb_id(vid, pid):
                    devices.append(
                        DeviceInfo(
                            vid=vid,
                            pid=pid,
                            bus=getattr(item, "bus", None),
                            address=getattr(item, "address", None),
                            path=self._device_path(item),
                            speed=str(getattr(item, "speed", "unknown")),
                        )
                    )
        except Exception as exc:
            raise UsbBackendError(_usb_error_message("enumeration", exc)) from exc
        return devices

    def open(self) -> None:
        try:
            if self.device is None:
                self.device = self._find_device()
            if self.device is None:
                raise UsbBackendError("no supported ATK DL16 device found")
            self._detach_kernel_driver(0)
            self.usb_util.claim_interface(self.device, 0)
            self._claimed = True
            self.write_endpoint, self.read_endpoint = self._find_endpoints(self.device)
            if self.write_endpoint is None:
                raise UsbBackendError("could not find USB OUT endpoint")
        except UsbBackendError:
            self._release_after_open_failure()
            raise
        except Exception as exc:
            self._release_after_open_failure()
            raise UsbBackendError(_usb_error_message("open", exc)) from exc

    def _release_after_open_failure(self) -> None:
        if self.device is not None and self._claimed:
            try:
                self.usb_util.release_interface(self.device, 0)
            except Exception:
                pass
        self._claimed = False
        self.write_endpoint = None
        self.read_endpoint = None

    def recover_ffcc_link(self, timeout_seconds: float = 3.0) -> None:
        """Recover an already-plugged FFCC device without a physical hotplug."""

        if self._claimed:
            self.close()
        if self.device is None:
            self.device = self._find_device()
        if self.device is None:
            raise UsbBackendError("no supported ATK DL16 device found")
        if (int(self.device.idVendor), int(self.device.idProduct)) != (0x1A86, 0xFFCC):
            self.open()
            return

        try:
            self.device.clear_halt(0x02)
            self.device.clear_halt(0x81)
            self.device.reset()
        except Exception as exc:
            raise UsbBackendError(_usb_error_message("FFCC link reset", exc)) from exc
        if hasattr(self.usb_util, "dispose_resources"):
            self.usb_util.dispose_resources(self.device)
        self.device = None
        self.write_endpoint = None
        self.read_endpoint = None
        self._claimed = False

        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            self.device = self._find_device()
            if self.device is not None:
                try:
                    self.open()
                    return
                except Exception as exc:
                    last_error = exc
                    if hasattr(self.usb_util, "dispose_resources"):
                        self.usb_util.dispose_resources(self.device)
                    self.device = None
                    self.write_endpoint = None
                    self.read_endpoint = None
                    self._claimed = False
            time.sleep(0.005)
        raise UsbBackendError(f"FFCC device did not become claimable after reset: {last_error}")

    def close(self) -> None:
        error: Exception | None = None
        if self.device is not None and self._claimed:
            try:
                self.usb_util.release_interface(self.device, 0)
            except Exception as exc:
                error = exc
            finally:
                self._claimed = False
        if self.device is not None and hasattr(self.usb_util, "dispose_resources"):
            try:
                self.usb_util.dispose_resources(self.device)
            except Exception as exc:
                error = error or exc
        self.write_endpoint = None
        self.read_endpoint = None
        if error is not None:
            raise UsbBackendError(_usb_error_message("close", error)) from error

    def send_frame(self, frame: bytes) -> bytes:
        if self.write_endpoint is None or self.read_endpoint is None:
            self.open()
        uses_ffcc_transport = self._uses_ffcc_transport()
        self.write_frame(frame)
        if self.read_endpoint is None:
            return b""
        read_size = NORMAL_COMMAND_TRANSFER_SIZE if uses_ffcc_transport else int(
            getattr(self.read_endpoint, "wMaxPacketSize", 64) or 64
        )
        data = bytes(self.read_endpoint.read(read_size, timeout=self.timeout_ms))
        return decode_ffcc_transport(data) if uses_ffcc_transport else data

    def write_frame(self, frame: bytes) -> int:
        """Write one normal command without consuming capture/ack data from bulk IN."""

        if self.write_endpoint is None:
            self.open()
        frame = bytes(frame)
        padded_size = (
            (len(frame) + NORMAL_COMMAND_TRANSFER_SIZE - 1)
            // NORMAL_COMMAND_TRANSFER_SIZE
            * NORMAL_COMMAND_TRANSFER_SIZE
        )
        transfer = frame.ljust(padded_size, b"\x00")
        if self._uses_ffcc_transport():
            transfer = encode_ffcc_transport(transfer)
        return self.write_chunk(transfer)

    def write_chunk(self, data: bytes, timeout_ms: int | None = None) -> int:
        if self.write_endpoint is None:
            self.open()
        if self.write_endpoint is None:
            raise UsbBackendError("could not find USB OUT endpoint")
        timeout = self.timeout_ms if timeout_ms is None else timeout_ms
        if not isinstance(timeout, int) or timeout <= 0:
            raise ProtocolError(f"USB timeout must be a positive integer, got {timeout!r}")
        try:
            return int(self.write_endpoint.write(bytes(data), timeout=timeout))
        except Exception as exc:
            raise UsbBackendError(_usb_error_message("write", exc)) from exc

    def read_chunk(self, size: int | None = None, timeout_ms: int | None = None) -> bytes:
        if self.read_endpoint is None:
            self.open()
        if self.read_endpoint is None:
            raise UsbBackendError("could not find USB IN endpoint")
        read_size = size
        if read_size is None:
            read_size = int(getattr(self.read_endpoint, "wMaxPacketSize", 64) or 64)
        if not isinstance(read_size, int) or read_size <= 0:
            raise ProtocolError(f"USB read size must be a positive integer, got {read_size!r}")
        timeout = self.timeout_ms if timeout_ms is None else timeout_ms
        if not isinstance(timeout, int) or timeout <= 0:
            raise ProtocolError(f"USB timeout must be a positive integer, got {timeout!r}")
        try:
            data = bytes(self.read_endpoint.read(read_size, timeout=timeout))
            if (
                self._uses_ffcc_transport()
                and len(data) >= NORMAL_COMMAND_TRANSFER_SIZE
                and len(data) % NORMAL_COMMAND_TRANSFER_SIZE == 0
            ):
                return decode_ffcc_transport(data)
            return data
        except Exception as exc:
            raise UsbBackendError(_usb_error_message("read", exc)) from exc

    def _uses_ffcc_transport(self) -> bool:
        return (
            int(getattr(self.device, "idVendor", 0)) == 0x1A86
            and int(getattr(self.device, "idProduct", 0)) == 0xFFCC
        )

    def _find_device(self) -> Any | None:
        candidates = [self.vid_pid] if self.vid_pid is not None else [(item.vid, item.pid) for item in SUPPORTED_USB_IDS]
        for vid, pid in candidates:
            dev = self.usb_core.find(idVendor=vid, idProduct=pid)
            if dev is not None:
                return dev
        return None

    def _detach_kernel_driver(self, interface: int) -> None:
        if not hasattr(self.device, "is_kernel_driver_active"):
            return
        try:
            active = self.device.is_kernel_driver_active(interface)
        except (NotImplementedError, AttributeError):
            return
        if active and hasattr(self.device, "detach_kernel_driver"):
            self.device.detach_kernel_driver(interface)

    def _find_endpoints(self, device: Any) -> tuple[Any | None, Any | None]:
        write_endpoint = None
        read_endpoint = None
        for config in device:
            for interface in config:
                if getattr(interface, "bInterfaceNumber", 0) != 0:
                    continue
                for endpoint in interface:
                    direction = self.usb_util.endpoint_direction(endpoint.bEndpointAddress)
                    if direction == self.usb_util.ENDPOINT_OUT and write_endpoint is None:
                        write_endpoint = endpoint
                    if direction == self.usb_util.ENDPOINT_IN and read_endpoint is None:
                        read_endpoint = endpoint
        return write_endpoint, read_endpoint

    @staticmethod
    def _device_path(device: Any) -> str | None:
        bus = getattr(device, "bus", None)
        address = getattr(device, "address", None)
        if bus is None or address is None:
            return None
        return f"{bus}-{address}"
