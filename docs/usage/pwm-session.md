# PWM and persistent sessions

PWM0/PWM1 support the verified 1 Hz–20 MHz range and 0–100% duty:

```bash
dl16 pwm start --channel 0 --freq 1000000 --duty 75
dl16 pwm stop --channel 0
```

For the fixed PWM0→CH0 and PWM1→CH8 loopback, one command sets both outputs,
chooses a compact Buffer capture, measures all complete periods, and leaves PWM
running:

```bash
dl16 pwm verify --pwm0 1kHz,25 --pwm1 2kHz,75
```

It prints only `frequency duty` per requested PWM. Out-of-range frequency/duty
is normalized internally; deviations or variation produce one concise warning.

Apply requested PWM state directly; do not inspect, restore, or stop unrelated
activity.

Separate CLI processes reinitialize the USB/FPGA link. For multiple PWM settings
followed by capture, use a JSONL `session`:

```json
{"op":"pwm_start","channel":0,"frequency_hz":1000000,"duty_percent":75}
{"op":"capture","channels":[7,15],"sample_rate_hz":250000000,"duration_ms":1,"buffer":true,"output_dir":"capture"}
{"op":"quit"}
```

```bash
dl16 session --commands commands.jsonl
```

Responses are JSONL. Session operations are `pwm_start`, `pwm_stop`, `stream`,
`capture`, `stop`, and `quit`; `capture` also accepts RLE/trigger options and
`overwrite`. It is a persistent transport, not a replacement for public CLI
workflows.
