# Analysis, export, and protocol decoding

Measure PWM from complete rising-edge periods, filter short pulses into a new
capture, or search multi-channel conditions:

```bash
dl16 capture measure --input-dir capture --channel 7
dl16 capture filter --input-dir capture --output-dir filtered --max-samples 2 --channels 7,15
dl16 capture search --input-dir capture --conditions 7=rising,15=high --limit 100
```

PWM measurement prints only `frequency duty`; add `--json` for complete edge,
period, sample-rate, and variation metadata.

Export CSV, edge CSV, or VCD without copying the full capture into memory:

```bash
dl16 capture export --input-dir capture --format edges --output edges.csv
```

Offline native decoders support UART (5–9 bits, parity, stop bits, inversion),
I2C, and SPI (modes 0–3, bit order, optional MOSI/MISO/CS):

```bash
dl16 capture uart --input-dir capture --channel 6 --baud 115200 --output uart.json
dl16 capture i2c --input-dir capture --scl 0 --sda 1 --output i2c.json
dl16 capture spi --input-dir capture --clock 2 --mosi 3 --miso 4 --cs 5 --output spi.json
```

For supported external decoders, use sigrok; it creates and removes temporary
VCD automatically:

```bash
dl16 capture sigrok --input-dir capture --decoder uart --channel rx=7 --option baudrate=115200
```

Use `capture sigrok --list` to inspect installed decoders. Private/custom vendor
decoders and GUI display parity are not provided.
