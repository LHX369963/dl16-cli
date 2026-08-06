---
name: dl16-cli
description: Operate, test, debug, or document the DL16 logic analyzer through the public dl16 CLI, including PWM, Stream/Buffer/RLE capture, triggers, persistent sessions, measurement, search, filtering, export, and protocol decoding. Use for DL16 hardware work, dl16 command changes, connected validation, capture analysis, or deployment of this CLI; do not apply it to DL32 or other models.
---

# DL16 CLI

Resolve the repository two levels above this file's real path. Use its
`.venv/bin/dl16` when present, otherwise `dl16`, and use public CLI workflows
rather than `dl16_cli`, libusb, or raw protocol calls. Support only DL16; do not
infer DL32 behavior. Never issue `SET_CONFIGURATION` because it breaks the link.

Do not run `list` or `info` before direct PWM/capture work unless discovery,
selection, or identity is actually uncertain. Normal initialization handshakes
directly; endpoint clear/reset is failure recovery, never routine preflight.
Inspect `dl16 <command> --help` only for unfamiliar parameters.

Use `capture run` for finite Stream/Buffer/RLE and `capture stream` for long,
incremental recording. Let the CLI select sample index unless investigating its
mapping. Read [capture](../../docs/usage/capture.md) for triggers, limits, and
file handling; read [PWM/session](../../docs/usage/pwm-session.md) only for
multi-step persistent work; read [analysis](../../docs/usage/analysis.md) only
for post-capture processing.

Use a new capture directory by default and preserve its manifest, raw packets,
and channels together. Set bounded duration/timeout for unattended runs. Stop
only PWM/stream activity created by the task; do not require snapshots,
restoration, or routine post-checks. Keep partial aligned Stream data after an
intentional interrupt.

Report CLI errors and their impact immediately, then diagnose without dropping
the requested task. Read [development](../../docs/usage/development.md) for
protocol or code work; acceptance is not daily-use preflight. Run relevant tests
after code changes and separate hardware evidence from unit-test coverage.
