"""Argument parser for the DL16 command-line interface."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dl16")
    parser.add_argument("--dry-run", action="store_true", help="print frames without accessing USB hardware")
    parser.add_argument("--vid-pid", default=None, help="select USB device as VID:PID hex, for example 1a86:ffcc")
    parser.add_argument("--timeout-ms", type=int, default=1000, help="USB timeout in milliseconds")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list supported or attached devices")
    info = sub.add_parser("info", help="query device information")
    info.add_argument("--raw", action="store_true", help="also include the complete raw response")
    session = sub.add_parser("session", help="run newline-delimited JSON commands over one persistent link")
    session.add_argument("--commands", default="-", help="JSONL command file; '-' reads standard input")

    stop = sub.add_parser("stop", help="send stop command")
    stop.add_argument("--channel", type=int, default=None)

    pwm = sub.add_parser("pwm", help="PWM commands")
    pwm_sub = pwm.add_subparsers(dest="pwm_command", required=True)
    pwm_start = pwm_sub.add_parser("start", help="start PWM")
    pwm_start.add_argument("--channel", type=int, required=True)
    pwm_start.add_argument("--freq", type=int, required=True)
    pwm_start.add_argument("--duty", type=float, required=True)
    pwm_stop = pwm_sub.add_parser("stop", help="stop PWM")
    pwm_stop.add_argument("--channel", type=int, required=True)
    pwm_verify = pwm_sub.add_parser("verify", help="set PWM, capture inputs, and measure in one call")
    pwm_verify.add_argument("--pwm0", help="frequency,duty; for example 1kHz,25")
    pwm_verify.add_argument("--pwm1", help="frequency,duty; for example 2kHz,75")
    pwm_verify.add_argument("--input0", type=int, help="input wired to PWM0")
    pwm_verify.add_argument("--input1", type=int, help="input wired to PWM1")

    capture = sub.add_parser("capture", help="capture configuration and acquisition")
    capture_sub = capture.add_subparsers(dest="capture_command", required=True)
    configure = capture_sub.add_parser("configure", help="send recovered sampling parameters")
    configure.add_argument("--set-time", type=float, required=True, help="original settingData.setTime value")
    configure.add_argument("--set-hz", type=int, required=True, help="sampling frequency in Hz")
    configure.add_argument("--trigger-position", type=float, required=True, help="trigger position percent")
    configure.add_argument("--threshold", type=float, required=True, help="threshold level in volts")
    configure.add_argument("--sample-index", type=int, required=True, help="original settingData.index value")
    configure.add_argument("--rle", action="store_true", help="enable hardware RLE flag")
    configure.add_argument("--buffer", action="store_true", help="enable buffer mode flag")
    configure.add_argument("--collect-type", type=int, default=1, help="original collectType value")
    parse_capture = capture_sub.add_parser("parse", help="parse a saved raw DL16 receive stream")
    parse_capture.add_argument("--input", required=True, help="input file containing concatenated wire packets")
    read_capture = capture_sub.add_parser("read", help="read and losslessly save DL16 packets from USB")
    read_capture.add_argument("--packets", type=int, required=True, help="number of complete packets to read")
    read_capture.add_argument("--output", required=True, help="output file for concatenated raw wire packets")
    read_capture.add_argument("--read-size", type=int, default=None, help="optional USB bulk-IN read size")
    decode_capture = capture_sub.add_parser("decode", help="decode type-1 packets into per-channel packed samples")
    decode_capture.add_argument("--input", required=True)
    decode_capture.add_argument("--output-dir", required=True)
    decode_capture.add_argument("--rle", action="store_true", help="expand recovered value/count RLE pairs")
    export = capture_sub.add_parser("export", help="export decoded channels as CSV, edge CSV, or VCD")
    export.add_argument("--input-dir", required=True, help="decoded capture directory containing manifest.json")
    export.add_argument("--output", required=True, help="destination file")
    export.add_argument("--format", required=True, choices=("csv", "edges", "vcd"))
    run_capture = capture_sub.add_parser(
        "run", help="initialize, configure, trigger, acquire and decode in one process"
    )
    channel_selection = run_capture.add_mutually_exclusive_group(required=True)
    channel_selection.add_argument("--channel", type=int, help="single input channel, 0..15")
    channel_selection.add_argument("--channels", help="comma-separated input channels, for example 0,3,6")
    run_capture.add_argument("--set-time", type=float, required=True, help="capture time in milliseconds")
    run_capture.add_argument(
        "--set-hz", "--sample-rate", dest="set_hz", type=int, required=True,
        help="sampling frequency in Hz; the hardware index is selected automatically",
    )
    run_capture.add_argument("--trigger-position", type=float, default=0, help="trigger position percent (default: 0)")
    run_capture.add_argument(
        "--trigger", choices=("none", "rising", "high", "falling", "low", "either"),
        default="none", help="optional single-channel trigger condition",
    )
    run_capture.add_argument(
        "--trigger-channel", type=int, default=None,
        help="trigger channel; defaults to the first captured channel",
    )
    run_capture.add_argument(
        "--trigger-states", default=None, metavar="CH=STATE,...",
        help="multi-channel AND trigger, for example 7=rising,15=high",
    )
    run_capture.add_argument("--threshold", type=float, default=1.2, help="threshold level in volts (default: 1.2)")
    run_capture.add_argument(
        "--sample-index", type=int, default=None,
        help="optional recovered index assertion; normally selected automatically",
    )
    run_capture.add_argument("--buffer", action="store_true", help="use hardware Buffer acquisition mode")
    run_capture.add_argument("--rle", action="store_true", help="enable Buffer hardware RLE compression")
    run_capture.add_argument("--output-dir", required=True)
    run_capture.add_argument("--read-size", type=int, default=16384)
    run_capture.add_argument(
        "--trigger-timeout", type=float, default=30.0,
        help="seconds to wait for the first triggered sample (default: 30)",
    )
    run_capture.add_argument("--force", action="store_true", help="replace capture artifacts in output-dir")
    stream_capture = capture_sub.add_parser(
        "stream", help="capture Stream mode incrementally to disk; Ctrl-C retains synchronized data"
    )
    stream_selection = stream_capture.add_mutually_exclusive_group(required=True)
    stream_selection.add_argument("--channel", type=int, help="single input channel, 0..15")
    stream_selection.add_argument("--channels", help="comma-separated input channels")
    stream_capture.add_argument(
        "--duration", type=float, default=None,
        help="capture duration in seconds; omit to run until Ctrl-C or the 40-bit depth limit",
    )
    stream_capture.add_argument(
        "--set-hz", "--sample-rate", dest="set_hz", type=int, required=True,
        help="sampling frequency in Hz",
    )
    stream_capture.add_argument("--threshold", type=float, default=1.2, help="threshold level in volts")
    stream_capture.add_argument("--sample-index", type=int, default=None)
    stream_capture.add_argument("--output-dir", required=True)
    stream_capture.add_argument("--read-size", type=int, default=16384)
    stream_capture.add_argument("--force", action="store_true", help="replace capture artifacts in output-dir")
    measure = capture_sub.add_parser("measure", help="measure PWM frequency and duty from a capture")
    measure.add_argument("--input-dir", required=True)
    measure.add_argument("--channel", type=int, required=True)
    measure.add_argument("--json", action="store_true", help="show complete measurement metadata")
    sigrok = capture_sub.add_parser("sigrok", help="decode through the sigrok protocol library")
    sigrok_mode = sigrok.add_mutually_exclusive_group()
    sigrok_mode.add_argument("--list", action="store_true", help="list installed protocol decoders")
    sigrok_mode.add_argument("--show", metavar="DECODER", help="show decoder channels and options")
    sigrok.add_argument("--input-dir", help="decoded capture directory")
    sigrok.add_argument("--decoder", help="sigrok decoder ID, for example can or jtag")
    sigrok.add_argument(
        "--channel", action="append", default=[], metavar="NAME=CH",
        help="decoder channel mapping; repeat for multiple signals",
    )
    sigrok.add_argument(
        "--option", action="append", default=[], metavar="NAME=VALUE",
        help="decoder option; repeat for multiple options",
    )
    sigrok.add_argument("--annotations", default=None, help="sigrok annotation selection")
    sigrok.add_argument("--output", default=None, help="optional text output file")
    glitch_filter = capture_sub.add_parser("filter", help="remove short pulses into a derived capture")
    glitch_filter.add_argument("--input-dir", required=True)
    glitch_filter.add_argument("--output-dir", required=True)
    glitch_filter.add_argument("--max-samples", type=int, required=True)
    glitch_filter.add_argument("--channels", default=None, help="optional comma-separated channels")
    glitch_filter.add_argument("--force", action="store_true")
    search = capture_sub.add_parser("search", help="find samples matching channel conditions")
    search.add_argument("--input-dir", required=True)
    search.add_argument("--conditions", required=True, metavar="CH=STATE,...")
    search.add_argument("--start-sample", type=int, default=0)
    search.add_argument("--end-sample", type=int, default=None)
    search.add_argument("--limit", type=int, default=1000)
    search.add_argument("--output", default=None, help="optional JSON output file")
    uart = capture_sub.add_parser("uart", help="offline UART decode from a capture directory")
    uart.add_argument("--input-dir", required=True)
    uart.add_argument("--channel", type=int, required=True)
    uart.add_argument("--baud", type=int, required=True)
    uart.add_argument("--data-bits", type=int, default=8)
    uart.add_argument("--parity", choices=("none", "even", "odd"), default="none")
    uart.add_argument("--stop-bits", type=int, choices=(1, 2), default=1)
    uart.add_argument("--inverted", action="store_true")
    uart.add_argument("--output", default=None, help="optional JSON output file")
    i2c = capture_sub.add_parser("i2c", help="offline I2C decode from a capture directory")
    i2c.add_argument("--input-dir", required=True)
    i2c.add_argument("--scl", type=int, required=True, help="SCL channel")
    i2c.add_argument("--sda", type=int, required=True, help="SDA channel")
    i2c.add_argument("--output", default=None, help="optional JSON output file")
    spi = capture_sub.add_parser("spi", help="offline SPI decode from a capture directory")
    spi.add_argument("--input-dir", required=True)
    spi.add_argument("--clock", type=int, required=True)
    spi.add_argument("--mosi", type=int, default=None)
    spi.add_argument("--miso", type=int, default=None)
    spi.add_argument("--cs", type=int, default=None)
    spi.add_argument("--mode", type=int, choices=range(4), default=0)
    spi.add_argument("--bits-per-word", type=int, default=8)
    spi.add_argument("--bit-order", choices=("msb", "lsb"), default="msb")
    spi.add_argument("--output", default=None, help="optional JSON output file")

    trigger = sub.add_parser("trigger", help="configure recovered trigger modes")
    trigger_sub = trigger.add_subparsers(dest="trigger_command", required=True)
    simple = trigger_sub.add_parser("simple", help="configure simple per-channel trigger")
    simple.add_argument("--states", required=True, help="comma-separated states in channel order")
    simple.add_argument("--enabled", default=None, help="optional comma-separated 1/0 channel mask")
    simple.add_argument("--collect-type", type=int, default=1)
    simple.add_argument("--channel-offset", type=int, default=0)
    stage = trigger_sub.add_parser("stage", help="configure staged trigger from JSON")
    stage.add_argument("--file", required=True)
    serial = trigger_sub.add_parser("serial", help="configure serial trigger from JSON")
    serial.add_argument("--file", required=True)

    raw = sub.add_parser("raw", help="send recovered command IDs with raw hex payloads")
    raw_sub = raw.add_subparsers(dest="raw_command", required=True)
    for name in ("parameter-setting", "simple-trigger", "stage-trigger", "serial-trigger"):
        raw_cmd = raw_sub.add_parser(name, help=f"send raw {name} payload")
        raw_cmd.add_argument("--payload-hex", required=True, help="payload bytes as hexadecimal, spaces allowed")

    return parser

