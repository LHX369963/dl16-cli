from __future__ import annotations

import time
from collections.abc import Callable

from .capture import SamplingParameters, build_parameter_setting_payload
from .errors import ProtocolError
from .errors import UsbBackendError
from .firmware import build_get_mcu_version_frame
from .protocol import Command, build_transport_frame
from .pwm import build_pwm_start_payload, build_pwm_stop_payload
from .trigger import (
    SerialTriggerConfig,
    StageCondition,
    TriggerState,
    build_serial_trigger_payload,
    build_simple_trigger_payload,
    build_stage_trigger_payload,
)
from .usb import UsbBackend


class AtkDevice:
    def __init__(self, backend: UsbBackend) -> None:
        self.backend = backend
        self.last_response = b""

    def _send_command(self, command: Command, payload: bytes = b"") -> bytes:
        frame = build_transport_frame(command, payload)
        self.last_response = self.backend.send_frame(frame)
        return frame

    def _write_command(self, command: Command, payload: bytes = b"") -> bytes:
        frame = build_transport_frame(command, payload)
        self.backend.write_frame(frame)
        self.last_response = b""
        return frame

    def get_device_data_frame(self) -> bytes:
        return build_transport_frame(Command.GET_DEVICE_DATA, b"")

    def get_device_data(self) -> bytes:
        return self.backend.send_frame(self.get_device_data_frame())

    def initialize_connection(
        self, *, sleep_fn: Callable[[float], None] = time.sleep
    ) -> bytes:
        recover = getattr(self.backend, "recover_ffcc_link", None)
        if callable(recover):
            recover()
        sleep_fn(0.4)

        mcu_response: bytes | None = None
        for attempt in range(6):
            self.backend.write_chunk(build_get_mcu_version_frame(), timeout_ms=500)
            for _ in range(16):
                try:
                    response = self.backend.read_chunk(size=512, timeout_ms=100)
                except UsbBackendError:
                    break
                if response.startswith(b"\x0a\x81"):
                    mcu_response = response
                    break
                if not response:
                    break
            if mcu_response is not None:
                break
            if attempt < 5:
                sleep_fn(0.05)
        if mcu_response is None:
            raise UsbBackendError("DL16 MCU did not answer after USB link recovery")

        for index in (0, 1):
            self.backend.write_chunk(
                bytes((0x0A, 0x87, index, 0x0B)).ljust(510, b"\x00"), timeout_ms=500
            )
        fpga_responses = 0
        for _ in range(32):
            try:
                response = self.backend.read_chunk(size=512, timeout_ms=100)
            except UsbBackendError:
                break
            if response.startswith(b"\x0a\x87"):
                fpga_responses += 1
                if fpga_responses == 2:
                    break
            if not response:
                break
        if fpga_responses != 2:
            raise UsbBackendError("DL16 FPGA information handshake was incomplete")

        response = self.get_device_data()
        if b"DL16" not in response:
            raise UsbBackendError("DL16 device information response was not valid")
        return response

    def stop(self, channel: int | None = None) -> bytes:
        if channel is None:
            payload = b""
        else:
            if not isinstance(channel, int) or not 0 <= channel <= 127:
                raise ProtocolError(f"stop channel must be in range 0..127, got {channel!r}")
            payload = bytes((channel,))
        return self._send_command(Command.STOP, payload)

    def stop_no_response(self, channel: int | None = None) -> bytes:
        if channel is None:
            payload = b""
        else:
            if not isinstance(channel, int) or not 0 <= channel <= 127:
                raise ProtocolError(f"stop channel must be in range 0..127, got {channel!r}")
            payload = bytes((channel,))
        return self._write_command(Command.STOP, payload)

    def pwm_start(self, channel: int, frequency_hz: int, duty_percent: float) -> bytes:
        return self._send_command(Command.PWM, build_pwm_start_payload(channel, frequency_hz, duty_percent))

    def pwm_stop(self, channel: int) -> bytes:
        return self._send_command(Command.PWM, build_pwm_stop_payload(channel))


    def configure_sampling(self, params: SamplingParameters) -> bytes:
        return self._send_command(Command.PARAMETER_SETTING, build_parameter_setting_payload(params))

    def configure_sampling_no_response(self, params: SamplingParameters) -> bytes:
        return self._write_command(Command.PARAMETER_SETTING, build_parameter_setting_payload(params))

    def parameter_setting_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.PARAMETER_SETTING, payload)


    def configure_simple_trigger(
        self,
        states: list[TriggerState],
        *,
        enabled: list[bool] | None = None,
        collect_type: int = 1,
        channel_offset: int = 0,
    ) -> bytes:
        payload = build_simple_trigger_payload(
            states, enabled=enabled, collect_type=collect_type, channel_offset=channel_offset
        )
        return self._send_command(Command.SIMPLE_TRIGGER, payload)

    def configure_simple_trigger_no_response(
        self,
        states: list[TriggerState],
        *,
        enabled: list[bool] | None = None,
        collect_type: int = 1,
        channel_offset: int = 0,
    ) -> bytes:
        payload = build_simple_trigger_payload(
            states, enabled=enabled, collect_type=collect_type, channel_offset=channel_offset
        )
        return self._write_command(Command.SIMPLE_TRIGGER, payload)

    def configure_stage_trigger(
        self,
        stages: list[StageCondition],
        *,
        trigger_level: int,
        enabled: list[bool] | None = None,
        channel_offset: int = 0,
    ) -> bytes:
        payload = build_stage_trigger_payload(
            stages, trigger_level=trigger_level, enabled=enabled, channel_offset=channel_offset
        )
        return self._send_command(Command.STAGE_TRIGGER, payload)

    def configure_serial_trigger(self, config: SerialTriggerConfig) -> bytes:
        return self._send_command(Command.SERIAL_TRIGGER, build_serial_trigger_payload(config))

    def simple_trigger_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.SIMPLE_TRIGGER, payload)

    def stage_trigger_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.STAGE_TRIGGER, payload)

    def serial_trigger_raw(self, payload: bytes) -> bytes:
        return self._send_command(Command.SERIAL_TRIGGER, payload)
