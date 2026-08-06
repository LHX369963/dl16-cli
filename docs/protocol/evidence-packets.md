# Evidence: receive packets

## Recovered DL16 receive packet framing

Evidence source: `Analysis::*` at `0x57bc0..0x57f30`, captured in `../../reverse/capture/57bc0_Analysis_DL16.s`.

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

