from __future__ import annotations

from .capture import SamplingParameters, build_parameter_setting_payload
from .errors import ProtocolError
from .protocol import Command, build_transport_frame
from .pwm import build_pwm_start_payload, build_pwm_stop_payload
from .usb import UsbBackend


class AtkDevice:
    def __init__(self, backend: UsbBackend) -> None:
        self.backend = backend
        self.last_response = b""

    def _send_command(self, command: Command, payload: bytes = b"") -> bytes:
        frame = build_transport_frame(command, payload)
        self.last_response = self.backend.send_frame(frame)
        return frame

    def get_device_data_frame(self) -> bytes:
        return build_transport_frame(Command.GET_DEVICE_DATA, b"")

    def get_device_data(self) -> bytes:
        return self.backend.send_frame(self.get_device_data_frame())

    def stop(self, channel: int | None = None) -> bytes:
        if channel is None:
            payload = b""
        else:
            if not isinstance(channel, int) or not 0 <= channel <= 127:
                raise ProtocolError(f"stop channel must be in range 0..127, got {channel!r}")
            payload = bytes((channel,))
        return self._send_command(Command.STOP, payload)

    def pwm_start(self, channel: int, frequency_hz: int, duty_percent: float) -> bytes:
        return self._send_command(Command.PWM, build_pwm_start_payload(channel, frequency_hz, duty_percent))

    def pwm_stop(self, channel: int) -> bytes:
        return self._send_command(Command.PWM, build_pwm_stop_payload(channel))


    def configure_sampling(self, params: SamplingParameters) -> bytes:
        return self._send_command(Command.PARAMETER_SETTING, build_parameter_setting_payload(params))

    def parameter_setting_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.PARAMETER_SETTING, payload)

    def simple_trigger_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.SIMPLE_TRIGGER, payload)

    def stage_trigger_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.STAGE_TRIGGER, payload)

    def serial_trigger_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.SERIAL_TRIGGER, payload)
