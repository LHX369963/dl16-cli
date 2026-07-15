# ATK DL16 Protocol Reference

Status: partially implemented and still under reverse engineering.

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
| 8 | 40 MHz |
| 9 | 50 MHz |
| 10 | 100 MHz |
| 11 | 200 MHz |
| 12 | 250 MHz |
| 0 | 500 MHz |

Indexes 6 and 7 remain deliberately undocumented until separately measured
with a suitable reference frequency.

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

- `atkdl16 list`
- `atkdl16 info`
- `atkdl16 stop [--channel N]`
- `atkdl16 pwm start --channel N --freq HZ --duty PERCENT`
- `atkdl16 pwm stop --channel N`
- `atkdl16 capture configure ...`
- `atkdl16 trigger simple ...`
- `atkdl16 trigger stage --file ...`
- `atkdl16 trigger serial --file ...`
- `atkdl16 capture read --packets N --output wire.bin`
- `atkdl16 capture run ... --output-dir capture`

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
atkdl16 --timeout-ms 2000 capture run \
  --channel 7 \
  --set-time 500 \
  --set-hz 1000000 \
  --trigger-position 1 \
  --threshold 1.6 \
  --sample-index 1 \
  --output-dir capture
```

The output directory contains the logical packet stream (`wire.bin`), packed
LSB-first samples (`channel-07.bin`), and `manifest.json`. The implementation
removes the confirmed 12-byte first-channel transport trailer and stops after
the requested sample depth. This command currently supports one input channel
per invocation while the multi-channel prefix/offset behavior is still being
recovered.

Firmware frame planning is available offline. Hardware flashing is exposed only behind the explicit `--i-understand-this-can-brick` guard and should be used only after entering the bootloader and confirming the correct transport mode.

## Raw recovered command CLI

The following commands expose recovered command IDs with caller-supplied payload bytes. They are intended for reverse-engineering experiments and do not imply that the payload schema is fully decoded:

```bash
atkdl16 --dry-run raw parameter-setting --payload-hex "11 22"
atkdl16 --dry-run raw simple-trigger --payload-hex "aa"
atkdl16 --dry-run raw stage-trigger --payload-hex "aa"
atkdl16 --dry-run raw serial-trigger --payload-hex "aa"
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
atkdl16 --dry-run capture configure \
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

## High-level trigger commands

Simple trigger accepts channel states in ascending channel order; the first channel occupies the high nibble:

```bash
atkdl16 --dry-run trigger simple \
  --states rising,high,null,low \
  --enabled 1,1,1,1 \
  --collect-type 1
```

State names: `null`, `rising`, `high`, `falling`, `low`, `double`. Aliases `X`, `R`, `1`, `F`, `0`, and `C` are also accepted.

Stage and serial trigger commands consume JSON:

```bash
atkdl16 --dry-run trigger stage --file examples/stage-trigger.json
atkdl16 --dry-run trigger serial --file examples/serial-trigger.json
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

Raw capture and inspection:

```bash
atkdl16 capture read --packets 100 --output wire.bin
atkdl16 capture parse --input wire.bin
```

`capture read` saves complete concatenated wire packets without altering them.

One-shot acquisition accepts either one channel or a comma-separated channel set:

```bash
atkdl16 capture run --buffer --channels 6,7 \
  --set-time 0.08 --set-hz 250000000 --sample-index 12 \
  --trigger-position 0 --threshold 1.2 --output-dir capture-buffer
```

Type-1 packets from enabled channels may be interleaved. The receiver therefore
tracks each channel independently and stops only after every requested channel
has reached the configured sample depth plus its transport trailer. Existing
single-channel scripts remain compatible through `--channel N`.

Buffer hardware RLE can be enabled for one or more channels:

```bash
atkdl16 capture run --buffer --rle --channels 6,7 \
  --set-time 2500 --set-hz 250000000 --sample-index 12 \
  --trigger-position 0 --threshold 1.2 --output-dir capture-rle
```

On DL16, the original UI exposes RLE as starred sampling times beyond the
ordinary 1 Gbit Buffer depth. Very short acquisitions with the RLE bit set do
not produce sample packets on the tested hardware. RLE capture completion is
tracked using expanded per-channel lengths and the type-6 hardware completion
packet. If compressed memory fills before the requested depth, the shorter
valid result is retained and reported by `capture_shortened_by_hardware`.

## Packed samples and hardware RLE

For type-1 packets, the body is a sequence of packed sample bytes. Each byte contains eight chronological samples, least-significant bit first.

When `isRLE` is enabled, the body is instead a sequence of two-byte records:

```text
byte 0: repeat count
byte 1: packed sample value
```

The original receiver expands each packed value `repeat count` times into a 512 KiB packet buffer. The implementation enforces the same per-packet output limit.

Ordinary Buffer packets expose 12 extra expanded bytes after the requested
samples. RLE packets expose one extra expanded packed byte instead; the online
receiver removes the appropriate mode-specific trailer independently for every
channel.

Decode a saved stream into one packed file per channel:

```bash
atkdl16 capture decode --input wire.bin --output-dir decoded
atkdl16 capture decode --input wire-rle.bin --output-dir decoded-rle --rle
```

The output directory contains `channel-NN.bin` files and `manifest.json`. Packed files retain the LSB-first eight-samples-per-byte representation.

## MCU and firmware update protocol

Firmware transfer does not use the normal command/CRC wrapper. Two MCU transport modes exist:

- `framed-510`: every write is 510 bytes; synchronous ACK reads are 512 bytes in the original application.
- `direct-64`: every write and ACK read is 64 bytes; update data is sent directly and zero-padded.

Fixed framed commands:

| Command | Meaning | Prefix |
|---:|---|---|
| `0x80` | Enter bootloader | `0a 80 "ATK-LOGIC-ANALYZER"` |
| `0x81` | Get MCU version | `0a 81 0b` |
| `0x82` | Enter MCU update | `0a 82 "ATK-LOGIC-ANALYZER-MCU-V1"` |
| `0x83` | MCU firmware data | framed data layout below |
| `0x84` | Restart MCU | `0a 84 0b` |
| `0x85` | Enter FPGA update | `0a 85 "ATK-LOGIC-ANALYZER-FPGA-V1"` |
| `0x86` | FPGA firmware data | framed data layout below |

Framed update data:

```text
0       0x0a
1       0x83 for MCU or 0x86 for FPGA
2..3    data length, uint16 little-endian, maximum 504
4..     firmware bytes
4+N     0x00
5+N     0x0b
...     zero padding to 510 bytes
```

The original downloader uses 256-byte chunks in `framed-510` mode and 64-byte chunks in `direct-64` mode. It always sends one final remainder frame, including a zero-length frame when the file size is an exact multiple.

ACK success is recognized from the first three response bytes:

```text
0a <expected-command> 01
```

It tries up to six reads with 50 ms between failures. Before the final data ACK it waits 1 second for MCU and 5 seconds for FPGA. In direct-64 mode, data ACK command `0x86` is expected for both target types, matching the original branch.

Generate and inspect every write offline first:

```bash
atkdl16 firmware plan --file firmware.bin --target mcu \
  --mode framed-510 --output-dir firmware-plan
```

Query the currently attached MCU endpoint or request the application-to-bootloader transition:

```bash
atkdl16 firmware version --mode framed-510
atkdl16 firmware enter-bootloader --mode framed-510 \
  --i-understand-this-can-brick
```

After allowing USB re-enumeration, selecting the bootloader device, and confirming the correct mode, the guarded update command is:

```bash
atkdl16 --vid-pid VID:PID firmware flash --file firmware.bin \
  --target mcu --mode framed-510 --i-understand-this-can-brick
```

The flash command sends enter-update, all data frames with ACK validation, then restart. The initial bootloader request and post-request USB re-enumeration remain separate CLI steps so the newly enumerated device can be selected explicitly.
