# Capture modes and completion


Raw capture and inspection:

```bash
dl16 capture read --packets 100 --output wire.bin
dl16 capture parse --input wire.bin
```

`capture read` saves complete concatenated wire packets without altering them.

One-shot acquisition accepts either one channel or a comma-separated channel set:

```bash
dl16 capture run --buffer --channels 6,7 \
  --set-time 0.08 --set-hz 250000000 --sample-index 12 \
  --trigger-position 0 --threshold 1.2 --output-dir capture-buffer
```

Type-1 packets from enabled channels may be interleaved. The receiver therefore
tracks each channel independently and stops only after every requested channel
has reached the configured sample depth plus its transport trailer. Existing
single-channel scripts remain compatible through `--channel N`.

Live ordinary Buffer pressure runs completed at 250 MHz with 4, 8, and 16
channels. Each channel returned 20,000 samples; CH6 decoded the connected
1 MHz/75% PWM, CH7 decoded 2 MHz/25%, and the unconnected channels remained
static as expected.

Buffer hardware RLE can be enabled for one or more channels:

```bash
dl16 capture run --buffer --rle --channels 6,7 \
  --set-time 2500 --set-hz 250000000 --sample-index 12 \
  --trigger-position 0 --threshold 1.2 --output-dir capture-rle
```

On DL16, the original UI exposes RLE as starred sampling times beyond the
ordinary 1 Gbit Buffer depth. Very short acquisitions with the RLE bit set do
not produce sample packets on the tested hardware. RLE capture completion is
tracked using expanded per-channel lengths and the type-6 hardware completion
packet. If compressed memory fills before the requested depth, the shorter
valid result is retained and reported by `capture_shortened_by_hardware`.

Multi-channel RLE pressure runs requested 1.05 billion aggregate samples in
each configuration. The 4/8/16-channel runs each expanded to 131.25 MB of
packed samples while transferring approximately 24.84/12.41/6.72 MB on the
wire. The connected PWM channels decoded correctly in every run.

For long Stream captures, `capture stream` writes channel bodies directly to
disk. Omitting `--duration` selects the largest 40-bit depth and Ctrl-C causes
the receiver to truncate every channel to the shortest common complete-byte
count before writing the manifest. A live interrupted 20 MHz, two-channel run
retained 52,230,528 aligned samples per channel. The DL16 Stream completion
suffix observed in this path is 8 bytes; the receiver derives and reports the
same-packet suffix instead of assuming the Buffer value.

