# DL16 CLI acceptance — 2026-07-15

Target: ATK DL16 (`1a86:ffcc`) with PWM0/PWM1 looped to CH7/CH6. Other models
and firmware update work are outside this acceptance scope.

## Result matrix

| Area | Result | Acceptance evidence |
|---|---|---|
| Start with device already attached | Pass | Recovered FFCC link without physical hotplug; avoids `SET_CONFIGURATION` |
| PWM0/PWM1 | Pass | 1 Hz..20 MHz matrices, duty-cycle combinations, independent high-range runs |
| Automatic sample rate | Pass | 1/2/4/5/10/20/40/50/100/200/250/500 MHz; index 6 measured as 20 MHz; index 7 excluded after three no-data attempts |
| Rising/falling trigger | Pass | Both edges appeared around the requested 50% point on a 100,000-sample Buffer capture |
| Multi-channel Buffer | Pass | 4/8/16 channels at 250 MHz; CH6/CH7 PWM correct, unconnected channels static |
| Buffer RLE | Pass | 4/8/16-channel runs each expanded to 131.25 MB aggregate; online `(count,value)` decode correct |
| CSV/edge CSV/VCD | Pass | 16-channel capture exported in all formats; VCD transitions grouped by nanosecond timestamp |
| Incremental Stream | Pass | 20 MHz two-channel Ctrl-C run retained 52,230,528 synchronized samples/channel and exited cleanly |
| Persistent session | Pass | One initialized JSONL session started both PWMs and captured at 100 MHz without resetting generators |
| UART/I2C/SPI | Pass | Synthetic waveform tests cover UART 8N1, I2C address/data/ACK, and SPI mode 0; all have CLI JSON output |
| Packaging | Pass | Built wheel, installed it without source-tree imports in a clean venv, ran entry point and imported all new modules |

## Live persistent-session measurement

At 100 MHz Stream sampling, 200,000 samples/channel:

| Input | Generator setting | Measured |
|---|---|---|
| CH7 | PWM0, 1 MHz, 75% | 1,000,000 Hz, 75% |
| CH6 | PWM1, 2 MHz, 25% | 2,000,000 Hz, 24% |

The 1% duty difference on CH6 is one 100 MHz sample across the 50-sample PWM
period and is within sample-phase quantization.

## Pressure and performance observations

- RLE aggregate expanded data: 131.25 MB for each of 4/8/16-channel runs.
- RLE wire sizes: approximately 24.84 MB, 12.41 MB, and 6.72 MB respectively.
- Interrupted Stream wire input: 13,115,649 bytes during the timed run; output
  channels were truncated to the same 6,528,816 packed bytes each.
- Export of 20,000 samples × 16 channels on this host:
  - full CSV: 0.10 s, 15,136 KiB maximum RSS;
  - edge CSV: 0.07 s, 15,284 KiB maximum RSS;
  - VCD: 0.07 s, 15,500 KiB maximum RSS.

These timings are implementation acceptance measurements, not guaranteed
product throughput. Stream throughput depends on USB controller, filesystem,
channel count, and sample rate.

## Repeatable software checks

```bash
pytest -q
python -m compileall -q atkdl16_cli
python -m pip wheel . --no-deps -w /tmp/dl16-wheel
python -m venv /tmp/dl16-venv
/tmp/dl16-venv/bin/pip install --no-deps /tmp/dl16-wheel/*.whl
/tmp/dl16-venv/bin/atkdl16 --dry-run list
```

Raw live-capture artifacts are kept under the local ignored `reverse/`
directory so large wire/sample files are not committed to the source package.
