# Evidence: commands, PWM, and early trigger clues

## Confirmed command IDs

Evidence: short wrapper functions in `../../reverse/disasm_117*.s`.

| Command | Meaning | Evidence |
|---:|---|---|
| `0x10` | GetDeviceData | `USBControl::GetDeviceData()` |
| `0x11` | ParameterSetting | `USBControl::ParameterSetting(payload, len)` |
| `0x12` | SimpleTrigger | `USBControl::SimpleTrigger(payload, len)` |
| `0x13` | StageTrigger | `USBControl::StageTrigger(payload, len)` |
| `0x14` | SerialTrigger | `USBControl::SerialTrigger(payload, len)` |
| `0x15` | Stop | `USBControl::Stop(signed char)` |
| `0x17` | PWM | `USBControl::PWM(payload, len)` |

## PWM payload

Evidence:

- `../../reverse/high_b8fc0_SessionController::pwmStart_signed_char_int_int_.s`
- `../../reverse/high_b93b0_SessionController::pwmStop_signed_char_.s`
- `../../reverse/high_cfd40_Session::PWM_QByteArray_.s`

Start payload:

```text
payload[0] = (channel << 4) + 0x11
payload[1..4] = period_count, 4 bytes, byte order from intToBytes() still to confirm
payload[5..8] = duty_count, 4 bytes, byte order from intToBytes() still to confirm
period_count ~= 100_000_000 / frequency_hz
duty_count ~= period_count * duty_percent / 100
```

Stop payload:

```text
payload[0] = (channel + 1) << 4
```

Both are sent via command `0x17`.

## Trigger encoding clues

Evidence: `../../reverse/high_b29e0_triggerStringToByte_QJsonArray_QString_int_int_.s`.

`triggerStringToByte(QJsonArray, QString, int, int)` converts trigger strings into packed bytes. Character mapping observed in the disassembly includes cases for:

- `R` (rising edge) contributes bit pattern using `0x01`/`0x10` nibble positions.
- `1` contributes `0x04`/`0x40` nibble positions.
- `F` contributes `0x02`/`0x20` nibble positions.
- `0` contributes no edge/level bit.
- `C` and default/other branches contribute other nibble patterns.

The function also reads per-channel JSON objects and the key string with length 6; this likely corresponds to an enable/disable field. Exact JSON schema must be recovered from QML and call sites.

## Implemented prototype references

The first implementation plan turns the low-risk portions of this evidence into tested code:

- `dl16_cli.protocol` for USB IDs, command IDs, frame construction, and CRC32 byte conversion.
- `dl16_cli.pwm` for PWM start/stop payloads.
- `dl16_cli.device` and `dl16_cli.cli` for dry-run command frame generation.

