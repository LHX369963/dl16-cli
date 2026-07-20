# DL16 Protocol Reference

Status: the DL16 acquisition path is implemented and hardware-verified; fields
that remain unknown are explicitly labelled rather than guessed.

## Supported USB IDs

- `1a86:ffcc`
- `1a86:6a6b`
- `04b4:6a6a`

## Normal command inner frame

```text
byte 0: command
byte 1: payload length + 1
byte 2..: payload
```

## Normal command transport frame

The current implementation follows the observed `USBControl::Write(raw, raw_len)` layout from the binary:

```text
8 bytes: 00 00 00 00 00 00 00 00
1 byte : 0a
N bytes: inner frame
1 byte : 0b
4 bytes: recovered gCRC32(inner frame), little-endian
1 byte : 00 reserved/trailing byte from the binary allocation
```

The original `gCRC32` uses the standard reflected CRC-32 table (`0xedb88320` polynomial), but starts the accumulator at zero and returns its bitwise complement. This differs from the common CRC-32/ISO-HDLC initial state.

```text
width   = 32
poly    = 0x04c11db7 (reflected table uses 0xedb88320)
refin   = true
refout  = true
init    = 0x00000000
xorout  = 0xffffffff
check("123456789") = 0xd202d277
```

For `1a86:ffcc`, normal frames are zero-padded to a 2048-byte boundary and then
de-interleaved into four 16-bit-word lanes before bulk OUT. Bulk IN capture data
uses the inverse lane transform. The original application does not issue
`SET_CONFIGURATION` when opening this device; doing so was observed to leave the
DL16 endpoints unresponsive until a physical replug.

## Implemented command IDs

| Command | Value | Implemented behavior |
|---|---:|---|
| `GET_DEVICE_DATA` | `0x10` | Dry-run frame generation |
| `PARAMETER_SETTING` | `0x11` | High-level 13-byte sampling configuration |
| `SIMPLE_TRIGGER` | `0x12` | High-level and raw payload generation |
| `STAGE_TRIGGER` | `0x13` | High-level and raw payload generation |
| `SERIAL_TRIGGER` | `0x14` | High-level and raw payload generation |
| `STOP` | `0x15` | Optional one-byte channel payload |
| `PWM` | `0x17` | Start and stop payloads |

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
`reverse/pwm-matrix/`, `reverse/pwm-high-range/`, and
`reverse/pwm-1hz-snapshots/` outside the source tree.

PWM1 was subsequently wired to CH6 and independently verified: a channel scan
located the signal only on CH6, the 100 Hz..100 kHz representative matrix
passed 12/12, the 500 kHz..20 MHz matrix passed 21/21, and repeated short
captures measured the 1 Hz endpoint at 0.999901 Hz. Those artifacts are stored
under `reverse/pwm1-channel-scan/`, `reverse/pwm1-mid-range/`,
`reverse/pwm1-high-range/`, and `reverse/pwm1-1hz-snapshots/`.

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

## Hardware USB backend stage

Install the optional pyusb dependency before using non-dry-run hardware commands:

```bash
python3 -m pip install -e '.[usb]'
```

The hardware backend exposes the tested command builders plus independent bulk-IN capture reads:

- `dl16 list`
- `dl16 info`
- `dl16 stop [--channel N]`
- `dl16 pwm start --channel N --freq HZ --duty PERCENT`
- `dl16 pwm stop --channel N`
- `dl16 capture configure ...`
- `dl16 trigger simple ...`
- `dl16 trigger stage --file ...`
- `dl16 trigger serial --file ...`
- `dl16 capture read --packets N --output wire.bin`
- `dl16 capture run ... --output-dir capture`
- `dl16 capture stream ... --output-dir capture`
- `dl16 capture export ...`
- `dl16 capture uart|i2c|spi ...`
- `dl16 session [--commands commands.jsonl]`

The backend opens supported devices by descriptor, claims interface 0, detaches the kernel driver when the platform supports it, selects endpoints from descriptors, writes the command frame to the OUT endpoint, and reads one packet from the IN endpoint when present.

For an FFCC device that was plugged in before the CLI started, normal commands
automatically recover the link without a physical hotplug: clear both bulk
endpoints, issue a USB bus reset, immediately reclaim the interface, wait the
original application's 400 ms settle interval, retry the MCU query up to six
times, query both FPGA banks, and validate the `DL16` information response.

`capture run` keeps recovery, configuration, trigger, bulk reads, stop, and
decode in one process, so no command boundary resets the configured capture. A
single-channel 1 MHz/500 ms acquisition matching the confirmed CH7 trace is:

```bash
dl16 --timeout-ms 2000 capture run \
  --channel 7 \
  --set-time 500 \
  --set-hz 1000000 \
  --trigger-position 1 \
  --threshold 1.6 \
  --sample-index 1 \
  --output-dir capture
```

The output directory contains the logical packet stream (`wire.bin`), packed
LSB-first samples (`channel-07.bin`), and `manifest.json`. Type-1 packets may be
interleaved; the implementation tracks up to 16 requested channels
independently and removes each channel's completion suffix.

## Raw recovered command CLI

The following commands expose recovered command IDs with caller-supplied payload bytes. They are intended for reverse-engineering experiments and do not imply that the payload schema is fully decoded:

```bash
dl16 --dry-run raw parameter-setting --payload-hex "11 22"
dl16 --dry-run raw simple-trigger --payload-hex "aa"
dl16 --dry-run raw stage-trigger --payload-hex "aa"
dl16 --dry-run raw serial-trigger --payload-hex "aa"
```

Mapping:

| CLI command | Command ID |
|---|---:|
| `raw parameter-setting` | `0x11` |
| `raw simple-trigger` | `0x12` |
| `raw stage-trigger` | `0x13` |
| `raw serial-trigger` | `0x14` |

Use non-dry-run raw commands only when connected to sacrificial or recoverable hardware during protocol experiments.

## Recovered sampling configuration

The high-level CLI can now construct the recovered 13-byte `ParameterSetting` payload:

```bash
dl16 --dry-run capture configure \
  --set-time 10 \
  --set-hz 100000000 \
  --trigger-position 25 \
  --threshold -1.2 \
  --sample-index 3 \
  --rle \
  --collect-type 1
```

Payload layout:

```text
0      flags: 0x80 Buffer, 0x40 RLE
1      threshold in 0.1 V sign-magnitude form
2      sampling index
3..7   sample depth, unsigned 40-bit little-endian
8..12  trigger sample position, unsigned 40-bit little-endian
```

The CLI arguments `set-time`, `sample-index`, and `collect-type` deliberately retain the original application's field names until their complete user-facing value tables are recovered.

For `capture run`, `--sample-index` is optional and normally should be omitted.
The CLI selects the DL16 index from `--sample-rate` (an alias of `--set-hz`)
and rejects an explicitly supplied mismatching index. Verified DL16 rates are:

```text
1, 2, 4, 5, 10, 20, 40, 50, 100, 200, 250, 500 MHz
```

Index 7 is intentionally unavailable: three fresh live attempts returned no
sample packets on DL16. Stream mode combinations are checked against the
manual's limits: 16 channels through 20 MHz, 6 channels through 50 MHz, and 3
channels through 100 MHz. Buffer mode permits up to 16 channels through
500 MHz.

## High-level trigger commands

Simple trigger accepts channel states in ascending channel order; the first channel occupies the high nibble:

```bash
dl16 --dry-run trigger simple \
  --states rising,high,null,low \
  --enabled 1,1,1,1 \
  --collect-type 1
```

State names: `null`, `rising`, `high`, `falling`, `low`, `double`. Aliases `X`, `R`, `1`, `F`, `0`, and `C` are also accepted.

One-shot acquisition directly supports rising and falling edges. The trigger
channel defaults to the first captured channel and must be included in the
capture set:

```bash
dl16 capture run --buffer --channels 6,7 \
  --sample-rate 100000000 --set-time 1 \
  --trigger rising --trigger-channel 6 --trigger-position 50 \
  --threshold 1.2 --output-dir triggered
```

The manifest records the edge, channel, and requested trigger position.

Stage and serial trigger commands consume JSON:

```bash
dl16 --dry-run trigger stage --file examples/stage-trigger.json
dl16 --dry-run trigger serial --file examples/serial-trigger.json
```

`stage-trigger.json` schema:

```text
triggerLevel: byte
channelOffset: even channel count preceding this device segment
enabled: boolean mask
stages[]:
  states[]: trigger state names
  counter: uint16
  contiguous: boolean
```

`serial-trigger.json` schema:

```text
valueChannel, valueWidth, valueData
timeChannel, timeEdge
channelOffset
enabled[]
startStates[]
stopStates[]
```

## DL16 receive packet framing

`Analysis::analysis_get_type`, `analysis_get_length`, `analysis_get_data`, and `getNextData` establish this incremental wire format:

```text
0       0x0a
1       packet type, accepted range 1..6
2..3    payload length, uint16 little-endian
4..     payload
4+N     0x00
5+N     0x0b
```

The total packet length is `N + 6`. USB transfer boundaries do not need to match these packet boundaries.

Within the payload, byte 0 is metadata used as the channel ID on type-1 packets. Payload byte 1 is preserved as `metadata1`, but its meaning is not yet assigned. The packet body begins at payload offset 2.

Recovered packet-type behavior:

| Type | Original receive-thread behavior |
|---:|---|
| 1 | Packed per-channel sample data |
| 2 | Device-information response; format byte and selected fields recovered |
| 3 | Reads a 5-byte little-endian value and logs an offset command |
| 4 | Control/status body; observed subcommands include `0x15` end and `0x12` status/error |
| 5 | Reads a 5-byte little-endian value and updates receive progress |
| 6 | End/state transition path |

For a type-2 body whose byte 0 is `1`, the connection code reads:

```text
body[0]       format discriminator, required value 1
body[1..2]    reserved/unused by the observed parser
body[3]*100 + body[4]   first decimal-coded numeric value
body[5]*100 + body[6]   second decimal-coded numeric value
body[7..N]    NUL-terminated local-text device string
```

The CLI intentionally labels the numeric fields `value_3_4` and `value_5_6` until their exact product/version names can be confirmed from hardware output.

Repeated live queries on 2026-07-18 also returned discriminator `0` with the
same trailing `DL16` text layout. For this observed variant the CLI exposes the
text and preserves bytes 3..6 as `unassigned_3_6_hex`; it does not apply the
format-1 decimal interpretation to fields the original parser did not assign.

Raw capture and inspection:

```bash
dl16 capture read --packets 100 --output wire.bin
dl16 capture parse --input wire.bin
```

`capture read` saves complete concatenated wire packets without altering them.

One-shot acquisition accepts either one channel or a comma-separated channel set:

```bash
dl16 capture run --buffer --channels 6,7 \
  --set-time 0.08 --set-hz 250000000 --sample-index 12 \
  --trigger-position 0 --threshold 1.2 --output-dir capture-buffer
```

Type-1 packets from enabled channels may be interleaved. The receiver therefore
tracks each channel independently and stops only after every requested channel
has reached the configured sample depth plus its transport trailer. Existing
single-channel scripts remain compatible through `--channel N`.

Live ordinary Buffer pressure runs completed at 250 MHz with 4, 8, and 16
channels. Each channel returned 20,000 samples; CH6 decoded the connected
1 MHz/75% PWM, CH7 decoded 2 MHz/25%, and the unconnected channels remained
static as expected.

Buffer hardware RLE can be enabled for one or more channels:

```bash
dl16 capture run --buffer --rle --channels 6,7 \
  --set-time 2500 --set-hz 250000000 --sample-index 12 \
  --trigger-position 0 --threshold 1.2 --output-dir capture-rle
```

On DL16, the original UI exposes RLE as starred sampling times beyond the
ordinary 1 Gbit Buffer depth. Very short acquisitions with the RLE bit set do
not produce sample packets on the tested hardware. RLE capture completion is
tracked using expanded per-channel lengths and the type-6 hardware completion
packet. If compressed memory fills before the requested depth, the shorter
valid result is retained and reported by `capture_shortened_by_hardware`.

Multi-channel RLE pressure runs requested 1.05 billion aggregate samples in
each configuration. The 4/8/16-channel runs each expanded to 131.25 MB of
packed samples while transferring approximately 24.84/12.41/6.72 MB on the
wire. The connected PWM channels decoded correctly in every run.

For long Stream captures, `capture stream` writes channel bodies directly to
disk. Omitting `--duration` selects the largest 40-bit depth and Ctrl-C causes
the receiver to truncate every channel to the shortest common complete-byte
count before writing the manifest. A live interrupted 20 MHz, two-channel run
retained 52,230,528 aligned samples per channel. The DL16 Stream completion
suffix observed in this path is 8 bytes; the receiver derives and reports the
same-packet suffix instead of assuming the Buffer value.

## Packed samples and hardware RLE

For type-1 packets, the body is a sequence of packed sample bytes. Each byte contains eight chronological samples, least-significant bit first.

When `isRLE` is enabled, the body is instead a sequence of two-byte records:

```text
byte 0: repeat count
byte 1: packed sample value
```

The original receiver expands each packed value `repeat count` times into a 512 KiB packet buffer. The implementation enforces the same per-packet output limit.

Ordinary Buffer packets expose 12 extra expanded bytes after the requested
samples. RLE packets expose one extra expanded packed byte. Incremental Stream
on the current DL16 device exposed an 8-byte suffix. Receivers stop at the
requested sample count and remove/report the mode-specific suffix independently
for every channel.

## Export, persistent sessions, and software protocol decode

Decoded capture directories can be exported to full-sample CSV, transition-only
CSV, or 1 ns-timescale VCD. The exporter memory-maps channel files and emits
rows incrementally. A 20,000-sample, 16-channel acceptance capture exported in
0.10 s (CSV) and 0.07 s (edges/VCD), with about 15 MB maximum RSS on the test
host.

`dl16 session` is a JSON-lines command loop that performs link recovery once
and then accepts PWM and Stream operations over the same `Dl16Device`. This is
required when a loopback test must preserve both PWM generators across capture
configuration. A live 100 MHz session measured PWM0 on CH7 at 1 MHz/75% and
PWM1 on CH6 at 2 MHz/24% (finite sample quantization around the requested 25%).

Offline UART, I2C, and SPI decoders consume the packed LSB-first files and emit
JSON. UART supports 5..9 data bits, parity, 1/2 stop bits, and inversion; I2C
reports address/direction/data/ACK; SPI supports modes 0..3, MSB/LSB, arbitrary
1..32-bit words, optional MOSI/MISO, and optional active-low CS.

Decode a saved stream into one packed file per channel:

```bash
dl16 capture decode --input wire.bin --output-dir decoded
dl16 capture decode --input wire-rle.bin --output-dir decoded-rle --rle
```

The output directory contains `channel-NN.bin` files and `manifest.json`. Packed files retain the LSB-first eight-samples-per-byte representation.
