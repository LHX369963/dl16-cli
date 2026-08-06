# DL16 Protocol Reference

Status: the DL16 acquisition path is implemented and hardware-verified; unknown
fields are explicitly labelled rather than guessed. This index keeps the stable
path while loading only the needed protocol detail.

## Command and transport

- [USB IDs and command transport](transport.md)
- [Command IDs and raw experiment interface](commands.md)
- [PWM protocol and verified operating range](pwm.md)
- [USB hardware backend and recovery](backend.md)

## Acquisition

- [Sampling configuration and rate mapping](sampling.md)
- [Trigger configuration](triggers.md)
- [Receive packet framing and information responses](packet-framing.md)
- [Capture modes and completion](capture-modes.md)
- [Packed samples and hardware RLE](samples.md)
- [Export, sessions, and offline decoding](workflows.md)

For binary/disassembly provenance, use the separate
[evidence summary](evidence-summary.md).
