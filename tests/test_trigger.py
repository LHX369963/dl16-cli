import pytest

from dl16_cli.errors import ProtocolError
from dl16_cli.trigger import TriggerState, build_simple_trigger_payload, pack_trigger_states, parse_trigger_states


def test_trigger_state_nibble_map_matches_jump_table():
    assert pack_trigger_states([
        TriggerState.NULL,
        TriggerState.RISING,
        TriggerState.HIGH,
        TriggerState.FALLING,
        TriggerState.LOW,
        TriggerState.DOUBLE,
    ]) == bytes.fromhex("f9ca8b")


def test_first_channel_is_high_nibble_and_enable_bit_is_preserved():
    assert pack_trigger_states([TriggerState.RISING, TriggerState.HIGH]) == b"\x9c"
    assert pack_trigger_states([TriggerState.NULL, TriggerState.RISING], enabled=[False, True]) == b"\x79"


def test_channel_offset_is_zero_byte_padding_and_odd_channel_is_padded_low():
    assert pack_trigger_states([TriggerState.RISING], channel_offset=2) == bytes.fromhex("0090")


def test_parse_trigger_states_accepts_names_case_insensitively():
    assert parse_trigger_states("rising,HIGH, falling ,low,double,null") == [
        TriggerState.RISING,
        TriggerState.HIGH,
        TriggerState.FALLING,
        TriggerState.LOW,
        TriggerState.DOUBLE,
        TriggerState.NULL,
    ]
    assert parse_trigger_states("either,any") == [TriggerState.DOUBLE, TriggerState.DOUBLE]


def test_simple_trigger_appends_collect_type_flags():
    states = [TriggerState.RISING, TriggerState.HIGH]
    assert build_simple_trigger_payload(states, collect_type=1) == bytes.fromhex("9c0000")
    assert build_simple_trigger_payload(states, collect_type=2) == bytes.fromhex("9c0100")
    assert build_simple_trigger_payload(states, collect_type=3) == bytes.fromhex("9c0001")


def test_simple_trigger_uses_f_for_enabled_dont_care_channel_seen_on_dl16():
    states = [TriggerState.NULL] * 16
    enabled = [False] * 16
    enabled[7] = True
    assert build_simple_trigger_payload(states, enabled=enabled, collect_type=0) == bytes.fromhex(
        "7777777f777777770000"
    )


@pytest.mark.parametrize("text", ["", "rising,bogus"])
def test_trigger_state_parser_rejects_invalid_input(text):
    with pytest.raises(ProtocolError):
        parse_trigger_states(text)


def test_stage_trigger_payload_matches_recovered_layout():
    from dl16_cli.trigger import StageCondition, build_stage_trigger_payload

    stages = [
        StageCondition([TriggerState.RISING, TriggerState.HIGH], counter=0x1234, contiguous=False),
        StageCondition([TriggerState.FALLING, TriggerState.LOW], counter=1, contiguous=True),
    ]
    assert build_stage_trigger_payload(stages, trigger_level=2) == bytes.fromhex(
        "01023412409c"  # stage 1, level, counter LE, non-contiguous flag, states
        "0202010000a8"  # stage 2
    )


def test_stage_trigger_applies_enabled_mask_and_channel_offset():
    from dl16_cli.trigger import StageCondition, build_stage_trigger_payload

    payload = build_stage_trigger_payload(
        [StageCondition([TriggerState.NULL, TriggerState.RISING], counter=0, contiguous=True)],
        trigger_level=1,
        enabled=[False, True],
        channel_offset=2,
    )
    assert payload == bytes.fromhex("01010000000079")


def test_serial_trigger_payload_matches_recovered_layout():
    from dl16_cli.trigger import SerialTriggerConfig, build_serial_trigger_payload

    config = SerialTriggerConfig(
        value_channel=1,
        value_width=8,
        value_data=0x1234,
        time_channel=2,
        time_edge=1,
        start_states=[TriggerState.RISING, TriggerState.HIGH],
        stop_states=[TriggerState.FALLING, TriggerState.LOW],
        channel_offset=2,
    )
    assert build_serial_trigger_payload(config) == bytes.fromhex("030834120401009c00a8")


@pytest.mark.parametrize(
    "builder",
    [
        lambda: __import__("dl16_cli.trigger", fromlist=["*"]).build_stage_trigger_payload([], trigger_level=0),
        lambda: __import__("dl16_cli.trigger", fromlist=["*"]).build_stage_trigger_payload(
            [__import__("dl16_cli.trigger", fromlist=["*"]).StageCondition([TriggerState.RISING], 70000, True)],
            trigger_level=0,
        ),
    ],
)
def test_advanced_trigger_validation(builder):
    with pytest.raises(ProtocolError):
        builder()
