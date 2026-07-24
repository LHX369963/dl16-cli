---
name: dl16-cli
description: Operate, test, debug, or document the DL16 logic analyzer through the public dl16 CLI, including PWM, Stream/Buffer/RLE capture, triggers, persistent sessions, measurement, search, filtering, export, and protocol decoding. Use for DL16 hardware work, dl16 command changes, connected validation, capture analysis, or deployment of this CLI; do not apply it to DL32 or other models.
---

# DL16 CLI

## Establish Context

Resolve the repository as the directory two levels above this Skill's real path. Do not assume the current working directory. Read `README.md` before operating hardware. Read `docs/protocol/protocol.md`, `docs/protocol/evidence-summary.md`, and the latest `docs/acceptance-*.md` only when the task needs protocol or validation detail.

Treat DL16 as the only supported model. Do not infer DL32 behavior from shared vendor documentation.

## Use The Public CLI

Use `dl16` for device work. Prefer the repository's `.venv/bin/dl16` when present, otherwise use the PATH entry point. Inspect `dl16 <command> --help` before using unfamiliar parameters.

Do not call `dl16_cli` Python internals, libusb, or raw protocol functions when a CLI workflow exists. Never issue the USB `SET_CONFIGURATION` operation; the project intentionally avoids it because it breaks the DL16 link.

Start diagnosis with:

```bash
dl16 --dry-run list
dl16 list
dl16 info
```

Use `capture run` for finite Stream/Buffer/RLE acquisition and `capture stream` for incremental long-running capture. Let the CLI choose `--sample-index` unless investigating the mapping itself. Respect the channel/rate limits in `README.md`.

Use `dl16 session` for workflows that configure multiple PWM outputs and then capture. Separate CLI processes reinitialize USB/FPGA state. JSONL is the session transport, not a replacement for the CLI.

## Protect Data And Hardware State

Do not overwrite an existing capture directory unless the user explicitly requests replacement; use a new output directory by default. Preserve `manifest.json`, `wire.bin`, and channel files as one capture unit.

Use bounded durations and trigger timeouts for unattended hardware tests. On failure or completion, stop PWM channels enabled by the task and stop active streaming. Preserve partial aligned Stream data after an intentional interrupt.

Do not claim GUI parity, untested protocol behavior, accuracy, or another model's capability. Separate hardware evidence from unit-test coverage.

## Handle CLI Failures Without Losing The Task

Report every CLI error to the user as soon as it occurs, including the failing command and immediate impact, but do not stop work solely because an error occurred. Keep the requested task as the first priority:

- If the error blocks the task, diagnose it and attempt a repair immediately so the task can continue.
- If the error does not block the task, record enough evidence to reproduce it, finish the requested task first, and then diagnose and attempt a repair.
- After a repair, run focused regression tests plus the repository's required test suite and any safe connected checks needed to establish the fix.
- When the repair is complete and sufficiently verified, commit only the repair-related changes and push that commit to the current repository remote. Do not include unrelated pre-existing worktree changes.
- If the repair is incomplete, cannot be pushed, or lacks sufficient testing, continue any remaining feasible task work and explain the error, attempted repair, remaining risk, and missing validation in detail in the final report.

## Verify Changes

Run the repository test suite after code changes:

```bash
python -m pytest -q
```

Scale connected tests to the change. Confirm device identity first, use documented loopback wiring, retain exact commands/results, and restore PWM/capture state afterward.
