import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.trigger import TriggerState, build_simple_trigger_payload, pack_trigger_states, parse_trigger_states


def test_trigger_state_nibble_map_matches_jump_table():
    assert pack_trigger_states([
        TriggerState.NULL,
        TriggerState.RISING,
        TriggerState.HIGH,
        TriggerState.FALLING,
        TriggerState.LOW,
        TriggerState.DOUBLE,
    ]) == bytes.fromhex("714203")


def test_first_channel_is_high_nibble_and_disabled_channel_contributes_zero():
    assert pack_trigger_states([TriggerState.RISING, TriggerState.HIGH]) == b"\x14"
    assert pack_trigger_states([TriggerState.NULL, TriggerState.RISING], enabled=[False, True]) == b"\x01"


def test_channel_offset_is_zero_byte_padding_and_odd_channel_is_padded_low():
    assert pack_trigger_states([TriggerState.RISING], channel_offset=2) == bytes.fromhex("0010")


def test_parse_trigger_states_accepts_names_case_insensitively():
    assert parse_trigger_states("rising,HIGH, falling ,low,double,null") == [
        TriggerState.RISING,
        TriggerState.HIGH,
        TriggerState.FALLING,
        TriggerState.LOW,
        TriggerState.DOUBLE,
        TriggerState.NULL,
    ]


def test_simple_trigger_appends_collect_type_flags():
    states = [TriggerState.RISING, TriggerState.HIGH]
    assert build_simple_trigger_payload(states, collect_type=1) == bytes.fromhex("140000")
    assert build_simple_trigger_payload(states, collect_type=2) == bytes.fromhex("140100")
    assert build_simple_trigger_payload(states, collect_type=3) == bytes.fromhex("140001")


@pytest.mark.parametrize("text", ["", "rising,bogus"])
def test_trigger_state_parser_rejects_invalid_input(text):
    with pytest.raises(ProtocolError):
        parse_trigger_states(text)
