---
name: dl16-cli
description: Operate, test, debug, or document the ATK DL16 logic analyzer through the public atkdl16 CLI, including PWM, Stream/Buffer/RLE capture, triggers, persistent sessions, measurement, search, filtering, export, and protocol decoding. Use for DL16 hardware work, atkdl16 command changes, connected validation, capture analysis, or deployment of this CLI; do not apply it to DL32 or other models.
---

# DL16 CLI

## Establish Context

Resolve the repository as the directory two levels above this Skill's real path. Do not assume the current working directory. Read `README.md` before operating hardware. Read `docs/protocol/protocol.md`, `docs/protocol/evidence-summary.md`, and the latest `docs/acceptance-*.md` only when the task needs protocol or validation detail.

Treat DL16 as the only supported model. Do not infer DL32 behavior from shared vendor documentation.

## Use The Public CLI

Use `atkdl16` for device work. Prefer the repository's `.venv/bin/atkdl16` when present, otherwise use the PATH entry point. Inspect `atkdl16 <command> --help` before using unfamiliar parameters.

Do not call `atkdl16_cli` Python internals, libusb, or raw protocol functions when a CLI workflow exists. Never issue the USB `SET_CONFIGURATION` operation; the project intentionally avoids it because it breaks the DL16 link.

Start diagnosis with:

```bash
atkdl16 --dry-run list
atkdl16 list
atkdl16 info
```

Use `capture run` for finite Stream/Buffer/RLE acquisition and `capture stream` for incremental long-running capture. Let the CLI choose `--sample-index` unless investigating the mapping itself. Respect the channel/rate limits in `README.md`.

Use `atkdl16 session` for workflows that configure multiple PWM outputs and then capture. Separate CLI processes reinitialize USB/FPGA state. JSONL is the session transport, not a replacement for the CLI.

## Protect Data And Hardware State

Do not overwrite an existing capture directory unless the user explicitly requests replacement; use a new output directory by default. Preserve `manifest.json`, `wire.bin`, and channel files as one capture unit.

Use bounded durations and trigger timeouts for unattended hardware tests. On failure or completion, stop PWM channels enabled by the task and stop active streaming. Preserve partial aligned Stream data after an intentional interrupt.

Do not claim GUI parity, untested protocol behavior, accuracy, or another model's capability. Separate hardware evidence from unit-test coverage.

## Verify Changes

Run the repository test suite after code changes:

```bash
python -m pytest -q
```

Scale connected tests to the change. Confirm device identity first, use documented loopback wiring, retain exact commands/results, and restore PWM/capture state afterward.
