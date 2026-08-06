# PWM protocol and verified operating range

## PWM start payload

```text
byte 0   : (channel << 4) + 0x11
bytes 1-4: period_count, little-endian in the prototype
bytes 5-8: duty_count, little-endian in the prototype
```

```text
period_count = floor(200_000_000 / frequency_hz + 0.5)
duty_count = floor(period_count * duty_percent / 100 + 0.5)
```

The 200 MHz counter clock is confirmed by a live 1 kHz/50% original-application
transaction (`period_count=200000`, `duty_count=100000`) and a 1 MHz CH7 capture.
The half-up rounding above is also matched to the original disassembly rather
than Python's previous truncation. The DL16 UI exposes PWM0 and PWM1, so the CLI
now rejects unsupported PWM channel numbers outside 0..1.

A live PWM0-to-CH7 regression now covers the documented **1 Hz through 20 MHz**
range. The 100 Hz..100 kHz matrix passed 34/34 combinations. A 250 MHz capture
matrix (recovered sample index 12) passed 36/36 combinations from 100 kHz
through 20 MHz. The 1 Hz endpoint was verified by short repeated acquisitions;
sample-refined rising edges measured 1.000009 Hz across two periods. A separate
20-capture sequential stability run also completed without failure. The CLI
rejects PWM frequencies outside the product's documented 1..20,000,000 Hz
range. Raw artifacts and machine-readable results are under
`../../reverse/pwm-matrix/`, `../../reverse/pwm-high-range/`, and
`../../reverse/pwm-1hz-snapshots/` outside the source tree.

PWM1 was subsequently wired to CH6 and independently verified: a channel scan
located the signal only on CH6, the 100 Hz..100 kHz representative matrix
passed 12/12, the 500 kHz..20 MHz matrix passed 21/21, and repeated short
captures measured the 1 Hz endpoint at 0.999901 Hz. Those artifacts are stored
under `../../reverse/pwm1-channel-scan/`, `../../reverse/pwm1-mid-range/`,
`../../reverse/pwm1-high-range/`, and `../../reverse/pwm1-1hz-snapshots/`.

Live sample-index probing established the rates needed for PWM verification:

| Sample index | Observed sample rate |
|---:|---:|
| 1 | 1 MHz |
| 2 | 2 MHz |
| 3 | 4 MHz |
| 4 | 5 MHz |
| 5 | 10 MHz |
| 6 | 20 MHz |
| 8 | 40 MHz |
| 9 | 50 MHz |
| 10 | 100 MHz |
| 11 | 200 MHz |
| 12 | 250 MHz |
| 0 | 500 MHz |

Index 6 was measured with a 1 MHz PWM loopback at exactly 20 samples per
period. Index 7 returned no type-1 sample packets in three fresh DL16 attempts
and is deliberately excluded from automatic selection.

## PWM stop payload

```text
byte 0: (channel + 1) << 4
```

