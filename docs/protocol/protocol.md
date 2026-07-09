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
