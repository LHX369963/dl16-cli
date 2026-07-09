from __future__ import annotations

import binascii
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

from .errors import ProtocolError


@dataclass(frozen=True, order=True)
class UsbId:
    vid: int
    pid: int

    def __post_init__(self) -> None:
        if not 0 <= self.vid <= 0xFFFF:
            raise ProtocolError(f"USB VID out of range: {self.vid!r}")
        if not 0 <= self.pid <= 0xFFFF:
            raise ProtocolError(f"USB PID out of range: {self.pid!r}")

    def __str__(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"


SUPPORTED_USB_IDS: tuple[UsbId, ...] = (
    UsbId(0x1A86, 0xFFCC),
    UsbId(0x1A86, 0x6A6B),
    UsbId(0x04B4, 0x6A6A),
)


class Command(IntEnum):
    GET_DEVICE_DATA = 0x10
    PARAMETER_SETTING = 0x11
    SIMPLE_TRIGGER = 0x12
    STAGE_TRIGGER = 0x13
    SERIAL_TRIGGER = 0x14
    STOP = 0x15
    PWM = 0x17


def _command_byte(command: int | Command) -> int:
    value = int(command)
    if not 0 <= value <= 0xFF:
        raise ProtocolError(f"command out of range: {value!r}")
    return value


def crc32_atk(data: bytes) -> int:
    """Return the CRC32 used by the current prototype.

    The original binary calls a function named gCRC32. Until a recovered vector
    proves different seed/xor behavior, this function intentionally uses
    Python's standard CRC32 and masks to an unsigned 32-bit value.
    """

    return binascii.crc32(data) & 0xFFFFFFFF


def crc32_bytes(value: int, byteorder: Literal["little", "big"] = "little") -> bytes:
    if byteorder not in {"little", "big"}:
        raise ProtocolError(f"unsupported CRC byte order: {byteorder!r}")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ProtocolError(f"CRC value out of range: {value!r}")
    return value.to_bytes(4, byteorder)


def build_inner_frame(command: int | Command, payload: bytes = b"") -> bytes:
    if not isinstance(payload, bytes):
        raise ProtocolError("payload must be bytes")
    length = len(payload) + 1
    if length > 0xFF:
        raise ProtocolError(f"payload too long for one-byte length: {len(payload)} bytes")
    return bytes((_command_byte(command), length)) + payload


def build_transport_frame(
    command: int | Command,
    payload: bytes = b"",
    crc_byteorder: Literal["little", "big"] = "little",
) -> bytes:
    inner = build_inner_frame(command, payload)
    crc = crc32_bytes(crc32_atk(inner), crc_byteorder)
    # The binary allocates inner_len + 15 bytes, writes 0x0a at offset 8,
    # copies the inner frame at offset 9, writes 0x0b immediately after the
    # inner frame, writes CRC32 at inner_len + 10, and leaves the final byte 0.
    return (b"\x00" * 8) + b"\x0a" + inner + b"\x0b" + crc + b"\x00"
