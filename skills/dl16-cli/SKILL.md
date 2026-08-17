---
name: dl16-cli
description: Control and measure DL16 logic analyzers with the dl16 CLI.
---

# DL16 CLI

Use `dl16/.venv/bin/dl16` from the instrument-cli workspace. Execute the
requested operation directly; do not inspect, preserve, restore, stop, or clean
up unrelated state.

Common forms:

```bash
dl16/.venv/bin/dl16 pwm verify --pwm0 1kHz,25 --input0 0 --pwm1 2kHz,75 --input1 8
dl16/.venv/bin/dl16 capture run --channels 0,8 --sample-rate 20000000 --set-time 20 --output-dir capture
dl16/.venv/bin/dl16 capture measure --input-dir capture --channel 0
```

`pwm verify` uses the explicitly supplied PWM-to-input mapping. It sets outputs,
chooses capture parameters, measures the selected inputs, and
leaves PWM running. Measurement warnings do not suppress results; report them
and let the user decide whether to investigate further.
