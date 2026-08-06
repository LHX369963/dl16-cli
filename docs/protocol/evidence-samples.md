# Evidence: samples and RLE

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
