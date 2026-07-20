from dl16_cli.device import Dl16Device
from dl16_cli.protocol import Command, build_transport_frame
from dl16_cli.pwm import build_pwm_start_payload, build_pwm_stop_payload
from dl16_cli.usb import DeviceInfo, DryRunBackend


class InitializationBackend(DryRunBackend):
    def __init__(self):
        super().__init__(read_chunks=[
            bytes(512),
            b"\x0a\x81\x01mcu" + bytes(505),
            b"\x0a\x87\x01fpga0" + bytes(503),
            b"\x0a\x87\x02fpga1" + bytes(503),
        ])
        self.recovered = False

    def recover_ffcc_link(self):
        self.recovered = True

    def send_frame(self, frame):
        self.sent_frames.append(bytes(frame))
        return b"\x0a\x02\x0d\x00\xff\x00\x01\x02\x10\x02\x16\x0b\x08DL16\x00\x0b"


def test_dry_run_backend_lists_configured_devices():
    backend = DryRunBackend(devices=[DeviceInfo(vid=0x1A86, pid=0xFFCC, bus=1, address=2, path="1-2", speed="high")])
    assert backend.list_devices() == [DeviceInfo(vid=0x1A86, pid=0xFFCC, bus=1, address=2, path="1-2", speed="high")]


def test_device_pwm_start_sends_expected_transport_frame():
    backend = DryRunBackend()
    device = Dl16Device(backend)
    frame = device.pwm_start(channel=0, frequency_hz=1_000, duty_percent=50)
    expected = build_transport_frame(Command.PWM, build_pwm_start_payload(0, 1_000, 50))
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_device_pwm_stop_sends_expected_transport_frame():
    backend = DryRunBackend()
    device = Dl16Device(backend)
    frame = device.pwm_stop(channel=1)
    expected = build_transport_frame(Command.PWM, build_pwm_stop_payload(1))
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_device_stop_without_channel_sends_empty_stop_payload():
    backend = DryRunBackend()
    device = Dl16Device(backend)
    frame = device.stop()
    expected = build_transport_frame(Command.STOP, b"")
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_device_stop_with_channel_sends_one_byte_payload():
    backend = DryRunBackend()
    device = Dl16Device(backend)
    frame = device.stop(channel=2)
    expected = build_transport_frame(Command.STOP, b"\x02")
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_get_device_data_frame_is_built_without_sending():
    backend = DryRunBackend()
    device = Dl16Device(backend)
    frame = device.get_device_data_frame()
    assert frame == build_transport_frame(Command.GET_DEVICE_DATA, b"")
    assert backend.sent_frames == []


def test_get_device_data_sends_query_frame():
    backend = DryRunBackend()
    device = Dl16Device(backend)
    response = device.get_device_data()
    expected = build_transport_frame(Command.GET_DEVICE_DATA, b"")
    assert response == b""
    assert backend.sent_frames == [expected]


def test_initialize_connection_recovers_waits_and_runs_mcu_fpga_handshake():
    backend = InitializationBackend()
    sleeps = []
    response = Dl16Device(backend).initialize_connection(sleep_fn=sleeps.append)
    assert backend.recovered is True
    assert sleeps[0] == 0.4
    assert backend.written_chunks[0][:3] == b"\x0a\x81\x0b"
    assert backend.written_chunks[-2][:4] == b"\x0a\x87\x00\x0b"
    assert backend.written_chunks[-1][:4] == b"\x0a\x87\x01\x0b"
    assert b"DL16" in response


def test_raw_parameter_and_trigger_methods_send_expected_frames():
    backend = DryRunBackend()
    device = Dl16Device(backend)
    payload = b"\x11\x22"
    cases = [
        (device.parameter_setting_raw, Command.PARAMETER_SETTING),
        (device.simple_trigger_raw, Command.SIMPLE_TRIGGER),
        (device.stage_trigger_raw, Command.STAGE_TRIGGER),
        (device.serial_trigger_raw, Command.SERIAL_TRIGGER),
    ]
    for method, command in cases:
        frame = method(payload)
        assert frame == build_transport_frame(command, payload)
    assert backend.sent_frames == [build_transport_frame(command, payload) for _, command in cases]


def test_configure_sampling_sends_recovered_parameter_payload():
    from dl16_cli.capture import SamplingParameters, build_parameter_setting_payload

    backend = DryRunBackend()
    device = Dl16Device(backend)
    params = SamplingParameters(10, 100_000_000, 25, -1.2, 3, True, False, 1)
    frame = device.configure_sampling(params)
    expected = build_transport_frame(Command.PARAMETER_SETTING, build_parameter_setting_payload(params))
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_high_level_trigger_methods_send_built_payloads():
    from dl16_cli.trigger import (
        SerialTriggerConfig,
        StageCondition,
        TriggerState,
        build_serial_trigger_payload,
        build_simple_trigger_payload,
        build_stage_trigger_payload,
    )

    backend = DryRunBackend()
    device = Dl16Device(backend)
    states = [TriggerState.RISING, TriggerState.HIGH]
    simple = device.configure_simple_trigger(states, collect_type=1)
    stages = [StageCondition(states, 0x1234, False)]
    stage = device.configure_stage_trigger(stages, trigger_level=2)
    serial_config = SerialTriggerConfig(1, 8, 0x1234, 2, 1, states, [TriggerState.FALLING, TriggerState.LOW], 2)
    serial = device.configure_serial_trigger(serial_config)
    assert simple == build_transport_frame(Command.SIMPLE_TRIGGER, build_simple_trigger_payload(states))
    assert stage == build_transport_frame(Command.STAGE_TRIGGER, build_stage_trigger_payload(stages, trigger_level=2))
    assert serial == build_transport_frame(Command.SERIAL_TRIGGER, build_serial_trigger_payload(serial_config))
