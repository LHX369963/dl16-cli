# ATK DL16/ATK-Logic CLI reverse-engineering design

Date: 2026-07-09
Status: Draft for user review
Source package: `ATK-Logic_1.1.2.0_amd64.deb`
Supporting evidence: `docs/protocol/evidence-summary.md`, `reverse/`

## Goal

Build a command-line and library-style replacement for the ATK-Logic upper-computer software's device-control path, with the long-term target of reproducing capture functionality as completely as practical: device discovery, information queries, sampling, simple trigger, staged/advanced trigger, serial trigger, PWM, stop/reset, raw capture export, and firmware/bootloader operations.

The UI, waveform renderer, measurement tools, and protocol decoders are not part of the first CLI goal except where data formats must interoperate with them.

## Current evidence baseline

The Linux package contains an unstripped Qt/libusb binary. The binary exposes enough symbols to guide the reverse engineering:

- `logic_analyzer_find/open/close`
- `USBControl::Write`, `SendToDevice`, `Read`, `ReadSynchronous*`
- `USBControl::ParameterSetting`, `SimpleTrigger`, `StageTrigger`, `SerialTrigger`, `PWM`, `Stop`
- `USBControl::EnterBootloader`, `GetMCUVersion`, `SendUpdateData`
- `ThreadWork::DeviceRecvThread`
- `triggerStringToByte`

The initial protocol facts are documented in `docs/protocol/evidence-summary.md`.

## Approach

Use a two-layer implementation strategy:

1. **Python protocol prototype and CLI**
   - Fastest for reverse-engineering iteration.
   - Uses `pyusb` or a thin `libusb1` binding.
   - Keeps packet builders small and testable.
   - Provides immediate integration through subprocess execution or Python import.

2. **Native high-speed backend later**
   - Added only after the protocol is verified.
   - Handles continuous high-throughput capture, RLE/format conversion, and firmware flashing if Python proves too slow or too risky.
   - Exposed behind the same CLI and library interfaces.

This avoids prematurely committing to a native implementation before the unknown command payloads are recovered.

## Deliverables

### Documentation

- `docs/protocol/evidence-summary.md`: observed facts with source references.
- `docs/protocol/protocol.md`: stable protocol reference once fields are verified.
- `docs/protocol/firmware-update.md`: separate firmware/bootloader reference with warnings and recovery notes.
- `docs/protocol/capture-format.md`: raw sample stream, RLE/decompression, and exported file layout.

### Python package layout

```text
atkdl16_cli/
  __init__.py
  cli.py                 # argparse/click entrypoint
  usb.py                 # libusb discovery/open/read/write
  protocol.py            # frame builder, CRC, command IDs
  device.py              # high-level device facade
  capture.py             # sampling parameter and read-loop orchestration
  trigger.py             # simple/stage/serial trigger encoding
  pwm.py                 # PWM payload builder
  firmware.py            # guarded MCU/bootloader/update commands
  formats.py             # raw/bin/csv/sigrok export helpers where practical
  errors.py              # typed exceptions and user-facing diagnostics
  _native.py             # optional native backend adapter stub

tests/
  test_protocol_frame.py
  test_pwm_payload.py
  test_trigger_encoding.py
  test_cli_args.py
```

### CLI commands

```bash
atkdl16 list
atkdl16 info [--json]
atkdl16 stop [--channel N]
atkdl16 pwm start --channel N --freq HZ --duty PERCENT
atkdl16 pwm stop --channel N
atkdl16 capture --samplerate RATE --channels LIST --depth N --output FILE [--format raw|bin|csv|sr]
atkdl16 trigger simple [options]
atkdl16 trigger stage --file trigger.json
atkdl16 trigger serial --file serial-trigger.json
atkdl16 firmware version
atkdl16 firmware enter-bootloader --i-understand-risk
atkdl16 firmware flash FILE --i-understand-this-can-brick
```

## Protocol architecture

### USB layer

Responsibilities:

- Enumerate accepted USB IDs:
  - `1a86:ffcc`
  - `1a86:6a6b`
  - `04b4:6a6a`
- Open interface 0.
- Detach kernel driver when supported.
- Resolve endpoints from descriptors instead of hard-coding endpoint bytes until the endpoint mapping is fully confirmed.
- Support both bulk and interrupt devices.
- Provide synchronous operations first; add async transfers when capture throughput requires them.

### Packet layer

Responsibilities:

- Build inner command:

```text
cmd, payload_len + 1, payload...
```

- Build outer transport frame:

```text
8 zero bytes, 0x0a, inner, crc32(inner), 0x0b
```

- Verify or reproduce the binary's `gCRC32` algorithm and byte order.
- Decode acknowledgements and error frames once observed.

### Device command layer

Initial command IDs:

```text
0x10 GetDeviceData
0x11 ParameterSetting
0x12 SimpleTrigger
0x13 StageTrigger
0x14 SerialTrigger
0x15 Stop
0x17 PWM
```

The command layer must keep unknown/reserved fields explicit. If a field is inferred but not verified, the code must label it as such and tests must not pretend it is proven.

## Feature design

### Device discovery and info

- `list` returns bus, address/path hash, VID/PID, speed, and guessed model.
- `info` sends `GetDeviceData` and later MCU version query after the response format is known.
- Output can be text or JSON.

### PWM

PWM is the first feature suitable for implementation after frame/CRC verification because its payload is mostly recovered.

Start payload:

```text
byte0 = (channel << 4) | 0x11
byte1..4 = period_count
byte5..8 = duty_count
period_count = round_or_truncate(100_000_000 / frequency_hz), matching original binary behavior
duty_count = round_or_truncate(period_count * duty_percent / 100), matching original binary behavior
```

Stop payload:

```text
byte0 = (channel + 1) << 4
```

Remaining PWM unknowns:

- `intToBytes()` byte order.
- Exact rounding behavior for negative/edge floating-point values is irrelevant for the CLI because the CLI will reject invalid frequency/duty values.

### Capture and sampling

Capture depends on three pieces that must be recovered together:

1. `ParameterSetting` payload layout.
2. Read stream packet format.
3. Data conversion/RLE handling.

Work plan for this area:

- Trace call sites that assemble `ParameterSetting` from `SessionConfig`.
- Use `ThreadWork::DeviceRecvThread` and `AnalysisDl32::*` to identify stream framing.
- Implement a conservative capture loop that writes exact raw packets before attempting conversion.
- Add post-processing only after raw packet boundaries and compression are verified.

CLI output modes:

- `raw`: exact received data after optional transport conversion.
- `bin`: packed sample bytes compatible with the original binary export if recovered.
- `csv`: decoded logic levels per sample for smaller captures.
- `sr`: optional Sigrok session export if practical.

### Simple trigger

`SimpleTrigger` sends command `0x12` with a trigger payload. The trigger character packing is partially recovered through `triggerStringToByte`:

- `R`, `F`, `1`, `0`, `C`, and other/default states map into nibbles.
- Two channels appear to pack into one byte.

The design keeps trigger encoding in `trigger.py` with named enums and test vectors from the original binary. Implementation must not claim full trigger support until call sites and JSON schema are verified.

### Stage/advanced trigger

`StageTrigger` uses command `0x13`. The UI exposes stage trigger JSON, so the implementation will support `--file trigger.json` rather than inventing a large CLI syntax first.

Implementation steps:

- Recover QML/JSON schema from embedded strings/resources.
- Recover payload packing from call sites around `StageTrigger`.
- Provide a schema validator that rejects unsupported fields instead of silently ignoring them.

### Serial trigger

`SerialTrigger` uses command `0x14`. The UI exposes fields such as `startCondition` and `startCondition32` in embedded QML strings.

Implementation steps:

- Recover the serial trigger JSON schema and byte packing.
- Implement `--file serial-trigger.json` first.
- Add ergonomic flags for common UART/SPI-like cases only after the raw schema is proven.

### Stop/reset

`Stop(signed char)` sends command `0x15` with either no payload or one signed byte when the channel/device argument is non-negative. The CLI will expose:

```bash
atkdl16 stop
atkdl16 stop --channel N
```

### Firmware and bootloader

Firmware update uses a separate MCU frame path and is more dangerous than normal commands.

Design rules:

- Firmware commands are isolated in `firmware.py`.
- Flashing requires `--i-understand-this-can-brick`.
- Bootloader entry requires `--i-understand-risk`.
- Dry-run mode prints the frames that would be sent without sending them.
- The CLI must refuse to flash unless the target VID/PID and current mode match the recovered update flow.
- The firmware updater must record a log file with every sent block and response.

Known MCU commands from current evidence:

- Get MCU version: frame starts with memory word corresponding to `0x810a`; byte `0x0b` at offset 2.
- Enter bootloader: frame starts with memory word corresponding to `0x800a`, includes a 16-byte literal and word `0x5245`.

Unknowns to recover:

- Full MCU frame structure.
- Firmware block size and checksum.
- Response/ack format.
- Update-mode VID/PID transitions.

## Error handling

- USB open failures report permissions, busy interface, and missing udev rules separately.
- Timeout errors include command name and endpoint.
- Unsupported or unverified options fail closed.
- Firmware errors always stop and require manual retry.
- Capture interruptions preserve partial raw output with a metadata sidecar.

## Testing and verification

### Offline tests

- CRC vectors generated from the original binary or verified captures.
- Frame builder tests for each command.
- PWM payload tests.
- Trigger encoder tests using known trigger strings and original binary-equivalent outputs.
- CLI parser tests.

### Hardware tests

- Enumerate device.
- Query info.
- Start/stop PWM on one channel and measure with an external logic analyzer or loopback capture.
- Short capture with no trigger.
- Simple trigger capture.
- Stage trigger capture.
- Serial trigger capture.
- Firmware version query.
- Bootloader entry and flashing only on a sacrificial/recoverable device.

## Safety and scope boundaries

The final target is broad, but development must be staged. The CLI should expose experimental commands only with clear labels until hardware tests prove them.

Firmware flashing is explicitly high-risk and will not be considered complete without a verified recovery path or explicit acceptance that the user has a recoverable test device.

## Milestones

1. **Protocol core**: USB open, endpoint detection, command frame/CRC, `list`, dry-run packet printing.
2. **Low-risk commands**: `info`, `stop`, `pwm start/stop`.
3. **Capture MVP**: parameter payload recovered enough for raw capture; raw packet dump implemented.
4. **Capture decoding**: sample stream/RLE decoded; export formats implemented.
5. **Trigger support**: simple trigger, then stage trigger, then serial trigger.
6. **Firmware support**: version query, bootloader entry dry-run, guarded flashing after update protocol is recovered.
7. **Native acceleration**: only if Python cannot sustain required capture throughput.

## Acceptance criteria

The objective is complete only when current evidence proves all of the following:

- CLI can discover and open supported devices.
- CLI can send correctly framed commands with verified CRC.
- Device information and stop commands work.
- PWM start/stop works and is externally verified.
- Sampling parameters can reproduce the original app's supported capture modes to the practical extent of DL16 hardware.
- Raw capture data can be acquired and exported.
- Captured logic levels decode correctly for known test patterns.
- Simple, stage, and serial triggers work against hardware tests.
- Firmware version query works.
- Bootloader/update flow is either implemented and verified on recoverable hardware, or documented as intentionally disabled behind safety guards until the user provides a test device and firmware file.
- Protocol documentation matches implementation and cites evidence for recovered fields.

