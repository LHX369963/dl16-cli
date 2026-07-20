import pytest

from dl16_cli.capture import (
    Dl16StreamParser,
    SamplingParameters,
    decode_channel_packet,
    decode_rle_pairs,
    iter_sample_bits,
    interpret_capture_packet,
    build_parameter_setting_payload,
)
from dl16_cli.errors import ProtocolError


def test_parameter_payload_layout_matches_recovered_binary_formula():
    params = SamplingParameters(
        set_time=10.0,
        set_hz=100_000_000,
        trigger_position_percent=25.0,
        threshold_level=-1.2,
        sample_index=3,
        is_rle=True,
        is_buffer=False,
        collect_type=1,
    )
    # depth = 10 * (100_000_000 // 1000) = 1_000_000
    # trigger = (1_000_000 // 100) * 25 = 250_000
    assert build_parameter_setting_payload(params) == (
        bytes.fromhex("408c03")
        + (1_000_000).to_bytes(5, "little")
        + (250_000).to_bytes(5, "little")
    )


def test_parameter_flags_combine_rle_and_buffer():
    params = SamplingParameters(1, 1_000, 0, 0, 0, True, True, 1)
    assert build_parameter_setting_payload(params)[0] == 0xC0


def test_parameter_flags_match_original_buffer_and_rle_bits_individually():
    buffer_only = SamplingParameters(1, 1_000, 0, 0, 0, False, True, 1)
    rle_only = SamplingParameters(1, 1_000, 0, 0, 0, True, False, 1)
    assert build_parameter_setting_payload(buffer_only)[0] == 0x80
    assert build_parameter_setting_payload(rle_only)[0] == 0x40


@pytest.mark.parametrize(
    ("level", "expected"),
    [(0.0, 0x00), (1.24, 0x0C), (1.25, 0x0D), (-1.24, 0x8C), (-1.25, 0x8D)],
)
def test_threshold_uses_tenth_volt_sign_magnitude_rounding(level, expected):
    params = SamplingParameters(1, 1_000, 0, level, 0)
    assert build_parameter_setting_payload(params)[1] == expected


def test_stream_collect_type_rejects_rle_or_buffer():
    with pytest.raises(ProtocolError, match="stream collect type 3"):
        build_parameter_setting_payload(SamplingParameters(1, 1_000, 0, 0, 0, True, False, 3))
    with pytest.raises(ProtocolError, match="stream collect type 3"):
        build_parameter_setting_payload(SamplingParameters(1, 1_000, 0, 0, 0, False, True, 3))


@pytest.mark.parametrize(
    "params",
    [
        SamplingParameters(-1, 1_000, 0, 0, 0),
        SamplingParameters(1, 999, 0, 0, 0),
        SamplingParameters(1, 1_000, -1, 0, 0),
        SamplingParameters(1, 1_000, 101, 0, 0),
        SamplingParameters(1, 1_000, 0, 20, 0),
        SamplingParameters(1, 1_000, 0, 0, 256),
    ],
)
def test_parameter_builder_rejects_out_of_range_values(params):
    with pytest.raises(ProtocolError):
        build_parameter_setting_payload(params)


def dl16_packet(packet_type: int, payload: bytes) -> bytes:
    return bytes((0x0A, packet_type)) + len(payload).to_bytes(2, "little") + payload + b"\x00\x0b"


def test_stream_parser_decodes_recovered_dl16_packet_layout():
    raw = dl16_packet(1, b"\x12\x34\xaa\xbb")
    packets = Dl16StreamParser().feed(raw)
    assert len(packets) == 1
    packet = packets[0]
    assert packet.packet_type == 1
    assert packet.payload == b"\x12\x34\xaa\xbb"
    assert packet.metadata0 == 0x12
    assert packet.metadata1 == 0x34
    assert packet.body == b"\xaa\xbb"
    assert packet.raw == raw


def test_stream_parser_waits_for_fragmented_packet():
    raw = dl16_packet(4, b"\x01\x00payload")
    parser = Dl16StreamParser()
    assert parser.feed(raw[:3]) == []
    assert parser.feed(raw[3:7]) == []
    assert [packet.raw for packet in parser.feed(raw[7:])] == [raw]


def test_stream_parser_returns_concatenated_packets():
    first = dl16_packet(3, b"\x00\x00hello")
    second = dl16_packet(6, b"\x01\x00")
    packets = Dl16StreamParser().feed(first + second)
    assert [(packet.packet_type, packet.body) for packet in packets] == [(3, b"hello"), (6, b"")]


def test_stream_parser_discards_noise_and_resynchronizes_after_bad_trailer():
    malformed = bytes((0x0A, 1, 1, 0, 0xFF, 0x99, 0x0B))
    valid = dl16_packet(5, b"\x02\x00done")
    packets = Dl16StreamParser().feed(b"noise" + malformed + valid)
    assert [packet.raw for packet in packets] == [valid]


def test_stream_parser_rejects_unknown_type_and_resynchronizes():
    unknown = dl16_packet(7, b"\x00\x00")
    valid = dl16_packet(2, b"\x03\x04")
    packets = Dl16StreamParser().feed(unknown + valid)
    assert [packet.packet_type for packet in packets] == [2]


def test_packet_short_payload_exposes_missing_metadata_without_guessing():
    packet = Dl16StreamParser().feed(dl16_packet(1, b"\x7f"))[0]
    assert packet.metadata0 == 0x7F
    assert packet.metadata1 is None
    assert packet.body == b""


def test_recovered_rle_decoder_expands_count_value_pairs():
    assert decode_rle_pairs(bytes.fromhex("03a50200")) == bytes.fromhex("a5a5a50000")


def test_recovered_rle_decoder_rejects_odd_input_and_original_buffer_overflow():
    with pytest.raises(ProtocolError, match="count/value pairs"):
        decode_rle_pairs(b"\xaa")
    with pytest.raises(ProtocolError, match="524288"):
        decode_rle_pairs(b"\xff\xff" * 2057)


def test_sample_bits_are_chronological_lsb_first():
    assert list(iter_sample_bits(bytes((0b10000001,)))) == [1, 0, 0, 0, 0, 0, 0, 1]


def test_channel_packet_decoder_uses_metadata0_as_channel_and_expands_rle():
    packet = Dl16StreamParser().feed(dl16_packet(1, b"\x03\x09\x02\x81"))[0]
    block = decode_channel_packet(packet, is_rle=True)
    assert block.channel == 3
    assert block.metadata1 == 9
    assert block.packed_samples == b"\x81\x81"
    assert block.sample_count == 16
    assert list(block.iter_samples())[:9] == [1, 0, 0, 0, 0, 0, 0, 1, 1]


def test_channel_packet_decoder_rejects_non_data_packet():
    packet = Dl16StreamParser().feed(dl16_packet(4, b"\x15\x00"))[0]
    with pytest.raises(ProtocolError, match="type 1"):
        decode_channel_packet(packet)


@pytest.mark.parametrize("packet_type", [3, 5])
def test_control_value_packets_expose_recovered_u40_without_assigning_unknown_semantics(packet_type):
    packet = Dl16StreamParser().feed(
        dl16_packet(packet_type, b"\x00\x00\x78\x56\x34\x12\x01")
    )[0]
    assert interpret_capture_packet(packet) == {
        "type": packet_type,
        "metadata0": 0,
        "metadata1": 0,
        "value_u40": 0x0112345678,
    }


def test_type4_control_packet_exposes_subcommand_and_status_bytes():
    packet = Dl16StreamParser().feed(dl16_packet(4, b"\x00\x00\x12\x03\xaa"))[0]
    assert interpret_capture_packet(packet) == {
        "type": 4,
        "metadata0": 0,
        "metadata1": 0,
        "control_command": 0x12,
        "control_status": 0x03,
        "control_extra_hex": "aa",
    }


def test_unknown_or_short_control_fields_remain_absent():
    packet = Dl16StreamParser().feed(dl16_packet(2, b"\x01"))[0]
    assert interpret_capture_packet(packet) == {
        "type": 2,
        "metadata0": 1,
        "metadata1": None,
        "body_hex": "",
    }


def test_type2_device_info_exposes_recovered_numeric_fields_and_nul_terminated_text():
    body = bytes((1, 0xAA, 0xBB, 2, 34, 5, 67)) + b"DL16-A\x00ignored"
    packet = Dl16StreamParser().feed(dl16_packet(2, b"\x00\x00" + body))[0]
    assert interpret_capture_packet(packet) == {
        "type": 2,
        "metadata0": 0,
        "metadata1": 0,
        "device_info_format": 1,
        "value_3_4": 234,
        "value_5_6": 567,
        "device_text": "DL16-A",
        "reserved_1_2_hex": "aabb",
    }


def test_type2_format_zero_keeps_unknown_fields_but_exposes_device_text():
    body = bytes((0, 0x02, 0x10, 0x02, 0x16, 0x0B, 0x08)) + b"DL16"
    packet = Dl16StreamParser().feed(dl16_packet(2, b"\xff\x00" + body))[0]
    assert interpret_capture_packet(packet) == {
        "type": 2,
        "metadata0": 0xFF,
        "metadata1": 0,
        "device_info_format": 0,
        "device_text": "DL16",
        "reserved_1_2_hex": "0210",
        "unassigned_3_6_hex": "02160b08",
    }
