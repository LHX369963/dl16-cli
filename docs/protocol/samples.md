# Packed samples and hardware RLE

## Packed samples and hardware RLE

For type-1 packets, the body is a sequence of packed sample bytes. Each byte contains eight chronological samples, least-significant bit first.

When `isRLE` is enabled, the body is instead a sequence of two-byte records:

```text
byte 0: repeat count
byte 1: packed sample value
```

The original receiver expands each packed value `repeat count` times into a 512 KiB packet buffer. The implementation enforces the same per-packet output limit.

Ordinary Buffer packets expose 12 extra expanded bytes after the requested
samples. RLE packets expose one extra expanded packed byte. Incremental Stream
on the current DL16 device exposed an 8-byte suffix. Receivers stop at the
requested sample count and remove/report the mode-specific suffix independently
for every channel.

