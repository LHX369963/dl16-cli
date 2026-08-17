# Capture, trigger, Stream, and files

Use `capture run` for finite Stream/Buffer/RLE. Defaults are 1.2 V threshold and
0% trigger position; the CLI chooses a valid sample index.
Successful capture is silent; artifacts are written to `--output-dir`.

```bash
# Finite Stream
dl16 capture run --channels 7,15 --sample-rate 20000000 --set-time 10 --output-dir capture
# Buffer with hardware RLE
dl16 capture run --buffer --rle --channels 7,15 --sample-rate 250000000 --set-time 525 --output-dir capture-rle
# Multi-channel trigger
dl16 capture run --buffer --channels 7,15 --sample-rate 250000000 --set-time 1 \
  --trigger-states 7=high,15=low --trigger-position 50 --trigger-timeout 10 --output-dir triggered
```

Single-channel trigger values are `rising`, `high`, `falling`, `low`, or
`either`. The default first-sample timeout is 30 s. Verified rates are 1, 2, 4,
5, 10, 20, 40, 50, 100, 200, 250, and 500 MHz. Stream limits are 16 channels at
20 MHz, 6 at 50 MHz, and 3 at 100 MHz; Buffer supports 16 channels at 500 MHz.

Use `capture stream` for incremental, interruptible recording:

```bash
dl16 capture stream --channels 7,15 --sample-rate 20000000 --duration 30 --output-dir long-capture
```

Without `--duration`, it runs until Ctrl-C or the 40-bit depth limit. Ctrl-C
keeps aligned data. DL16 has no DL32 rolling-display mode.

A capture directory is one unit: `manifest.json` (settings), `wire.bin` (raw
packets), and packed LSB-first `channel-NN.bin` files. Do not overwrite part of
it or replace it without explicit request.
