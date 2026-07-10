import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.firmware import (
    FirmwareTarget,
    McuTransportMode,
    build_enter_bootloader_frame,
    build_enter_update_frame,
    build_firmware_data_frame,
    build_get_mcu_version_frame,
    build_restart_mcu_frame,
    firmware_data_frames,
    validate_firmware_ack,
)


def test_fixed_mcu_query_frames_match_recovered_510_byte_buffers():
    version = build_get_mcu_version_frame()
    restart = build_restart_mcu_frame()
    assert len(version) == len(restart) == 510
    assert version[:4] == b"\x0a\x81\x0b\x00"
    assert restart[:4] == b"\x0a\x84\x0b\x00"
    assert not any(version[3:])


def test_enter_bootloader_frame_contains_recovered_analyzer_marker():
    frame = build_enter_bootloader_frame()
    assert len(frame) == 510
    assert frame.startswith(b"\x0a\x80ATK-LOGIC-ANALYZER\x00")


@pytest.mark.parametrize(
    ("target", "command", "marker"),
    [
        (FirmwareTarget.MCU, 0x82, b"ATK-LOGIC-ANALYZER-MCU-V1"),
        (FirmwareTarget.FPGA, 0x85, b"ATK-LOGIC-ANALYZER-FPGA-V1"),
    ],
)
def test_enter_update_frame_maps_target_to_recovered_command_and_marker(target, command, marker):
    frame = build_enter_update_frame(target)
    assert len(frame) == 510
    assert frame[:2] == bytes((0x0A, command))
    assert frame[2 : 2 + len(marker)] == marker
    assert frame[2 + len(marker)] == 0


@pytest.mark.parametrize(
    ("target", "command"),
    [(FirmwareTarget.MCU, 0x83), (FirmwareTarget.FPGA, 0x86)],
)
def test_framed_firmware_data_layout_has_zero_then_end_marker(target, command):
    frame = build_firmware_data_frame(b"abc", target=target)
    assert len(frame) == 510
    assert frame[:7] == bytes((0x0A, command, 3, 0)) + b"abc"
    assert frame[7:9] == b"\x00\x0b"
    assert not any(frame[9:])


def test_framed_firmware_data_accepts_504_bytes_and_rejects_more():
    frame = build_firmware_data_frame(b"x" * 504, target=FirmwareTarget.MCU)
    assert frame[-2:] == b"\x00\x0b"
    with pytest.raises(ProtocolError, match="504"):
        build_firmware_data_frame(b"x" * 505, target=FirmwareTarget.MCU)


def test_direct_64_mode_zero_pads_raw_data_and_rejects_more_than_64():
    frame = build_firmware_data_frame(
        b"abc", target=FirmwareTarget.FPGA, mode=McuTransportMode.DIRECT_64
    )
    assert len(frame) == 64
    assert frame[:3] == b"abc"
    assert not any(frame[3:])
    with pytest.raises(ProtocolError, match="64"):
        build_firmware_data_frame(
            b"x" * 65, target=FirmwareTarget.FPGA, mode=McuTransportMode.DIRECT_64
        )


def test_firmware_planner_uses_original_chunk_sizes_and_always_emits_final_remainder():
    framed = firmware_data_frames(b"x" * 512, target=FirmwareTarget.MCU)
    assert len(framed) == 3
    assert [int.from_bytes(frame[2:4], "little") for frame in framed] == [256, 256, 0]
    direct = firmware_data_frames(
        b"x" * 65, target=FirmwareTarget.FPGA, mode=McuTransportMode.DIRECT_64
    )
    assert len(direct) == 2
    assert direct[0] == b"x" * 64
    assert direct[1][0] == ord("x") and not any(direct[1][1:])


def test_ack_requires_start_expected_command_and_success_byte():
    assert validate_firmware_ack(b"\x0a\x83\x01", expected_command=0x83)
    assert not validate_firmware_ack(b"\x0a\x83\x00", expected_command=0x83)
    assert not validate_firmware_ack(b"\x0a\x86\x01", expected_command=0x83)
    assert not validate_firmware_ack(b"\x0a\x83", expected_command=0x83)
