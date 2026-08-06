# Evidence: command framing and CRC

## Command frame layering

Evidence:

- `../../reverse/disasm_117370...Write_unsigned_char_unsigned_char_int_.s` (included inside the objdump range captured in prior output)
- `../../reverse/disasm_117250_USBControl::SendToDevice_unsigned_char_int_.s`
- `../../reverse/disasm_116fd0_USBControl::SendToLIBUSB_unsigned_char_int_.s`

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

