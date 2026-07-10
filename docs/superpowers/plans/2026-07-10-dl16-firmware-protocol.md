# DL16 MCU/Firmware Protocol Implementation Plan

**Goal:** Reproduce the recovered firmware frames and ACK validation safely before enabling guarded hardware writes.

1. Add tests for version, bootloader, update-mode, data, restart, and ACK frames.
2. Implement fixed 510-byte framed-MCU builders and 64-byte direct-mode chunks.
3. Add deterministic firmware chunk planning with target-specific commands.
4. Expose offline CLI inspection/planning only; do not flash hardware yet.
5. Document the two transport modes, target mapping, delays, ACK retries, and unresolved recovery risks.
6. Add a separately reviewed `--i-understand-this-can-brick` guarded execution path only after ACK reads can be tested.
