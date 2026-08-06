# Receive packet framing and information responses

## DL16 receive packet framing

`Analysis::analysis_get_type`, `analysis_get_length`, `analysis_get_data`, and `getNextData` establish this incremental wire format:

```text
0       0x0a
1       packet type, accepted range 1..6
2..3    payload length, uint16 little-endian
4..     payload
4+N     0x00
5+N     0x0b
```

The total packet length is `N + 6`. USB transfer boundaries do not need to match these packet boundaries.

Within the payload, byte 0 is metadata used as the channel ID on type-1 packets. Payload byte 1 is preserved as `metadata1`, but its meaning is not yet assigned. The packet body begins at payload offset 2.

Recovered packet-type behavior:

| Type | Original receive-thread behavior |
|---:|---|
| 1 | Packed per-channel sample data |
| 2 | Device-information response; format byte and selected fields recovered |
| 3 | Reads a 5-byte little-endian value and logs an offset command |
| 4 | Control/status body; observed subcommands include `0x15` end and `0x12` status/error |
| 5 | Reads a 5-byte little-endian value and updates receive progress |
| 6 | End/state transition path |

For a type-2 body whose byte 0 is `1`, the connection code reads:

```text
body[0]       format discriminator, required value 1
body[1..2]    reserved/unused by the observed parser
body[3]*100 + body[4]   first decimal-coded numeric value
body[5]*100 + body[6]   second decimal-coded numeric value
body[7..N]    NUL-terminated local-text device string
```

The CLI intentionally labels the numeric fields `value_3_4` and `value_5_6` until their exact product/version names can be confirmed from hardware output.

Repeated live queries on 2026-07-18 also returned discriminator `0` with the
same trailing `DL16` text layout. For this observed variant the CLI exposes the
text and preserves bytes 3..6 as `unassigned_3_6_hex`; it does not apply the
format-1 decimal interpretation to fields the original parser did not assign.
