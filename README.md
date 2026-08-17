# DL16 CLI

Non-official Linux CLI and Python protocol implementation for the **DL16** logic
analyzer. It supports PWM, finite/streaming capture, trigger, export, analysis,
and offline protocol decoding. It is evidence-backed only for DL16, not DL32 or
other models.

## Install

Requires Linux, Python 3.10+, and libusb:

```bash
python3 -m pip install '.[usb]'
```

For CAN/LIN/JTAG/1-Wire and other sigrok decoders:

```bash
sudo apt install sigrok-cli
```

If USB permissions fail, install `udev/99-dl16.rules`, reload udev rules, and
reconnect the analyzer. Normal work needs no `list`/`info` preflight; normal
initialization handshakes first and uses endpoint clear/reset only after failure.

## Quick capture

```bash
dl16 pwm verify --pwm0 1kHz,25 --pwm1 2kHz,75
dl16 capture run --buffer --channels 7,15 --sample-rate 250000000 --set-time 1 \
  --trigger rising --trigger-channel 7 --trigger-position 50 --output-dir capture
dl16 capture measure --input-dir capture --channel 7
```

Successful control and file-producing commands are silent. Measurements print
only requested values unless a detailed format is explicitly selected.

The CLI chooses `--sample-index` by default and protects existing capture files.
Use a new output directory unless replacement is explicitly requested with
`--force`.

## Topics

- [Capture, trigger, Stream, and file format](docs/usage/capture.md)
- [PWM and persistent sessions](docs/usage/pwm-session.md)
- [Analysis, export, and protocol decoding](docs/usage/analysis.md)
- [Boundaries, protocol evidence, and development](docs/usage/development.md)

The Codex Skill is [`skills/dl16-cli`](skills/dl16-cli). Parameters are
authoritative in `dl16 <command> --help`.
