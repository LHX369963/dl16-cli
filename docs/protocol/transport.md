# USB IDs and command transport

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

