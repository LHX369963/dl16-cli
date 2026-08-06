# Export, sessions, and offline decoding

## Export, persistent sessions, and software protocol decode

Decoded capture directories can be exported to full-sample CSV, transition-only
CSV, or 1 ns-timescale VCD. The exporter memory-maps channel files and emits
rows incrementally. A 20,000-sample, 16-channel acceptance capture exported in
0.10 s (CSV) and 0.07 s (edges/VCD), with about 15 MB maximum RSS on the test
host.

`dl16 session` is a JSON-lines command loop that performs link recovery once
and then accepts PWM and Stream operations over the same `Dl16Device`. This is
required when a loopback test must preserve both PWM generators across capture
configuration. A live 100 MHz session measured PWM0 on CH7 at 1 MHz/75% and
PWM1 on CH6 at 2 MHz/24% (finite sample quantization around the requested 25%).

Offline UART, I2C, and SPI decoders consume the packed LSB-first files and emit
JSON. UART supports 5..9 data bits, parity, 1/2 stop bits, and inversion; I2C
reports address/direction/data/ACK; SPI supports modes 0..3, MSB/LSB, arbitrary
1..32-bit words, optional MOSI/MISO, and optional active-low CS.

Decode a saved stream into one packed file per channel:

```bash
dl16 capture decode --input wire.bin --output-dir decoded
dl16 capture decode --input wire-rle.bin --output-dir decoded-rle --rle
```

The output directory contains `channel-NN.bin` files and `manifest.json`. Packed files retain the LSB-first eight-samples-per-byte representation.
