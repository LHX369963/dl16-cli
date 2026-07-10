import pytest

from atkdl16_cli.errors import FirmwareUpdateError, ProtocolError, UsbBackendError
from atkdl16_cli.firmware import (
    FirmwareTarget,
    McuTransportMode,
    build_enter_bootloader_frame,
    build_enter_update_frame,
    build_firmware_data_frame,
    build_get_mcu_version_frame,
    build_restart_mcu_frame,
    firmware_data_frames,
    flash_firmware,
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


class FakeFirmwareBackend:
    def __init__(self, acknowledgements):
        self.acknowledgements = list(acknowledgements)
        self.writes = []

    def write_chunk(self, data, timeout_ms=None):
        del timeout_ms
        self.writes.append(bytes(data))
        return len(data)

    def read_chunk(self, size=None, timeout_ms=None):
        del size, timeout_ms
        item = self.acknowledgements.pop(0) if self.acknowledgements else b""
        if isinstance(item, Exception):
            raise item
        return item


def test_guarded_flash_sequence_enters_updates_all_chunks_and_restarts():
    backend = FakeFirmwareBackend([
        b"\x0a\x82\x01",
        b"\x0a\x83\x01",
        b"\x0a\x83\x01",
    ])
    sleeps = []
    result = flash_firmware(
        backend,
        b"x" * 257,
        target=FirmwareTarget.MCU,
        sleep_fn=sleeps.append,
    )
    assert len(backend.writes) == 4
    assert backend.writes[0][:2] == b"\x0a\x82"
    assert [int.from_bytes(frame[2:4], "little") for frame in backend.writes[1:3]] == [256, 1]
    assert backend.writes[-1][:3] == b"\x0a\x84\x0b"
    assert sleeps == [1.0]
    assert result.data_frames == 2
    assert result.firmware_bytes == 257


def test_flash_ack_wait_retries_six_times_with_original_50ms_delay():
    backend = FakeFirmwareBackend([b"bad"] * 6)
    sleeps = []
    with pytest.raises(FirmwareUpdateError, match="0x82"):
        flash_firmware(
            backend, b"", target=FirmwareTarget.MCU, sleep_fn=sleeps.append
        )
    assert sleeps == [0.05] * 5
    assert len(backend.writes) == 1


def test_direct_mode_writes_only_64_bytes_and_expects_0x86_data_ack():
    backend = FakeFirmwareBackend([b"\x0a\x82\x01", b"\x0a\x86\x01"])
    sleeps = []
    flash_firmware(
        backend,
        b"abc",
        target=FirmwareTarget.MCU,
        mode=McuTransportMode.DIRECT_64,
        sleep_fn=sleeps.append,
    )
    assert [len(item) for item in backend.writes] == [64, 64, 64]
    assert backend.writes[1][:3] == b"abc"


def test_flash_treats_wrapped_usb_read_timeouts_as_ack_retries():
    backend = FakeFirmwareBackend([
        UsbBackendError("timeout"),
        b"\x0a\x82\x01",
        b"\x0a\x83\x01",
    ])
    sleeps = []
    flash_firmware(backend, b"abc", target=FirmwareTarget.MCU, sleep_fn=sleeps.append)
    assert sleeps == [0.05, 1.0]
