from atkdl16_cli.device import AtkDevice
from atkdl16_cli.protocol import Command, build_transport_frame
from atkdl16_cli.pwm import build_pwm_start_payload, build_pwm_stop_payload
from atkdl16_cli.usb import DeviceInfo, DryRunBackend


def test_dry_run_backend_lists_configured_devices():
    backend = DryRunBackend(devices=[DeviceInfo(vid=0x1A86, pid=0xFFCC, bus=1, address=2, path="1-2", speed="high")])
    assert backend.list_devices() == [DeviceInfo(vid=0x1A86, pid=0xFFCC, bus=1, address=2, path="1-2", speed="high")]


def test_device_pwm_start_sends_expected_transport_frame():
    backend = DryRunBackend()
    device = AtkDevice(backend)
    frame = device.pwm_start(channel=0, frequency_hz=1_000, duty_percent=50)
    expected = build_transport_frame(Command.PWM, build_pwm_start_payload(0, 1_000, 50))
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_device_pwm_stop_sends_expected_transport_frame():
    backend = DryRunBackend()
    device = AtkDevice(backend)
    frame = device.pwm_stop(channel=3)
    expected = build_transport_frame(Command.PWM, build_pwm_stop_payload(3))
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_device_stop_without_channel_sends_empty_stop_payload():
    backend = DryRunBackend()
    device = AtkDevice(backend)
    frame = device.stop()
    expected = build_transport_frame(Command.STOP, b"")
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_device_stop_with_channel_sends_one_byte_payload():
    backend = DryRunBackend()
    device = AtkDevice(backend)
    frame = device.stop(channel=2)
    expected = build_transport_frame(Command.STOP, b"\x02")
    assert frame == expected
    assert backend.sent_frames == [expected]


def test_get_device_data_frame_is_built_without_sending():
    backend = DryRunBackend()
    device = AtkDevice(backend)
    frame = device.get_device_data_frame()
    assert frame == build_transport_frame(Command.GET_DEVICE_DATA, b"")
    assert backend.sent_frames == []


def test_get_device_data_sends_query_frame():
    backend = DryRunBackend()
    device = AtkDevice(backend)
    response = device.get_device_data()
    expected = build_transport_frame(Command.GET_DEVICE_DATA, b"")
    assert response == b""
    assert backend.sent_frames == [expected]


def test_raw_parameter_and_trigger_methods_send_expected_frames():
    backend = DryRunBackend()
    device = AtkDevice(backend)
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
