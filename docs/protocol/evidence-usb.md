# Evidence: USB discovery and transports

## USB discovery

Evidence: `../../reverse/disasm_116240_logic_analyzer_find_.s` (`logic_analyzer_find`).

The application initializes libusb, enumerates devices, reads descriptors, and accepts these IDs:

- `VID 0x1a86, PID 0xffcc`
- `VID 0x1a86, PID 0x6a6b`
- `VID 0x04b4, PID 0x6a6a`

`logic_analyzer_open` claims interface 0 after enabling auto-detach:

- Evidence: `../../reverse/disasm_115f80_logic_analyzer_open_LogicAnalyzer_.s`
- Calls: `libusb_set_auto_detach_kernel_driver(handle, 1)`, `libusb_claim_interface(handle, 0)`.

## Transfer modes and endpoints

Evidence: `../../reverse/disasm_118680_USBControl::Init_libusb_device_libusb_context_int_int_bool_.s`.

The program supports both interrupt and bulk-style paths:

- Interrupt write path: `USBControl::SendToLIBUSB_Interrupt` -> `libusb_interrupt_transfer`.
- Bulk/async path: `USBControl::SendToLIBUSB` -> `libusb_submit_transfer`.
- Synchronous read path: `USBControl::ReadSynchronousLIBUSB` -> `libusb_bulk_transfer`.
- Interrupt read path: `USBControl::ReadSynchronousLIBUSB_Interrupt` -> `libusb_interrupt_transfer`.

Endpoint fields are stored in the `LogicAnalyzer` object:

- write endpoint at object offset `0x24`
- read endpoint at object offset `0x25`

Known constants assigned during initialization include `0xffff8101` and `0xffff8102`; the endpoint byte used by libusb is read with `movzbl 0x24/0x25`, so the low byte must be validated against real descriptors or runtime traces before finalizing endpoint direction/mapping.

