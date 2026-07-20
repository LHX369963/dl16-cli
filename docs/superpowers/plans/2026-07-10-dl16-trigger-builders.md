# DL16 Trigger Builder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement recovered simple, staged, and serial trigger payload builders plus CLI commands.

**Architecture:** Centralize two-channel nibble packing in `trigger.py`. Simple trigger accepts comma-separated states; stage and serial triggers accept explicit JSON files matching recovered fields.

**Tech Stack:** Python 3.10+, dataclasses, enum, JSON, pytest.

## State encoding

| State | Nibble |
|---|---:|
| null / don't-care | `0x7` |
| rising | `0x1` |
| high | `0x4` |
| falling | `0x2` |
| low | `0x0` |
| double | `0x3` |
| disabled channel | `0x0` |

First channel in each pair occupies the high nibble.

## Payloads

Simple:

```text
packed channel states
byte: collect_type == 2
byte: collect_type == 3
```

Stage, repeated per stage:

```text
stage number (1-based)
triggerLevel
counter uint16 little-endian
0x00 if contiguous else 0x40
packed channel states
```

Serial:

```text
valueChannel + channelOffset
valueWidth
valueData uint16 little-endian
timeChannel + channelOffset
timeEdge
packed start conditions
packed stop conditions
```

---

### Task 1: State packing and simple trigger

Files: `dl16_cli/trigger.py`, `tests/test_trigger.py`

- [ ] Write failing tests for all nibble codes, disabled masks, channel offset padding, and simple trailer bytes.
- [ ] Implement enum/parser/packer/simple builder.
- [ ] Run targeted/full tests and commit.

### Task 2: Stage and serial builders

Files: `dl16_cli/trigger.py`, `tests/test_trigger.py`

- [ ] Write failing tests for exact stage and serial payload layouts and validation.
- [ ] Implement dataclasses and builders.
- [ ] Run targeted/full tests and commit.

### Task 3: CLI integration

Files: `dl16_cli/cli.py`, `tests/test_cli.py`

- [ ] Add failing tests for `trigger simple`, `trigger stage --file`, and `trigger serial --file` dry-run paths.
- [ ] Implement JSON loading and device command dispatch.
- [ ] Run targeted/full tests and commit.

### Task 4: Documentation

Files: `docs/protocol/protocol.md`, `docs/protocol/evidence-summary.md`

- [ ] Record state map, payload layouts, JSON schemas, and evidence addresses.
- [ ] Run full tests and representative dry-runs.
- [ ] Commit docs.
