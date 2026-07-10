from __future__ import annotations

from enum import Enum

from .errors import ProtocolError

MCU_FRAME_SIZE = 0x1FE
DIRECT_MCU_FRAME_SIZE = 0x40
ANALYZER_MARKER = b"ATK-LOGIC-ANALYZER"


class FirmwareTarget(str, Enum):
    MCU = "mcu"
    FPGA = "fpga"


class McuTransportMode(str, Enum):
    FRAMED_510 = "framed-510"
    DIRECT_64 = "direct-64"


_ENTER_COMMAND = {FirmwareTarget.MCU: 0x82, FirmwareTarget.FPGA: 0x85}
_DATA_COMMAND = {FirmwareTarget.MCU: 0x83, FirmwareTarget.FPGA: 0x86}
_UPDATE_MARKER = {
    FirmwareTarget.MCU: ANALYZER_MARKER + b"-MCU-V1",
    FirmwareTarget.FPGA: ANALYZER_MARKER + b"-FPGA-V1",
}


def _fixed_frame(prefix: bytes) -> bytes:
    if len(prefix) > MCU_FRAME_SIZE:
        raise ProtocolError(f"MCU frame prefix exceeds {MCU_FRAME_SIZE} bytes")
    return prefix.ljust(MCU_FRAME_SIZE, b"\x00")


def build_get_mcu_version_frame() -> bytes:
    return _fixed_frame(b"\x0a\x81\x0b")


def build_restart_mcu_frame() -> bytes:
    return _fixed_frame(b"\x0a\x84\x0b")


def build_enter_bootloader_frame() -> bytes:
    return _fixed_frame(b"\x0a\x80" + ANALYZER_MARKER)


def build_enter_update_frame(target: FirmwareTarget) -> bytes:
    try:
        command = _ENTER_COMMAND[target]
        marker = _UPDATE_MARKER[target]
    except KeyError as exc:
        raise ProtocolError(f"unsupported firmware target: {target!r}") from exc
    return _fixed_frame(bytes((0x0A, command)) + marker)


def build_firmware_data_frame(
    data: bytes,
    *,
    target: FirmwareTarget,
    mode: McuTransportMode = McuTransportMode.FRAMED_510,
) -> bytes:
    data = bytes(data)
    if mode == McuTransportMode.DIRECT_64:
        if len(data) > DIRECT_MCU_FRAME_SIZE:
            raise ProtocolError(f"direct MCU update data cannot exceed {DIRECT_MCU_FRAME_SIZE} bytes")
        return data.ljust(DIRECT_MCU_FRAME_SIZE, b"\x00")
    if mode != McuTransportMode.FRAMED_510:
        raise ProtocolError(f"unsupported MCU transport mode: {mode!r}")
    if len(data) > 0x1F8:
        raise ProtocolError("framed MCU update data cannot exceed 504 bytes")
    try:
        command = _DATA_COMMAND[target]
    except KeyError as exc:
        raise ProtocolError(f"unsupported firmware target: {target!r}") from exc
    prefix = bytes((0x0A, command)) + len(data).to_bytes(2, "little") + data + b"\x00\x0b"
    return _fixed_frame(prefix)


def firmware_data_frames(
    firmware: bytes,
    *,
    target: FirmwareTarget,
    mode: McuTransportMode = McuTransportMode.FRAMED_510,
) -> list[bytes]:
    """Reproduce ThreadDownload's full-chunk loop plus mandatory final remainder send."""

    firmware = bytes(firmware)
    chunk_size = 0x100 if mode == McuTransportMode.FRAMED_510 else DIRECT_MCU_FRAME_SIZE
    if mode not in (McuTransportMode.FRAMED_510, McuTransportMode.DIRECT_64):
        raise ProtocolError(f"unsupported MCU transport mode: {mode!r}")
    full_count, remainder = divmod(len(firmware), chunk_size)
    frames = [
        build_firmware_data_frame(
            firmware[index * chunk_size : (index + 1) * chunk_size], target=target, mode=mode
        )
        for index in range(full_count)
    ]
    frames.append(build_firmware_data_frame(firmware[-remainder:] if remainder else b"", target=target, mode=mode))
    return frames


def validate_firmware_ack(data: bytes, *, expected_command: int) -> bool:
    return len(data) >= 3 and data[0] == 0x0A and data[1] == expected_command and data[2] == 0x01
