# Boundaries, protocol evidence, and development

Use public `dl16` commands, not libusb or raw protocol calls, where a workflow
exists. Never issue USB `SET_CONFIGURATION`: it breaks the DL16 link. Endpoint
clear/reset is automated recovery after failed handshake, not normal preflight.

Protocol fields and reverse-engineering evidence are in
[`../protocol/protocol.md`](../protocol/protocol.md) and
[`../protocol/evidence-summary.md`](../protocol/evidence-summary.md). Sample
index 7 repeatedly returned no type-1 data and is deliberately excluded from
automatic selection.

The test suite covers protocol construction, USB transport, triggers, capture,
RLE, directories, analysis, exports, sessions, and native decoders. For code
changes install `.[test]` and run `pytest -q`. Connected acceptance is a
development workflow, not a daily-use prerequisite; read the dated acceptance
reports only when its evidence matters. Do not claim untested behavior, GUI
parity, another model's capability, or physical accuracy from unit tests.

Keep README and Skill as short navigation; put feature examples in `docs/usage/`.
