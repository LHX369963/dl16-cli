# DL16 Capture Packet Parser Implementation Plan

**Goal:** Parse the recovered DL16 USB receive stream incrementally and expose lossless raw packet capture through the CLI.

## Recovered wire format

- Start marker: `0x0a`
- Packet type: one byte (`1..6` accepted by the original parser)
- Payload length: unsigned 16-bit little-endian
- Payload: exactly the declared number of bytes
- Trailer: `0x00 0x0b`
- Total size: `payload_length + 6`
- For packets returned by `Analysis::getNextData`, payload byte 0 is copied to a metadata field, payload byte 1 remains reserved/unknown, and the body starts at payload offset 2.

## Tasks

1. Add failing unit tests for complete, fragmented, concatenated, malformed, and resynchronized packets.
2. Implement immutable packet records and an incremental stream parser.
3. Add failing USB backend tests for independent bulk-IN reads.
4. Implement `read_chunk()` in dry-run and PyUSB backends.
5. Add failing CLI tests for parsing saved streams and reading a bounded packet count.
6. Implement lossless length-prefixed raw packet export and JSON-lines summaries.
7. Document evidence, packet type uncertainty, and usage; run the full test suite.
