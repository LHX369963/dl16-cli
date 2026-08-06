# Evidence: capture dispatch and sampling payload

## Capture and trigger call-site evidence

Additional xref notes were generated under `../../reverse/capture/`.

- `../../reverse/capture/xrefs.md` shows `Session::OrderStart(...)` calls:
  - `USBControl::ParameterSetting` at `0xd0198`
  - `USBControl::SimpleTrigger` at `0xd0587`
  - `USBControl::SerialTrigger` at `0xd066e`
  - `USBControl::StageTrigger` at `0xd06e5`
- `../../reverse/capture/cfe80_Session::OrderStart_QByteArray_QByteArray_QJsonObject_unsigned_long_long_unsigned_long_long_QVector_signed_char_.s` is the main capture/trigger dispatch function.
- `../../reverse/capture/fc3b0_ThreadRead::start_USBControl_int_ThreadWork_.s` shows the read thread calling `USBControl::Read`.
- `../../reverse/capture/118970_USBControl::ReadLIBUSB_Data__int_int_int_.s` contains the async read path.

## Recovered ParameterSetting payload

Evidence source: `SessionController::start(QJsonObject, int)` at `0x0c2820`, extracted as `../../reverse/capture/c2820_SessionController_start.s`.

The first `QByteArray` passed to `Session::OrderStart` is built as a fixed 13-byte payload:

| Offset | Size | Meaning | Evidence |
|---:|---:|---|---|
| 0 | 1 | flags: bit 7 `isBuffer`, bit 6 `isRLE` | append at `0xc2ea7`; flag branches `0xc2e66..0xc2e92`, `0xc3748` |
| 1 | 1 | threshold sign-magnitude, magnitude is threshold volts × 10 rounded to nearest integer, bit 7 is negative | append at `0xc3047`; factor 10.0 at `0x1f291f0` |
| 2 | 1 | `settingData.index` | append at `0xc308b` |
| 3 | 5 | sample depth, unsigned little-endian | `intToBytes(..., 5)` at `0xc3392` |
| 8 | 5 | trigger sample position, unsigned little-endian | `intToBytes(..., 5)` at `0xc355d` |

`intToBytes` at `0x0b2970` emits least-significant byte first.

Recovered calculations:

```text
frequency_khz = int(settingData.setHz) // 1000
sample_depth = int(settingData.setTime * frequency_khz)
trigger_sample = int((sample_depth // 100) * settingData.triggerPosition)
```

When `collectType == 3`, the original function aborts configuration if either RLE or Buffer is enabled (`0xc2e74..0xc2e8c`, `0xc3748..0xc3758`).

