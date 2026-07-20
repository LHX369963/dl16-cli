import pytest

from dl16_cli.errors import ProtocolError
from dl16_cli.pwm import PWM_BASE_HZ, PWM_MAX_HZ, build_pwm_start_payload, build_pwm_stop_payload


def test_pwm_base_frequency_matches_reverse_evidence():
    assert PWM_BASE_HZ == 200_000_000
    assert PWM_MAX_HZ == 20_000_000


def test_pwm_start_payload_for_channel_zero_1khz_50_percent_little_endian():
    payload = build_pwm_start_payload(channel=0, frequency_hz=1_000, duty_percent=50)
    assert payload == bytes.fromhex("11400d0300a0860100")


def test_pwm_start_payload_for_channel_one_10khz_25_percent_little_endian():
    payload = build_pwm_start_payload(channel=1, frequency_hz=10_000, duty_percent=25)
    assert payload == bytes.fromhex("21204e000088130000")


def test_pwm_counts_round_half_up_like_original_application():
    payload = build_pwm_start_payload(channel=0, frequency_hz=3_000, duty_percent=33)
    assert int.from_bytes(payload[1:5], "little") == 66_667
    assert int.from_bytes(payload[5:9], "little") == 22_000


def test_pwm_20mhz_endpoint_uses_ten_counter_ticks():
    payload = build_pwm_start_payload(channel=0, frequency_hz=20_000_000, duty_percent=50)
    assert int.from_bytes(payload[1:5], "little") == 10
    assert int.from_bytes(payload[5:9], "little") == 5


def test_pwm_start_payload_supports_big_endian_for_verification_experiments():
    payload = build_pwm_start_payload(channel=0, frequency_hz=1_000, duty_percent=50, byteorder="big")
    assert payload == bytes.fromhex("1100030d40000186a0")


def test_pwm_stop_payload_uses_channel_plus_one_shifted_nibble():
    assert build_pwm_stop_payload(0) == bytes.fromhex("10")
    assert build_pwm_stop_payload(1) == bytes.fromhex("20")


@pytest.mark.parametrize("channel", [-1, 2, 16])
def test_pwm_rejects_invalid_channel(channel):
    with pytest.raises(ProtocolError, match="channel must be in range"):
        build_pwm_start_payload(channel=channel, frequency_hz=1_000, duty_percent=50)


@pytest.mark.parametrize("frequency", [0, -1, 20_000_001, 200_000_001])
def test_pwm_rejects_invalid_frequency(frequency):
    with pytest.raises(ProtocolError, match="frequency_hz must be"):
        build_pwm_start_payload(channel=0, frequency_hz=frequency, duty_percent=50)


@pytest.mark.parametrize("duty", [-0.1, 100.1])
def test_pwm_rejects_invalid_duty(duty):
    with pytest.raises(ProtocolError, match="duty_percent must be"):
        build_pwm_start_payload(channel=0, frequency_hz=1_000, duty_percent=duty)


@pytest.mark.parametrize("duty", [float("nan"), float("inf"), float("-inf")])
def test_pwm_rejects_non_finite_duty(duty):
    with pytest.raises(ProtocolError, match="duty_percent must be finite"):
        build_pwm_start_payload(channel=0, frequency_hz=1_000, duty_percent=duty)
