import pytest

from atkdl16_cli.capture import SamplingParameters, build_parameter_setting_payload
from atkdl16_cli.errors import ProtocolError


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
        bytes.fromhex("808c03")
        + (1_000_000).to_bytes(5, "little")
        + (250_000).to_bytes(5, "little")
    )


def test_parameter_flags_combine_rle_and_buffer():
    params = SamplingParameters(1, 1_000, 0, 0, 0, True, True, 1)
    assert build_parameter_setting_payload(params)[0] == 0xC0


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
