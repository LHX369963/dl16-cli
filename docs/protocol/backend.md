# USB hardware backend and recovery

## Hardware USB backend stage

Install the optional pyusb dependency before using non-dry-run hardware commands:

```bash
python3 -m pip install -e '.[usb]'
```

The hardware backend exposes the tested command builders plus independent bulk-IN capture reads:

- `dl16 list`
- `dl16 info`
- `dl16 stop [--channel N]`
- `dl16 pwm start --channel N --freq HZ --duty PERCENT`
- `dl16 pwm stop --channel N`
- `dl16 capture configure ...`
- `dl16 trigger simple ...`
- `dl16 trigger stage --file ...`
- `dl16 trigger serial --file ...`
- `dl16 capture read --packets N --output wire.bin`
- `dl16 capture run ... --output-dir capture`
- `dl16 capture stream ... --output-dir capture`
- `dl16 capture export ...`
- `dl16 capture uart|i2c|spi ...`
- `dl16 session [--commands commands.jsonl]`

The backend opens supported devices by descriptor, claims interface 0, detaches the kernel driver when the platform supports it, selects endpoints from descriptors, writes the command frame to the OUT endpoint, and reads one packet from the IN endpoint when present.

For an FFCC device plugged in before the CLI started, first try the normal
MCU/FPGA handshake without a reset. Only when that handshake fails, automatic
recovery avoids physical hotplug: clear both bulk endpoints, issue a USB bus
reset, immediately reclaim the interface, wait the original application's
400 ms settle interval, retry the MCU query up to six times, query both FPGA
banks, and validate the `DL16` information response.

`capture run` keeps recovery, configuration, trigger, bulk reads, stop, and
decode in one process, so no command boundary resets the configured capture. A
single-channel 1 MHz/500 ms acquisition matching the confirmed CH7 trace is:

```bash
dl16 --timeout-ms 2000 capture run \
  --channel 7 \
  --set-time 500 \
  --set-hz 1000000 \
  --trigger-position 1 \
  --threshold 1.6 \
  --sample-index 1 \
  --output-dir capture
```

The output directory contains the logical packet stream (`wire.bin`), packed
LSB-first samples (`channel-07.bin`), and `manifest.json`. Type-1 packets may be
interleaved; the implementation tracks up to 16 requested channels
independently and removes each channel's completion suffix.

