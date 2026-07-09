# ATK DL16 Protocol Core and PWM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first tested CLI/library foundation for ATK DL16 reverse engineering: command constants, frame encoding, CRC hooks, USB discovery data structures, dry-run command output, and PWM payload generation.

**Architecture:** Implement a small Python package with pure packet builders first, then a CLI that can run in `--dry-run` mode without hardware. Hardware USB operations are represented by a narrow backend interface so later capture, trigger, and firmware plans can add real libusb behavior without changing the packet builders.

**Tech Stack:** Python 3.10+, standard library, `pytest` for tests, optional future `pyusb` dependency not required by this plan.

## Global Constraints

- Source package evidence is `ATK-Logic_1.1.2.0_amd64.deb` and the generated files under `reverse/`.
- Initial supported USB IDs are exactly `1a86:ffcc`, `1a86:6a6b`, and `04b4:6a6a`.
- Command IDs are exactly `0x10 GetDeviceData`, `0x11 ParameterSetting`, `0x12 SimpleTrigger`, `0x13 StageTrigger`, `0x14 SerialTrigger`, `0x15 Stop`, and `0x17 PWM`.
- Normal command inner frame is `cmd, payload_len + 1, payload...`.
- Normal command outer frame is `8 zero bytes, 0x0a, inner, crc32(inner), 0x0b`.
- CRC byte order remains a named parameter until verified from `gCRC32` or USB traces.
- Firmware flashing is out of this first implementation plan and must remain unavailable from the CLI in this plan.
- No command in this plan sends USB traffic unless the user explicitly avoids `--dry-run` and a later plan has added a real backend.

---

## File Structure

- Create `pyproject.toml`: package metadata, console script, pytest configuration.
- Create `atkdl16_cli/__init__.py`: package version export.
- Create `atkdl16_cli/errors.py`: typed exceptions.
- Create `atkdl16_cli/protocol.py`: command IDs, USB IDs, CRC32 function, inner/outer frame builders.
- Create `atkdl16_cli/pwm.py`: PWM start/stop payload builders.
- Create `atkdl16_cli/usb.py`: backend interface, dry-run backend, device ID parsing.
- Create `atkdl16_cli/device.py`: high-level facade for packet creation and backend send boundary.
- Create `atkdl16_cli/cli.py`: argparse CLI with `list`, `info`, `stop`, and `pwm` dry-run behavior.
- Create `tests/test_protocol.py`: protocol unit tests.
- Create `tests/test_pwm.py`: PWM unit tests.
- Create `tests/test_cli.py`: CLI dry-run tests.
- Modify `docs/protocol/protocol.md`: stable notes for implemented fields.

---

### Task 1: Project scaffold and importable package

**Files:**
- Create: `pyproject.toml`
- Create: `atkdl16_cli/__init__.py`
- Create: `atkdl16_cli/errors.py`
- Test: `tests/test_imports.py`

**Interfaces:**
- Produces: `atkdl16_cli.__version__: str`
- Produces: `AtkDl16Error`, `ProtocolError`, `UsbBackendError` exception classes
- Consumes: none

- [ ] **Step 1: Write the failing import test**

Create `tests/test_imports.py`:

```python
from atkdl16_cli import __version__
from atkdl16_cli.errors import AtkDl16Error, ProtocolError, UsbBackendError


def test_package_exports_version_string():
    assert isinstance(__version__, str)
    assert __version__


def test_error_hierarchy():
    assert issubclass(ProtocolError, AtkDl16Error)
    assert issubclass(UsbBackendError, AtkDl16Error)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_imports.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'atkdl16_cli'`.

- [ ] **Step 3: Create package metadata**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "atkdl16-cli"
version = "0.1.0"
description = "Command-line reverse-engineered control utility for ATK DL16 logic analyzer"
requires-python = ">=3.10"
dependencies = []

[project.optional-dependencies]
test = ["pytest>=8"]

[project.scripts]
atkdl16 = "atkdl16_cli.cli:main"

[tool.pytest.ini_options]
addopts = "-q"
testpaths = ["tests"]
```

- [ ] **Step 4: Create package files**

Create `atkdl16_cli/__init__.py`:

```python
"""ATK DL16 command-line reverse-engineering package."""

__version__ = "0.1.0"
```

Create `atkdl16_cli/errors.py`:

```python
class AtkDl16Error(Exception):
    """Base exception for atkdl16-cli."""


class ProtocolError(AtkDl16Error):
    """Raised when a command payload or protocol frame is invalid."""


class UsbBackendError(AtkDl16Error):
    """Raised when the selected USB backend cannot complete an operation."""
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_imports.py -v
```

Expected: PASS, 2 tests passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml atkdl16_cli/__init__.py atkdl16_cli/errors.py tests/test_imports.py
git commit -m "feat: scaffold atkdl16 cli package"
```

---

### Task 2: Protocol constants, CRC, and frame builders

**Files:**
- Create: `atkdl16_cli/protocol.py`
- Test: `tests/test_protocol.py`

**Interfaces:**
- Consumes: `ProtocolError` from `atkdl16_cli.errors`
- Produces: `SUPPORTED_USB_IDS: tuple[UsbId, ...]`
- Produces: `Command` enum with values `GET_DEVICE_DATA=0x10`, `PARAMETER_SETTING=0x11`, `SIMPLE_TRIGGER=0x12`, `STAGE_TRIGGER=0x13`, `SERIAL_TRIGGER=0x14`, `STOP=0x15`, `PWM=0x17`
- Produces: `crc32_atk(data: bytes) -> int`
- Produces: `crc32_bytes(value: int, byteorder: Literal["little", "big"] = "little") -> bytes`
- Produces: `build_inner_frame(command: int | Command, payload: bytes = b"") -> bytes`
- Produces: `build_transport_frame(command: int | Command, payload: bytes = b"", crc_byteorder: Literal["little", "big"] = "little") -> bytes`

- [ ] **Step 1: Write failing protocol tests**

Create `tests/test_protocol.py`:

```python
import binascii

import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.protocol import (
    Command,
    SUPPORTED_USB_IDS,
    UsbId,
    build_inner_frame,
    build_transport_frame,
    crc32_atk,
    crc32_bytes,
)


def test_supported_usb_ids_match_reverse_evidence():
    assert SUPPORTED_USB_IDS == (
        UsbId(0x1A86, 0xFFCC),
        UsbId(0x1A86, 0x6A6B),
        UsbId(0x04B4, 0x6A6A),
    )


def test_command_values_match_reverse_evidence():
    assert Command.GET_DEVICE_DATA == 0x10
    assert Command.PARAMETER_SETTING == 0x11
    assert Command.SIMPLE_TRIGGER == 0x12
    assert Command.STAGE_TRIGGER == 0x13
    assert Command.SERIAL_TRIGGER == 0x14
    assert Command.STOP == 0x15
    assert Command.PWM == 0x17


def test_crc32_uses_standard_seed_until_binary_vector_is_recovered():
    assert crc32_atk(b"\x17\x0a\x11") == binascii.crc32(b"\x17\x0a\x11") & 0xFFFFFFFF


def test_crc32_bytes_supports_explicit_byte_order():
    assert crc32_bytes(0x12345678, "little") == bytes.fromhex("78563412")
    assert crc32_bytes(0x12345678, "big") == bytes.fromhex("12345678")


def test_inner_frame_contains_command_length_and_payload():
    assert build_inner_frame(Command.PWM, bytes.fromhex("110100000001000000")) == bytes.fromhex(
        "170a110100000001000000"
    )


def test_transport_frame_wraps_inner_frame_with_padding_markers_and_crc():
    inner = bytes.fromhex("170a110100000001000000")
    expected_crc = crc32_bytes(crc32_atk(inner), "little")
    frame = build_transport_frame(Command.PWM, bytes.fromhex("110100000001000000"))
    assert frame[:8] == b"\x00" * 8
    assert frame[8] == 0x0A
    assert frame[9 : 9 + len(inner)] == inner
    assert frame[9 + len(inner) : 13 + len(inner)] == expected_crc
    assert frame[-1] == 0x0B
    assert len(frame) == len(inner) + 15


def test_inner_frame_rejects_payloads_too_large_for_one_byte_length():
    with pytest.raises(ProtocolError, match="payload too long"):
        build_inner_frame(Command.PWM, bytes(255))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_protocol.py -v
```

Expected: FAIL with `ModuleNotFoundError` or missing names from `atkdl16_cli.protocol`.

- [ ] **Step 3: Implement protocol module**

Create `atkdl16_cli/protocol.py`:

```python
from __future__ import annotations

import binascii
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

from .errors import ProtocolError


@dataclass(frozen=True, order=True)
class UsbId:
    vid: int
    pid: int

    def __post_init__(self) -> None:
        if not 0 <= self.vid <= 0xFFFF:
            raise ProtocolError(f"USB VID out of range: {self.vid!r}")
        if not 0 <= self.pid <= 0xFFFF:
            raise ProtocolError(f"USB PID out of range: {self.pid!r}")

    def __str__(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"


SUPPORTED_USB_IDS: tuple[UsbId, ...] = (
    UsbId(0x1A86, 0xFFCC),
    UsbId(0x1A86, 0x6A6B),
    UsbId(0x04B4, 0x6A6A),
)


class Command(IntEnum):
    GET_DEVICE_DATA = 0x10
    PARAMETER_SETTING = 0x11
    SIMPLE_TRIGGER = 0x12
    STAGE_TRIGGER = 0x13
    SERIAL_TRIGGER = 0x14
    STOP = 0x15
    PWM = 0x17


def _command_byte(command: int | Command) -> int:
    value = int(command)
    if not 0 <= value <= 0xFF:
        raise ProtocolError(f"command out of range: {value!r}")
    return value


def crc32_atk(data: bytes) -> int:
    """Return the CRC32 used by the current prototype.

    The original binary calls a function named gCRC32. Until a recovered vector
    proves different seed/xor behavior, this function intentionally uses
    Python's standard CRC32 and masks to an unsigned 32-bit value.
    """

    return binascii.crc32(data) & 0xFFFFFFFF


def crc32_bytes(value: int, byteorder: Literal["little", "big"] = "little") -> bytes:
    if byteorder not in {"little", "big"}:
        raise ProtocolError(f"unsupported CRC byte order: {byteorder!r}")
    if not 0 <= value <= 0xFFFFFFFF:
        raise ProtocolError(f"CRC value out of range: {value!r}")
    return value.to_bytes(4, byteorder)


def build_inner_frame(command: int | Command, payload: bytes = b"") -> bytes:
    if not isinstance(payload, bytes):
        raise ProtocolError("payload must be bytes")
    length = len(payload) + 1
    if length > 0xFF:
        raise ProtocolError(f"payload too long for one-byte length: {len(payload)} bytes")
    return bytes((_command_byte(command), length)) + payload


def build_transport_frame(
    command: int | Command,
    payload: bytes = b"",
    crc_byteorder: Literal["little", "big"] = "little",
) -> bytes:
    inner = build_inner_frame(command, payload)
    crc = crc32_bytes(crc32_atk(inner), crc_byteorder)
    return (b"\x00" * 8) + b"\x0a" + inner + crc + b"\x0b"
```

- [ ] **Step 4: Run protocol tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_protocol.py -v
```

Expected: PASS, 7 tests passed.

- [ ] **Step 5: Run all tests**

Run:

```bash
python3 -m pytest -v
```

Expected: PASS, all current tests passed.

- [ ] **Step 6: Commit**

```bash
git add atkdl16_cli/protocol.py tests/test_protocol.py
git commit -m "feat: add ATK command frame builder"
```

---

### Task 3: PWM payload builder

**Files:**
- Create: `atkdl16_cli/pwm.py`
- Test: `tests/test_pwm.py`

**Interfaces:**
- Consumes: `ProtocolError` from `atkdl16_cli.errors`
- Produces: `PWM_BASE_HZ: int = 100_000_000`
- Produces: `build_pwm_start_payload(channel: int, frequency_hz: int, duty_percent: float, byteorder: Literal["little", "big"] = "little") -> bytes`
- Produces: `build_pwm_stop_payload(channel: int) -> bytes`

- [ ] **Step 1: Write failing PWM tests**

Create `tests/test_pwm.py`:

```python
import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.pwm import PWM_BASE_HZ, build_pwm_start_payload, build_pwm_stop_payload


def test_pwm_base_frequency_matches_reverse_evidence():
    assert PWM_BASE_HZ == 100_000_000


def test_pwm_start_payload_for_channel_zero_1khz_50_percent_little_endian():
    payload = build_pwm_start_payload(channel=0, frequency_hz=1_000, duty_percent=50)
    assert payload == bytes.fromhex("11a086010050c30000")


def test_pwm_start_payload_for_channel_three_10khz_25_percent_little_endian():
    payload = build_pwm_start_payload(channel=3, frequency_hz=10_000, duty_percent=25)
    assert payload == bytes.fromhex("4110270000c4090000")


def test_pwm_start_payload_supports_big_endian_for_verification_experiments():
    payload = build_pwm_start_payload(channel=0, frequency_hz=1_000, duty_percent=50, byteorder="big")
    assert payload == bytes.fromhex("11000186a00000c350")


def test_pwm_stop_payload_uses_channel_plus_one_shifted_nibble():
    assert build_pwm_stop_payload(0) == bytes.fromhex("10")
    assert build_pwm_stop_payload(3) == bytes.fromhex("40")


@pytest.mark.parametrize("channel", [-1, 16])
def test_pwm_rejects_invalid_channel(channel):
    with pytest.raises(ProtocolError, match="channel must be in range"):
        build_pwm_start_payload(channel=channel, frequency_hz=1_000, duty_percent=50)


@pytest.mark.parametrize("frequency", [0, -1, 100_000_001])
def test_pwm_rejects_invalid_frequency(frequency):
    with pytest.raises(ProtocolError, match="frequency_hz must be"):
        build_pwm_start_payload(channel=0, frequency_hz=frequency, duty_percent=50)


@pytest.mark.parametrize("duty", [-0.1, 100.1])
def test_pwm_rejects_invalid_duty(duty):
    with pytest.raises(ProtocolError, match="duty_percent must be"):
        build_pwm_start_payload(channel=0, frequency_hz=1_000, duty_percent=duty)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_pwm.py -v
```

Expected: FAIL with missing `atkdl16_cli.pwm`.

- [ ] **Step 3: Implement PWM module**

Create `atkdl16_cli/pwm.py`:

```python
from __future__ import annotations

from typing import Literal

from .errors import ProtocolError

PWM_BASE_HZ = 100_000_000


def _validate_channel(channel: int) -> None:
    if not isinstance(channel, int) or not 0 <= channel <= 15:
        raise ProtocolError(f"channel must be in range 0..15, got {channel!r}")


def _validate_byteorder(byteorder: str) -> None:
    if byteorder not in {"little", "big"}:
        raise ProtocolError(f"unsupported byte order: {byteorder!r}")


def build_pwm_start_payload(
    channel: int,
    frequency_hz: int,
    duty_percent: float,
    byteorder: Literal["little", "big"] = "little",
) -> bytes:
    _validate_channel(channel)
    _validate_byteorder(byteorder)
    if not isinstance(frequency_hz, int) or not 1 <= frequency_hz <= PWM_BASE_HZ:
        raise ProtocolError(f"frequency_hz must be an integer in range 1..{PWM_BASE_HZ}, got {frequency_hz!r}")
    if not isinstance(duty_percent, (int, float)) or not 0 <= float(duty_percent) <= 100:
        raise ProtocolError(f"duty_percent must be in range 0..100, got {duty_percent!r}")

    period_count = int(PWM_BASE_HZ / frequency_hz)
    duty_count = int(period_count * float(duty_percent) / 100.0)
    control = (channel << 4) | 0x11
    return bytes((control,)) + period_count.to_bytes(4, byteorder) + duty_count.to_bytes(4, byteorder)


def build_pwm_stop_payload(channel: int) -> bytes:
    _validate_channel(channel)
    return bytes(((channel + 1) << 4,))
```

- [ ] **Step 4: Run PWM tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_pwm.py -v
```

Expected: PASS, 12 tests passed.

- [ ] **Step 5: Run all tests**

Run:

```bash
python3 -m pytest -v
```

Expected: PASS, all current tests passed.

- [ ] **Step 6: Commit**

```bash
git add atkdl16_cli/pwm.py tests/test_pwm.py
git commit -m "feat: add PWM payload builder"
```

---

### Task 4: USB backend boundary and dry-run device facade

**Files:**
- Create: `atkdl16_cli/usb.py`
- Create: `atkdl16_cli/device.py`
- Test: `tests/test_device.py`

**Interfaces:**
- Consumes: `Command`, `UsbId`, `SUPPORTED_USB_IDS`, `build_transport_frame` from `atkdl16_cli.protocol`
- Consumes: PWM payload functions from `atkdl16_cli.pwm`
- Produces: `DeviceInfo` dataclass
- Produces: `UsbBackend` protocol with `list_devices() -> list[DeviceInfo]` and `send_frame(frame: bytes) -> bytes`
- Produces: `DryRunBackend` class
- Produces: `AtkDevice` class with `pwm_start`, `pwm_stop`, `stop`, `get_device_data_frame`

- [ ] **Step 1: Write failing device tests**

Create `tests/test_device.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_device.py -v
```

Expected: FAIL with missing `atkdl16_cli.device` or `atkdl16_cli.usb`.

- [ ] **Step 3: Implement USB backend boundary**

Create `atkdl16_cli/usb.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DeviceInfo:
    vid: int
    pid: int
    bus: int | None = None
    address: int | None = None
    path: str | None = None
    speed: str | None = None

    @property
    def usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"


class UsbBackend(Protocol):
    def list_devices(self) -> list[DeviceInfo]:
        raise NotImplementedError

    def send_frame(self, frame: bytes) -> bytes:
        raise NotImplementedError


class DryRunBackend:
    def __init__(self, devices: list[DeviceInfo] | None = None) -> None:
        self._devices = list(devices or [])
        self.sent_frames: list[bytes] = []

    def list_devices(self) -> list[DeviceInfo]:
        return list(self._devices)

    def send_frame(self, frame: bytes) -> bytes:
        self.sent_frames.append(bytes(frame))
        return b""
```

- [ ] **Step 4: Implement device facade**

Create `atkdl16_cli/device.py`:

```python
from __future__ import annotations

from .errors import ProtocolError
from .protocol import Command, build_transport_frame
from .pwm import build_pwm_start_payload, build_pwm_stop_payload
from .usb import UsbBackend


class AtkDevice:
    def __init__(self, backend: UsbBackend) -> None:
        self.backend = backend

    def _send_command(self, command: Command, payload: bytes = b"") -> bytes:
        frame = build_transport_frame(command, payload)
        self.backend.send_frame(frame)
        return frame

    def get_device_data_frame(self) -> bytes:
        return build_transport_frame(Command.GET_DEVICE_DATA, b"")

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
```

- [ ] **Step 5: Run device tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_device.py -v
```

Expected: PASS, 6 tests passed.

- [ ] **Step 6: Run all tests**

Run:

```bash
python3 -m pytest -v
```

Expected: PASS, all current tests passed.

- [ ] **Step 7: Commit**

```bash
git add atkdl16_cli/usb.py atkdl16_cli/device.py tests/test_device.py
git commit -m "feat: add dry-run USB device facade"
```

---

### Task 5: Dry-run CLI for list/info/stop/PWM

**Files:**
- Create: `atkdl16_cli/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `AtkDevice` from `atkdl16_cli.device`
- Consumes: `SUPPORTED_USB_IDS` from `atkdl16_cli.protocol`
- Consumes: `DeviceInfo`, `DryRunBackend` from `atkdl16_cli.usb`
- Produces: `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli.py`:

```python
from atkdl16_cli.cli import main


def test_cli_list_dry_run_prints_supported_ids(capsys):
    rc = main(["--dry-run", "list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1a86:ffcc" in out
    assert "1a86:6a6b" in out
    assert "04b4:6a6a" in out


def test_cli_info_dry_run_prints_get_device_data_frame(capsys):
    rc = main(["--dry-run", "info"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "GET_DEVICE_DATA" in out
    assert "00000000000000000a1001" in out


def test_cli_pwm_start_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "pwm", "start", "--channel", "0", "--freq", "1000", "--duty", "50"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PWM_START" in out
    assert "170a11a086010050c30000" in out


def test_cli_pwm_stop_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "pwm", "stop", "--channel", "3"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "PWM_STOP" in out
    assert "170240" in out


def test_cli_stop_dry_run_prints_frame(capsys):
    rc = main(["--dry-run", "stop", "--channel", "2"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "STOP" in out
    assert "150202" in out
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_cli.py -v
```

Expected: FAIL with missing `atkdl16_cli.cli`.

- [ ] **Step 3: Implement CLI module**

Create `atkdl16_cli/cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .device import AtkDevice
from .errors import AtkDl16Error
from .protocol import SUPPORTED_USB_IDS
from .usb import DeviceInfo, DryRunBackend


def _print_frame(label: str, frame: bytes) -> None:
    print(f"{label} frame: {frame.hex()}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atkdl16")
    parser.add_argument("--dry-run", action="store_true", help="print frames without accessing USB hardware")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list supported or attached devices")
    sub.add_parser("info", help="print device info query frame or query a device")

    stop = sub.add_parser("stop", help="send stop command")
    stop.add_argument("--channel", type=int, default=None)

    pwm = sub.add_parser("pwm", help="PWM commands")
    pwm_sub = pwm.add_subparsers(dest="pwm_command", required=True)
    pwm_start = pwm_sub.add_parser("start", help="start PWM")
    pwm_start.add_argument("--channel", type=int, required=True)
    pwm_start.add_argument("--freq", type=int, required=True)
    pwm_start.add_argument("--duty", type=float, required=True)
    pwm_stop = pwm_sub.add_parser("stop", help="stop PWM")
    pwm_stop.add_argument("--channel", type=int, required=True)

    return parser


def _dry_backend() -> DryRunBackend:
    devices = [DeviceInfo(vid=item.vid, pid=item.pid, path="supported-id", speed="unknown") for item in SUPPORTED_USB_IDS]
    return DryRunBackend(devices=devices)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.dry_run:
        parser.error("only --dry-run is available in this implementation plan")

    backend = _dry_backend()
    device = AtkDevice(backend)

    try:
        if args.command == "list":
            for info in backend.list_devices():
                print(f"{info.usb_id} path={info.path} speed={info.speed}")
            return 0

        if args.command == "info":
            _print_frame("GET_DEVICE_DATA", device.get_device_data_frame())
            return 0

        if args.command == "stop":
            _print_frame("STOP", device.stop(channel=args.channel))
            return 0

        if args.command == "pwm" and args.pwm_command == "start":
            _print_frame("PWM_START", device.pwm_start(args.channel, args.freq, args.duty))
            return 0

        if args.command == "pwm" and args.pwm_command == "stop":
            _print_frame("PWM_STOP", device.pwm_stop(args.channel))
            return 0

        parser.error(f"unsupported command combination: {args}")
        return 2
    except AtkDl16Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run CLI tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_cli.py -v
```

Expected: PASS, 5 tests passed.

- [ ] **Step 5: Run all tests**

Run:

```bash
python3 -m pytest -v
```

Expected: PASS, all current tests passed.

- [ ] **Step 6: Smoke-test CLI manually**

Run:

```bash
python3 -m atkdl16_cli.cli --dry-run pwm start --channel 0 --freq 1000 --duty 50
```

Expected output contains:

```text
PWM_START frame:
```

and contains the inner frame hex:

```text
170a11a086010050c30000
```

- [ ] **Step 7: Commit**

```bash
git add atkdl16_cli/cli.py tests/test_cli.py
git commit -m "feat: add dry-run CLI commands"
```

---

### Task 6: Implemented protocol documentation

**Files:**
- Create: `docs/protocol/protocol.md`
- Modify: `docs/protocol/evidence-summary.md`

**Interfaces:**
- Consumes: public functions and command behavior from Tasks 2-5
- Produces: user-readable protocol reference for implemented dry-run features

- [ ] **Step 1: Write protocol reference**

Create `docs/protocol/protocol.md`:

```markdown
# ATK DL16 Protocol Reference

Status: partially implemented and still under reverse engineering.

## Supported USB IDs

- `1a86:ffcc`
- `1a86:6a6b`
- `04b4:6a6a`

## Normal command inner frame

```text
byte 0: command
byte 1: payload length + 1
byte 2..: payload
```

## Normal command transport frame

```text
8 bytes: 00 00 00 00 00 00 00 00
1 byte : 0a
N bytes: inner frame
4 bytes: CRC32(inner frame), little-endian in the prototype
1 byte : 0b
```

The original binary function is named `gCRC32`. The prototype uses standard CRC32 until a recovered vector proves the exact original parameters.

## Implemented command IDs

| Command | Value | Implemented behavior |
|---|---:|---|
| `GET_DEVICE_DATA` | `0x10` | Dry-run frame generation |
| `STOP` | `0x15` | Dry-run frame generation with optional one-byte channel payload |
| `PWM` | `0x17` | Dry-run frame generation for start and stop payloads |

## PWM start payload

```text
byte 0   : (channel << 4) | 0x11
bytes 1-4: period_count, little-endian in the prototype
bytes 5-8: duty_count, little-endian in the prototype
```

```text
period_count = int(100_000_000 / frequency_hz)
duty_count = int(period_count * duty_percent / 100)
```

## PWM stop payload

```text
byte 0: (channel + 1) << 4
```

## Commands not implemented in the first plan

Capture, trigger, and firmware commands remain documented in `docs/protocol/evidence-summary.md` and are intentionally not exposed as sending commands by the dry-run CLI.
```

- [ ] **Step 2: Add implementation pointer to evidence summary**

Append to `docs/protocol/evidence-summary.md`:

```markdown

## Implemented prototype references

The first implementation plan turns the low-risk portions of this evidence into tested code:

- `atkdl16_cli.protocol` for USB IDs, command IDs, frame construction, and CRC32 byte conversion.
- `atkdl16_cli.pwm` for PWM start/stop payloads.
- `atkdl16_cli.device` and `atkdl16_cli.cli` for dry-run command frame generation.
```

- [ ] **Step 3: Verify documentation files exist and contain key terms**

Run:

```bash
grep -n "PWM start payload" docs/protocol/protocol.md
grep -n "Implemented prototype references" docs/protocol/evidence-summary.md
```

Expected output includes one matching line from each file.

- [ ] **Step 4: Run all tests**

Run:

```bash
python3 -m pytest -v
```

Expected: PASS, all tests passed.

- [ ] **Step 5: Commit**

```bash
git add docs/protocol/protocol.md docs/protocol/evidence-summary.md
git commit -m "docs: describe implemented protocol core"
```

---

### Task 7: Plan completion verification

**Files:**
- Modify: none unless verification exposes a defect

**Interfaces:**
- Consumes: all files created in Tasks 1-6
- Produces: verified foundation for the next implementation plan covering hardware USB backend and safe info/PWM hardware tests

- [ ] **Step 1: Run full unit test suite**

Run:

```bash
python3 -m pytest -v
```

Expected: PASS, all tests passed.

- [ ] **Step 2: Run package CLI dry-run list**

Run:

```bash
python3 -m atkdl16_cli.cli --dry-run list
```

Expected output contains exactly these USB ID substrings:

```text
1a86:ffcc
1a86:6a6b
04b4:6a6a
```

- [ ] **Step 3: Run package CLI dry-run PWM start**

Run:

```bash
python3 -m atkdl16_cli.cli --dry-run pwm start --channel 0 --freq 1000 --duty 50
```

Expected output contains:

```text
PWM_START frame:
```

and contains:

```text
170a11a086010050c30000
```

- [ ] **Step 4: Run package CLI dry-run stop**

Run:

```bash
python3 -m atkdl16_cli.cli --dry-run stop --channel 2
```

Expected output contains:

```text
STOP frame:
```

and contains:

```text
150202
```

- [ ] **Step 5: Check git status**

Run:

```bash
git status --short
```

Expected: no modified tracked files. Large reverse-engineering artifacts may remain untracked if intentionally excluded from commits.

