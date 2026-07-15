import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.sampling import (
    SAMPLE_RATE_TO_INDEX,
    resolve_sample_index,
    validate_capture_combination,
)


def test_recovered_sample_rate_index_table_is_complete():
    assert SAMPLE_RATE_TO_INDEX == {
        500_000_000: 0,
        1_000_000: 1,
        2_000_000: 2,
        4_000_000: 3,
        5_000_000: 4,
        10_000_000: 5,
        20_000_000: 6,
        40_000_000: 8,
        50_000_000: 9,
        100_000_000: 10,
        200_000_000: 11,
        250_000_000: 12,
    }


def test_sample_index_is_automatically_resolved_and_explicit_value_must_match():
    assert resolve_sample_index(250_000_000) == 12
    assert resolve_sample_index(20_000_000, requested_index=6) == 6
    with pytest.raises(ProtocolError, match="does not match"):
        resolve_sample_index(20_000_000, requested_index=7)
    with pytest.raises(ProtocolError, match="unsupported sample rate"):
        resolve_sample_index(3_000_000)


@pytest.mark.parametrize("channels", [1, 4, 8, 16])
def test_buffer_accepts_up_to_sixteen_channels_at_500mhz(channels):
    validate_capture_combination(500_000_000, channels, is_buffer=True)


@pytest.mark.parametrize(
    ("rate", "maximum"),
    [(20_000_000, 16), (40_000_000, 6), (50_000_000, 6), (100_000_000, 3)],
)
def test_stream_channel_limits_match_dl16_manual(rate, maximum):
    validate_capture_combination(rate, maximum, is_buffer=False)
    if maximum < 16:
        with pytest.raises(ProtocolError, match=f"at most {maximum} channel"):
            validate_capture_combination(rate, maximum + 1, is_buffer=False)


def test_stream_rejects_rates_above_100mhz():
    with pytest.raises(ProtocolError, match="at most 100000000 Hz"):
        validate_capture_combination(200_000_000, 1, is_buffer=False)
