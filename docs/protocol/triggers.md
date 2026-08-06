# Trigger configuration

## High-level trigger commands

Simple trigger accepts channel states in ascending channel order; the first channel occupies the high nibble:

```bash
dl16 --dry-run trigger simple \
  --states rising,high,null,low \
  --enabled 1,1,1,1 \
  --collect-type 1
```

State names: `null`, `rising`, `high`, `falling`, `low`, `double`. Aliases `X`, `R`, `1`, `F`, `0`, and `C` are also accepted.

One-shot acquisition directly supports rising and falling edges. The trigger
channel defaults to the first captured channel and must be included in the
capture set:

```bash
dl16 capture run --buffer --channels 6,7 \
  --sample-rate 100000000 --set-time 1 \
  --trigger rising --trigger-channel 6 --trigger-position 50 \
  --threshold 1.2 --output-dir triggered
```

The manifest records the edge, channel, and requested trigger position.

Stage and serial trigger commands consume JSON:

```bash
dl16 --dry-run trigger stage --file examples/stage-trigger.json
dl16 --dry-run trigger serial --file examples/serial-trigger.json
```

`stage-trigger.json` schema:

```text
triggerLevel: byte
channelOffset: even channel count preceding this device segment
enabled: boolean mask
stages[]:
  states[]: trigger state names
  counter: uint16
  contiguous: boolean
```

`serial-trigger.json` schema:

```text
valueChannel, valueWidth, valueData
timeChannel, timeEdge
channelOffset
enabled[]
startStates[]
stopStates[]
```

