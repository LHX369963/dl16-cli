# ATK-Logic / DL16 reverse-engineering evidence summary

Date: 2026-07-10
Source package: `ATK-Logic_1.1.2.0_amd64.deb`
Main binary: `extracted/opt/apps/atk-logic/ATK-Logic`

This file records facts observed from the current worktree's binary and disassembly. It is not the final protocol document.

## USB discovery

Evidence: `reverse/disasm_116240_logic_analyzer_find_.s` (`logic_analyzer_find`).

The application initializes libusb, enumerates devices, reads descriptors, and accepts these IDs:

- `VID 0x1a86, PID 0xffcc`
- `VID 0x1a86, PID 0x6a6b`
- `VID 0x04b4, PID 0x6a6a`

`logic_analyzer_open` claims interface 0 after enabling auto-detach:

- Evidence: `reverse/disasm_115f80_logic_analyzer_open_LogicAnalyzer_.s`
- Calls: `libusb_set_auto_detach_kernel_driver(handle, 1)`, `libusb_claim_interface(handle, 0)`.

## Transfer modes and endpoints

Evidence: `reverse/disasm_118680_USBControl::Init_libusb_device_libusb_context_int_int_bool_.s`.

The program supports both interrupt and bulk-style paths:

- Interrupt write path: `USBControl::SendToLIBUSB_Interrupt` -> `libusb_interrupt_transfer`.
- Bulk/async path: `USBControl::SendToLIBUSB` -> `libusb_submit_transfer`.
- Synchronous read path: `USBControl::ReadSynchronousLIBUSB` -> `libusb_bulk_transfer`.
- Interrupt read path: `USBControl::ReadSynchronousLIBUSB_Interrupt` -> `libusb_interrupt_transfer`.

Endpoint fields are stored in the `LogicAnalyzer` object:

- write endpoint at object offset `0x24`
- read endpoint at object offset `0x25`

Known constants assigned during initialization include `0xffff8101` and `0xffff8102`; the endpoint byte used by libusb is read with `movzbl 0x24/0x25`, so the low byte must be validated against real descriptors or runtime traces before finalizing endpoint direction/mapping.

## Command frame layering

Evidence:

- `reverse/disasm_117370...Write_unsigned_char_unsigned_char_int_.s` (included inside the objdump range captured in prior output)
- `reverse/disasm_117250_USBControl::SendToDevice_unsigned_char_int_.s`
- `reverse/disasm_116fd0_USBControl::SendToLIBUSB_unsigned_char_int_.s`

High-level command wrapper `USBControl::Write(cmd, payload, len)` builds an inner command:

```text
inner[0] = cmd
inner[1] = payload_len + 1
inner[2..] = payload bytes
```

The lower-level `USBControl::Write(raw, raw_len)` wraps that with a transport frame. The relevant stores in the disassembly are:

- allocate and zero `raw_len + 15` bytes
- write `0x0a` at offset 8
- copy `raw_len` bytes at offset 9
- write `0x0b` at offset `9 + raw_len`
- write CRC32 at offset `10 + raw_len`
- leave the final byte zero from the initial memset

```text
transport = 8 zero bytes
          + 0x0a
          + inner bytes
          + 0x0b
          + crc32(inner bytes), 4 bytes as emitted by the binary
          + 0x00 trailing/reserved byte
```

Observed total length is `raw_len + 15`.

`gCRC32(unsigned char*, int)` at `0x0b2920` initializes EAX to zero, indexes the reflected table at `0x1f28d20`, and returns `~eax`. The table begins `0x00000000, 0x77073096, 0xee0e612c`, identifying the standard reflected `0xedb88320` polynomial. Exact parameters are init `0x00000000`, xorout `0xffffffff`; `"123456789"` produces `0xd202d277`. `USBControl::Write` stores the returned 32-bit value directly on little-endian x86, so transport CRC byte order is little-endian.

## Confirmed command IDs

Evidence: short wrapper functions in `reverse/disasm_117*.s`.

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

- `reverse/high_b8fc0_SessionController::pwmStart_signed_char_int_int_.s`
- `reverse/high_b93b0_SessionController::pwmStop_signed_char_.s`
- `reverse/high_cfd40_Session::PWM_QByteArray_.s`

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

Evidence: `reverse/high_b29e0_triggerStringToByte_QJsonArray_QString_int_int_.s`.

`triggerStringToByte(QJsonArray, QString, int, int)` converts trigger strings into packed bytes. Character mapping observed in the disassembly includes cases for:

- `R` (rising edge) contributes bit pattern using `0x01`/`0x10` nibble positions.
- `1` contributes `0x04`/`0x40` nibble positions.
- `F` contributes `0x02`/`0x20` nibble positions.
- `0` contributes no edge/level bit.
- `C` and default/other branches contribute other nibble patterns.

The function also reads per-channel JSON objects and the key string with length 6; this likely corresponds to an enable/disable field. Exact JSON schema must be recovered from QML and call sites.

## Implemented prototype references

The first implementation plan turns the low-risk portions of this evidence into tested code:

- `atkdl16_cli.protocol` for USB IDs, command IDs, frame construction, and CRC32 byte conversion.
- `atkdl16_cli.pwm` for PWM start/stop payloads.
- `atkdl16_cli.device` and `atkdl16_cli.cli` for dry-run command frame generation.

## Capture and trigger call-site evidence

Additional xref notes were generated under `reverse/capture/`.

- `reverse/capture/xrefs.md` shows `Session::OrderStart(...)` calls:
  - `USBControl::ParameterSetting` at `0xd0198`
  - `USBControl::SimpleTrigger` at `0xd0587`
  - `USBControl::SerialTrigger` at `0xd066e`
  - `USBControl::StageTrigger` at `0xd06e5`
- `reverse/capture/cfe80_Session::OrderStart_QByteArray_QByteArray_QJsonObject_unsigned_long_long_unsigned_long_long_QVector_signed_char_.s` is the main capture/trigger dispatch function.
- `reverse/capture/fc3b0_ThreadRead::start_USBControl_int_ThreadWork_.s` shows the read thread calling `USBControl::Read`.
- `reverse/capture/118970_USBControl::ReadLIBUSB_Data__int_int_int_.s` contains the async read path.

## Recovered ParameterSetting payload

Evidence source: `SessionController::start(QJsonObject, int)` at `0x0c2820`, extracted as `reverse/capture/c2820_SessionController_start.s`.

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

## Recovered trigger payloads

Evidence source: `SessionController::start(QJsonObject, int)` and `triggerStringToByte`.

### Trigger nibble encoding

The jump table at `0x1f29800` maps original `triggerType` values 0..5 to these encodings:

| Original type | Meaning | Nibble |
|---:|---|---:|
| 0 | null / don't-care | `0x7` |
| 1 | rising | `0x1` |
| 2 | high | `0x4` |
| 3 | falling | `0x2` |
| 4 | low | `0x0` |
| 5 | double edge | `0x3` |

The first channel of each pair occupies the high nibble. `triggerStringToByte`
sets bit 3 of each nibble when that channel is enabled, then adds the condition
code. Thus enabled rising/falling are `0x9`/`0xa`, enabled don't-care is `0xf`,
and disabled don't-care is `0x7`. Live edge-trigger tests fail with the old
code-only `0x1`/`0x2` representation and succeed with the enable bit present.

### Simple trigger

Evidence range: `0xc3aa8..0xc3c97`.

```text
packed channel bytes
byte: 1 when collectType == 2, otherwise 0
byte: 1 when collectType == 3, otherwise 0
```

Live Buffer captures with a continuous 1 MHz PWM on CH6 verified both simple
edge modes at a 50% trigger position: rising appeared at sample 49,975 of
100,000 and falling at sample 49,994 of 100,000.

### Stage trigger

Evidence range: `0xc3f20..0xc42df`; repeated for each object in `stageTriggerData.trigger`:

```text
stage number, 1-based
stageTriggerData.triggerLevel
counter, uint16 little-endian
0x00 when isContiguous, otherwise 0x40
packed stage condition bytes
```

Relevant stores/calls: stage number append `0xc4154`, trigger level append `0xc4169`, counter conversion `0xc41b8`, contiguous flag append `0xc4231`, condition packing call `0xc40a1`.

### Serial trigger

Evidence range: `0xc4310..0xc474b`:

```text
valueChannel + device channel offset
valueWidth
valueData, uint16 little-endian
timeChannel + device channel offset
timeEdge
packed startCondition bytes
packed stopCondition bytes
```

Relevant appends/conversions: `0xc43c6`, `0xc4407`, `0xc4451`, `0xc44bb`, `0xc44fc`, and condition pack calls `0xc45d5`, `0xc46e6`.

## Recovered DL16 receive packet framing

Evidence source: `Analysis::*` at `0x57bc0..0x57f30`, captured in `reverse/capture/57bc0_Analysis_DL16.s`.

- `analysis_get_type` requires byte 0 `0x0a` and accepts type byte 1 only in range 1..6.
- `analysis_get_length` reads bytes 2..3 as a little-endian uint16.
- `analysis_get_data` requires exactly that payload length, followed by `0x00 0x0b`.
- Total encoded size is `payload_length + 6`.
- `getNextData` copies payload byte 0 to its metadata field, returns a data pointer at payload + 2, and reports body length `payload_length - 2`.

The type jump table in `ThreadWork::DeviceRecvThread` is at `0x1f2c8e0`:

| Type | Destination | Observed behavior |
|---:|---:|---|
| 1 | `0x102fd3` | channel sample path |
| 2 | `0x103dac` | shared/default parser loop |
| 3 | `0x1033bd` | copies five body bytes into a uint64 and logs an offset command |
| 4 | `0x102f23` | control/status body; checks body byte 0 for `0x15` and `0x12` |
| 5 | `0x103c44` | copies five bytes and computes receive percentage |
| 6 | `0x102e22` | end/state transition path |

Type-2 device information is parsed in `ConnectDevice::CheckDeviceCreanInfo` at `0xf6d30..0xf6e4a`. It requires body byte 0 equal to 1, calculates `body[3] * 100 + body[4]` and `body[5] * 100 + body[6]`, and converts bytes from body offset 7 through the first NUL to a local-text string. Body bytes 1..2 are skipped by this observed path.

## Recovered sample and RLE representation

Evidence source: type-1 receive path `0x102fd3..0x1033b8`.

- Payload metadata byte 0 is passed as the channel argument to `Segment::SetSampleBlock`.
- With `isRLE == false`, the body is passed directly and its byte length is accumulated per channel.
- With `isRLE == true`, `0x103223..0x1032f1` requires an even body length and expands repeated `(count, value)` byte pairs into a `0x80000`-byte temporary buffer.
- The expanded or direct bytes are then handled identically.

Live DL16 verification with flags `0xc0` confirms that online Buffer+RLE
records are `(count, value)`. A requested 1,250,000,000-sample capture returned
156,250,001 expanded bytes and the type-3 completion value 1,250,000,008,
proving that RLE carries one extra packed-byte trailer. Ordinary Buffer exposes
a 12-byte trailer. The incremental Stream path on the current DL16 device
instead exposed an 8-byte same-packet suffix; capture code now stops at the
requested sample count rather than assuming one common trailer size.

Live sampling-index verification maps index 6 to 20 MHz using a 1 MHz PWM
loopback with exactly 20 samples per period. Index 7 was retried in three fresh
captures and returned no type-1 sample packets, so the DL16 automatic rate
table omits it instead of assuming a 25/30 MHz meaning from another model.

`Segment::GetSample` at `0xd7f80` computes `sample_index >> 3`, loads the packed byte, shifts it right by `sample_index & 7`, and masks bit 0. Therefore each packed byte contains eight chronological samples in LSB-first order.

`Segment::CheckCompress` is not the USB hardware RLE decoder. It checks 64-bit words for all-zero or all-one blocks and is used by internal `Segment` storage compression.
