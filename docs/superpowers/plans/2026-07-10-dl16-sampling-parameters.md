# DL16 Sampling Parameter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the recovered 13-byte `ParameterSetting` payload and expose it through `capture configure` CLI.

**Architecture:** Add a pure builder in `capture.py`, call it through `Dl16Device`, and retain dry-run/non-dry-run behavior through existing backends.

**Tech Stack:** Python 3.10+, pytest.

## Recovered layout

```text
byte 0: bit7 RLE, bit6 Buffer
byte 1: threshold sign-magnitude in 0.1 V units; bit7 means negative
byte 2: settingData.index
bytes 3..7: sample depth, unsigned 40-bit little-endian
bytes 8..12: trigger sample position, unsigned 40-bit little-endian
```

Calculations matching `SessionController::start`:

```text
depth = int(set_time * (int(set_hz) // 1000))
trigger_sample = int((depth // 100) * trigger_position_percent)
```

Stream/collect type 3 rejects RLE and Buffer.

---

### Task 1: Pure payload builder

Files: `dl16_cli/capture.py`, `tests/test_capture.py`

- [ ] Write tests for flags, threshold encoding, little-endian 40-bit fields, validation, and stream incompatibility.
- [ ] Verify tests fail because module is absent.
- [ ] Implement `SamplingParameters` dataclass and `build_parameter_setting_payload()`.
- [ ] Run targeted/full tests and commit.

### Task 2: Device and CLI integration

Files: `dl16_cli/device.py`, `dl16_cli/cli.py`, `tests/test_device.py`, `tests/test_cli.py`

- [ ] Write tests for device sending command `0x11` and `capture configure` dry-run/non-dry-run behavior.
- [ ] Verify tests fail.
- [ ] Implement device and CLI paths.
- [ ] Run targeted/full tests and commit.

### Task 3: Evidence and docs

Files: `docs/protocol/evidence-summary.md`, `docs/protocol/protocol.md`

- [ ] Document field offsets, formulas, and disassembly addresses.
- [ ] Run full tests and a representative CLI dry-run.
- [ ] Commit documentation.
