# DL16 CLI acceptance - 2026-07-18

Target: ATK DL16 (`1a86:ffcc`), PWM0 looped to CH7 and PWM1 looped to CH15.
Firmware update and other non-usage operations are outside this acceptance.

## Results

| Area | Result | Evidence |
|---|---|---|
| Non-root USB | Pass | `harry` opened, reset, claimed and queried the device without sudo; device has a logind ACL and the rule now includes a `plugdev` fallback |
| Device info | Pass | Parsed response reports `device_text=DL16`, `value_3_4=222`, `value_5_6=1108` |
| Persistent Stream | Pass | One session started both PWMs and captured 200,000 synchronized samples/channel at 100 MHz |
| Persistent Buffer | Pass | One session captured 100,000 synchronized samples/channel at 250 MHz without resetting PWM |
| Persistent edge trigger | Pass | 100,000-sample 250 MHz Buffer capture completed with CH7 rising trigger at requested 50% position |
| Full simple trigger | Pass | Single CH15 high-level trigger and two CH7/CH15 level-AND combinations completed; unmatched edge/level combinations return after configured timeout |
| Persistent Buffer+RLE | Pass | 131,250,000 samples/channel expanded for CH7 and CH15 at 250 MHz |
| Measurement | Pass | Stream: CH7 1 MHz/75%, CH15 2 MHz/24%; Buffer/RLE: CH7 1 MHz/75.2%, CH15 2 MHz/24.8% |
| Export | Pass | Edge CSV exported 12,000 transitions from the 200,000-sample Stream capture |
| Glitch filter | Pass | One-sample filter processed the live two-channel capture without false pulse removals |
| Data search | Pass | Multi-channel edge/level search scanned 200,000 live samples in 0.07 seconds with about 17 MiB RSS |
| Extended decode | Pass | System sigrok library reads generated VCD; counter decoder reported all 2,000 CH7 rising edges |
| Automated regression | Pass | 212 pytest cases plus `compileall` and `git diff --check` |

The duty differences are sampling quantization: PWM1 has 12 high samples in a
50-sample period at 100 MHz and 31 high samples in a 125-sample period at
250 MHz.

## Performance

The same two-channel 525 ms Buffer+RLE capture expands to 32,812,500 bytes of
channel data. Before incremental finite-capture writes it took 4.07 seconds and
98,856 KiB maximum RSS. After the change it took 3.95 seconds and 19,888 KiB
maximum RSS. Measurement of 1,050,000 rising edges on CH15 uses a period/duty
histogram and reduced maximum RSS from 164,308 KiB to 31,744 KiB.

Raw captures are under ignored `reverse/acceptance-2026-07-18-*` directories.

## Official manual usage coverage

- Buffer and Stream modes, normal capture, immediate/no-trigger capture, RLE,
  channel/rate/depth/threshold/position settings: implemented.
- Repeated capture: supported by sending repeated `capture` operations through
  one persistent JSONL session, with an optional delay controlled by the caller.
- All DL16 simple-trigger states and multi-channel AND conditions: implemented.
- Glitch filtering, waveform parameter measurement, data search, PWM output,
  raw/CSV/edge CSV/VCD storage, and offline protocol decode: implemented.
- Extended protocols use the maintained sigrok decoder library; native
  UART/I2C/SPI remain available without it.
- Roll mode, advanced serial/parallel trigger, and Buffer partial-upload stop
  are identified by the official manual as DL32-only and are outside DL16 scope.
- GUI-only presentation features such as themes, colors, zoom, labels and
  shortcuts are represented by machine-readable results and VCD viewing rather
  than reimplemented in a CLI.
