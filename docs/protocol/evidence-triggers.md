# Evidence: trigger payloads

## Recovered trigger payloads

Evidence source: `SessionController::start(QJsonObject, int)` and `triggerStringToByte`.

### Trigger nibble encoding

The jump table at `0x1f29800` maps original `triggerType` values 0..5 to these encodings:

| Original type | Meaning | Nibble |
|---:|---|---:|
| 0 | null / don't-care | `0x7` |
| 1 | rising | `0x1` |
| 2 | high | `0x4` |
| 3 | falling | `0x2` |
| 4 | low | `0x0` |
| 5 | double edge | `0x3` |

The first channel of each pair occupies the high nibble. `triggerStringToByte`
sets bit 3 of each nibble when that channel is enabled, then adds the condition
code. Thus enabled rising/falling are `0x9`/`0xa`, enabled don't-care is `0xf`,
and disabled don't-care is `0x7`. Live edge-trigger tests fail with the old
code-only `0x1`/`0x2` representation and succeed with the enable bit present.

### Simple trigger

Evidence range: `0xc3aa8..0xc3c97`.

```text
packed channel bytes
byte: 1 when collectType == 2, otherwise 0
byte: 1 when collectType == 3, otherwise 0
```

Live Buffer captures with a continuous 1 MHz PWM on CH6 verified both simple
edge modes at a 50% trigger position: rising appeared at sample 49,975 of
100,000 and falling at sample 49,994 of 100,000.

### Stage trigger

Evidence range: `0xc3f20..0xc42df`; repeated for each object in `stageTriggerData.trigger`:

```text
stage number, 1-based
stageTriggerData.triggerLevel
counter, uint16 little-endian
0x00 when isContiguous, otherwise 0x40
packed stage condition bytes
```

Relevant stores/calls: stage number append `0xc4154`, trigger level append `0xc4169`, counter conversion `0xc41b8`, contiguous flag append `0xc4231`, condition packing call `0xc40a1`.

### Serial trigger

Evidence range: `0xc4310..0xc474b`:

```text
valueChannel + device channel offset
valueWidth
valueData, uint16 little-endian
timeChannel + device channel offset
timeEdge
packed startCondition bytes
packed stopCondition bytes
```

Relevant appends/conversions: `0xc43c6`, `0xc4407`, `0xc4451`, `0xc44bb`, `0xc44fc`, and condition pack calls `0xc45d5`, `0xc46e6`.

