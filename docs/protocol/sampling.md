# Sampling configuration and rate mapping

## Recovered sampling configuration

The high-level CLI can now construct the recovered 13-byte `ParameterSetting` payload:

```bash
dl16 --dry-run capture configure \
  --set-time 10 \
  --set-hz 100000000 \
  --trigger-position 25 \
  --threshold -1.2 \
  --sample-index 3 \
  --rle \
  --collect-type 1
```

Payload layout:

```text
0      flags: 0x80 Buffer, 0x40 RLE
1      threshold in 0.1 V sign-magnitude form
2      sampling index
3..7   sample depth, unsigned 40-bit little-endian
8..12  trigger sample position, unsigned 40-bit little-endian
```

The CLI arguments `set-time`, `sample-index`, and `collect-type` deliberately retain the original application's field names until their complete user-facing value tables are recovered.

For `capture run`, `--sample-index` is optional and normally should be omitted.
The CLI selects the DL16 index from `--sample-rate` (an alias of `--set-hz`)
and rejects an explicitly supplied mismatching index. Verified DL16 rates are:

```text
1, 2, 4, 5, 10, 20, 40, 50, 100, 200, 250, 500 MHz
```

Index 7 is intentionally unavailable: three fresh live attempts returned no
sample packets on DL16. Stream mode combinations are checked against the
manual's limits: 16 channels through 20 MHz, 6 channels through 50 MHz, and 3
channels through 100 MHz. Buffer mode permits up to 16 channels through
500 MHz.

