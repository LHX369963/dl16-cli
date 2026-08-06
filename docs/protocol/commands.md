# Command IDs and raw experiment interface

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

