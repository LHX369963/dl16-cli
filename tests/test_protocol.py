import binascii

import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.protocol import (
    Command,
    SUPPORTED_USB_IDS,
    UsbId,
    build_inner_frame,
    build_transport_frame,
    crc32_atk,
    crc32_bytes,
)


def test_supported_usb_ids_match_reverse_evidence():
    assert SUPPORTED_USB_IDS == (
        UsbId(0x1A86, 0xFFCC),
        UsbId(0x1A86, 0x6A6B),
        UsbId(0x04B4, 0x6A6A),
    )


def test_command_values_match_reverse_evidence():
    assert Command.GET_DEVICE_DATA == 0x10
    assert Command.PARAMETER_SETTING == 0x11
    assert Command.SIMPLE_TRIGGER == 0x12
    assert Command.STAGE_TRIGGER == 0x13
    assert Command.SERIAL_TRIGGER == 0x14
    assert Command.STOP == 0x15
    assert Command.PWM == 0x17


def test_crc32_uses_standard_seed_until_binary_vector_is_recovered():
    assert crc32_atk(b"\x17\x0a\x11") == binascii.crc32(b"\x17\x0a\x11") & 0xFFFFFFFF


def test_crc32_bytes_supports_explicit_byte_order():
    assert crc32_bytes(0x12345678, "little") == bytes.fromhex("78563412")
    assert crc32_bytes(0x12345678, "big") == bytes.fromhex("12345678")


def test_inner_frame_contains_command_length_and_payload():
    assert build_inner_frame(Command.PWM, bytes.fromhex("110100000001000000")) == bytes.fromhex(
        "170a110100000001000000"
    )


def test_transport_frame_wraps_inner_frame_with_padding_markers_and_crc():
    inner = bytes.fromhex("170a110100000001000000")
    expected_crc = crc32_bytes(crc32_atk(inner), "little")
    frame = build_transport_frame(Command.PWM, bytes.fromhex("110100000001000000"))
    assert frame[:8] == b"\x00" * 8
    assert frame[8] == 0x0A
    assert frame[9 : 9 + len(inner)] == inner
    assert frame[9 + len(inner) : 13 + len(inner)] == expected_crc
    assert frame[-1] == 0x0B
    assert len(frame) == len(inner) + 15


def test_inner_frame_rejects_payloads_too_large_for_one_byte_length():
    with pytest.raises(ProtocolError, match="payload too long"):
        build_inner_frame(Command.PWM, bytes(255))
