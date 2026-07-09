# ATK DL16 Raw Command CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the recovered command IDs for `ParameterSetting`, `SimpleTrigger`, `StageTrigger`, and `SerialTrigger` as raw-payload CLI commands so hardware experiments can proceed before all payload semantics are decoded.

**Architecture:** Add strict hex parsing and generic command sending to the existing protocol/device/CLI layers. Keep all semantics explicit: these commands accept bytes, not high-level sampling/trigger options.

**Tech Stack:** Python 3.10+, pytest.

## Global Constraints

- Command IDs are the already recovered values: `0x11`, `0x12`, `0x13`, `0x14`.
- Raw payloads are hex strings with optional whitespace; invalid hex fails closed.
- Dry-run mode prints frames and never sends USB traffic.
- Non-dry-run mode sends exactly one frame and prints one response packet.
- High-level capture/trigger semantics remain undocumented until separately recovered.

---

### Task 1: Hex payload parsing

Files: `atkdl16_cli/protocol.py`, `tests/test_protocol.py`

- [ ] Add tests for `parse_hex_payload("11 22 aa") == b"\x11\x22\xaa"`, empty string as `b""`, and malformed odd/non-hex values raising `ProtocolError`.
- [ ] Run targeted tests and confirm failure.
- [ ] Implement `parse_hex_payload(text: str) -> bytes`.
- [ ] Run targeted and full tests; commit.

### Task 2: Device raw command methods

Files: `atkdl16_cli/device.py`, `tests/test_device.py`

- [ ] Add tests for `parameter_setting_raw`, `simple_trigger_raw`, `stage_trigger_raw`, and `serial_trigger_raw` sending the expected command frames.
- [ ] Run targeted tests and confirm failure.
- [ ] Implement methods that call `_send_command()` with the correct `Command` enum.
- [ ] Run targeted and full tests; commit.

### Task 3: CLI raw command group

Files: `atkdl16_cli/cli.py`, `tests/test_cli.py`

- [ ] Add dry-run CLI tests for `raw parameter-setting --payload-hex`, `raw simple-trigger`, `raw stage-trigger`, and `raw serial-trigger`.
- [ ] Add non-dry-run fake backend test for one raw command.
- [ ] Run targeted tests and confirm failure.
- [ ] Implement `raw` subcommands and response/frame printing.
- [ ] Run targeted and full tests; commit.

### Task 4: Documentation and verification

Files: `docs/protocol/protocol.md`, `docs/protocol/evidence-summary.md`

- [ ] Document raw command CLI syntax and warnings.
- [ ] Append the `Session::OrderStart` xref evidence location to evidence summary.
- [ ] Run full tests and representative dry-run raw command.
- [ ] Commit docs.
