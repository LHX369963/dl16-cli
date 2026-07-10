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
4 bytes: CRC32(inner frame), little-endian in the prototype
1 byte : 00 reserved/trailing byte from the binary allocation
```

The original binary function is named `gCRC32`. The prototype uses standard CRC32 until a recovered vector proves the exact original parameters.

## Implemented command IDs

| Command | Value | Implemented behavior |
|---|---:|---|
| `GET_DEVICE_DATA` | `0x10` | Dry-run frame generation |
| `STOP` | `0x15` | Dry-run frame generation with optional one-byte channel payload |
| `PWM` | `0x17` | Dry-run frame generation for start and stop payloads |

## PWM start payload

```text
byte 0   : (channel << 4) + 0x11
bytes 1-4: period_count, little-endian in the prototype
bytes 5-8: duty_count, little-endian in the prototype
```

```text
period_count = int(100_000_000 / frequency_hz)
duty_count = int(period_count * duty_percent / 100)
```

## PWM stop payload

```text
byte 0: (channel + 1) << 4
```

## Commands not implemented in the first plan

Capture, trigger, and firmware commands remain documented in `docs/protocol/evidence-summary.md` and are intentionally not exposed as sending commands by the dry-run CLI.

## Hardware USB backend stage

Install the optional pyusb dependency before using non-dry-run hardware commands:

```bash
python3 -m pip install -e '.[usb]'
```

The hardware backend currently supports only the low-risk commands that already have tested frame builders:

- `atkdl16 list`
- `atkdl16 info`
- `atkdl16 stop [--channel N]`
- `atkdl16 pwm start --channel N --freq HZ --duty PERCENT`
- `atkdl16 pwm stop --channel N`

The backend opens supported devices by descriptor, claims interface 0, detaches the kernel driver when the platform supports it, selects endpoints from descriptors, writes the command frame to the OUT endpoint, and reads one packet from the IN endpoint when present.

Capture, simple trigger, stage trigger, serial trigger, and firmware update remain unavailable in the CLI until their payloads and response formats are fully recovered and separately tested. Firmware flashing is intentionally disabled in this stage.

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
0      flags: 0x80 RLE, 0x40 Buffer
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
