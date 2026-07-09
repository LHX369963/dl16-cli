# ATK DL16 Hardware USB Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real, optional USB backend that can discover supported devices, open interface 0, resolve endpoints, and safely send already-implemented low-risk command frames (`info`, `stop`, `pwm`) while preserving dry-run tests without hardware.

**Architecture:** Keep protocol construction pure and tested. Add a `PyUsbBackend` behind the existing `UsbBackend` interface with dependency injection so unit tests use fake USB objects. CLI non-dry-run mode selects the real backend only when the optional `usb` module is installed and a supported device is available.

**Tech Stack:** Python 3.10+, standard library, optional `pyusb>=1.2`, pytest. No mandatory hardware is required for unit tests.

## Global Constraints

- Supported USB IDs remain exactly `1a86:ffcc`, `1a86:6a6b`, and `04b4:6a6a`.
- Real USB backend claims interface 0, matching `logic_analyzer_open` evidence.
- Real USB backend must detach kernel driver where supported before claiming interface 0.
- Endpoint selection must inspect descriptors and prefer OUT endpoint for writes, IN endpoint for reads; it must not rely only on recovered constants.
- Firmware flashing remains disabled.
- Capture and trigger command payload generation remain out of this plan.
- Unit tests must not require physical hardware.

---

## File Structure

- Modify `pyproject.toml`: add optional `usb = ["pyusb>=1.2"]` extra.
- Modify `atkdl16_cli/usb.py`: add `PyUsbBackend`, endpoint helpers, optional import handling, and open/close/send behavior.
- Modify `atkdl16_cli/device.py`: add `get_device_data()` send path that returns response bytes.
- Modify `atkdl16_cli/cli.py`: enable non-dry-run `list`, `info`, `stop`, `pwm start`, `pwm stop`; add `--vid-pid` and `--timeout-ms` global options.
- Create `tests/test_usb_backend.py`: fake pyusb objects and backend tests.
- Modify `tests/test_cli.py`: non-dry-run CLI tests through monkeypatched backend factory.
- Modify `docs/protocol/protocol.md`: document hardware backend behavior and limitations.

---

### Task 1: Optional pyusb dependency and USB ID parsing

**Files:**
- Modify: `pyproject.toml`
- Modify: `atkdl16_cli/usb.py`
- Test: `tests/test_usb_backend.py`

**Interfaces:**
- Produces: `parse_usb_id(text: str) -> tuple[int, int]`
- Produces: `is_supported_usb_id(vid: int, pid: int) -> bool`
- Produces: `PyUsbUnavailableError(UsbBackendError)`

Steps:

- [ ] Write tests for parsing `1a86:ffcc`, rejecting malformed IDs, and checking supported IDs.
- [ ] Run `python3 -m pytest tests/test_usb_backend.py -v`; expect missing functions/import failure.
- [ ] Add optional dependency group `usb = ["pyusb>=1.2"]` to `pyproject.toml`.
- [ ] Implement `parse_usb_id`, `is_supported_usb_id`, and `PyUsbUnavailableError` in `atkdl16_cli/usb.py`.
- [ ] Run `python3 -m pytest tests/test_usb_backend.py -v`; expect pass.
- [ ] Run `python3 -m pytest -v`; expect pass.
- [ ] Commit with `feat: add USB backend parsing helpers`.

### Task 2: Descriptor-driven PyUsbBackend discovery and endpoint selection

**Files:**
- Modify: `atkdl16_cli/usb.py`
- Test: `tests/test_usb_backend.py`

**Interfaces:**
- Produces: `PyUsbBackend(device=None, usb_core=None, usb_util=None, timeout_ms: int = 1000, vid_pid: tuple[int, int] | None = None)`
- Produces: `PyUsbBackend.list_devices() -> list[DeviceInfo]`
- Produces: `PyUsbBackend.open() -> None`
- Produces: `PyUsbBackend.close() -> None`

Steps:

- [ ] Add fake USB core/util classes in tests with supported and unsupported fake devices.
- [ ] Write tests that `list_devices()` returns only supported devices.
- [ ] Write tests that `open()` selects an OUT endpoint and an IN endpoint from fake interface descriptors.
- [ ] Write tests that `open()` calls detach kernel driver and claim interface 0 when methods are available.
- [ ] Run `python3 -m pytest tests/test_usb_backend.py -v`; expect missing `PyUsbBackend` behavior failures.
- [ ] Implement descriptor walking and endpoint selection in `PyUsbBackend`.
- [ ] Run targeted and full tests; expect pass.
- [ ] Commit with `feat: add descriptor-driven pyusb backend`.

### Task 3: Real backend send/read boundary and device facade info command

**Files:**
- Modify: `atkdl16_cli/usb.py`
- Modify: `atkdl16_cli/device.py`
- Test: `tests/test_usb_backend.py`
- Test: `tests/test_device.py`

**Interfaces:**
- Produces: `PyUsbBackend.send_frame(frame: bytes) -> bytes`
- Produces: `AtkDevice.get_device_data() -> bytes`

Steps:

- [ ] Write fake endpoint tests proving `send_frame()` writes the exact bytes and reads a response when an IN endpoint exists.
- [ ] Write device test proving `get_device_data()` sends the `GET_DEVICE_DATA` frame through backend.
- [ ] Run targeted tests; expect missing behavior failures.
- [ ] Implement `send_frame()` using endpoint `.write(frame, timeout=timeout_ms)` and optional `.read(max_packet_size, timeout=timeout_ms)`.
- [ ] Implement `AtkDevice.get_device_data()`.
- [ ] Run targeted and full tests; expect pass.
- [ ] Commit with `feat: send frames through pyusb backend`.

### Task 4: CLI non-dry-run backend selection

**Files:**
- Modify: `atkdl16_cli/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `create_backend(dry_run: bool, vid_pid: tuple[int, int] | None, timeout_ms: int) -> UsbBackend`
- CLI global options: `--vid-pid VID:PID`, `--timeout-ms N`

Steps:

- [ ] Write CLI tests using monkeypatch to replace `create_backend` with a fake backend for non-dry-run `info`, `stop`, and `pwm` commands.
- [ ] Run `python3 -m pytest tests/test_cli.py -v`; expect missing factory/option failures.
- [ ] Implement `create_backend`, `--vid-pid`, `--timeout-ms`, and non-dry-run command paths.
- [ ] Ensure non-dry-run `list` uses backend `list_devices()` and does not send frames.
- [ ] Run targeted and full tests; expect pass.
- [ ] Commit with `feat: enable non-dry-run CLI backend selection`.

### Task 5: Documentation and final verification

**Files:**
- Modify: `docs/protocol/protocol.md`

Steps:

- [ ] Document pyusb extra installation: `python3 -m pip install -e '.[usb]'`.
- [ ] Document that only `info`, `stop`, and `pwm` are wired to hardware in this stage.
- [ ] Document that capture, triggers, and firmware remain unavailable pending protocol recovery.
- [ ] Run `python3 -m pytest -v`; expect pass.
- [ ] Run `python3 -m atkdl16_cli.cli --dry-run list`; expect the three supported IDs.
- [ ] Run `python3 -m atkdl16_cli.cli --dry-run pwm start --channel 0 --freq 1000 --duty 50`; expect a `PWM_START frame` line.
- [ ] Run `git status --short`; expect no tracked modifications after commit.
- [ ] Commit with `docs: document pyusb backend stage`.

