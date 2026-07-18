from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import AtkDl16Error
from .export import export_capture


def _executable() -> str:
    executable = shutil.which("sigrok-cli")
    if executable is None:
        raise AtkDl16Error(
            "sigrok-cli is not installed; on Debian/Ubuntu run: sudo apt install sigrok-cli"
        )
    return executable


def _run(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            [_executable(), *arguments], text=True, capture_output=True, check=False
        )
    except OSError as exc:
        raise AtkDl16Error(f"cannot run sigrok-cli: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise AtkDl16Error(f"sigrok-cli failed: {detail}")
    return result.stdout


def list_sigrok_decoders() -> str:
    output = _run(["--list-supported"])
    marker = "Supported protocol decoders:\n"
    if marker not in output:
        raise AtkDl16Error("sigrok-cli did not report its protocol decoder list")
    return output.split(marker, 1)[1]


def show_sigrok_decoder(decoder: str) -> str:
    _validate_component("decoder", decoder)
    return _run(["-P", decoder, "--show"])


def _validate_component(label: str, value: str) -> None:
    if not value or any(character in value for character in ":=,\n\r"):
        raise AtkDl16Error(f"invalid sigrok {label}: {value!r}")


def _parse_assignments(values: list[str], *, channels: bool) -> list[str]:
    assignments = []
    seen = set()
    for value in values:
        parts = value.split("=", 1)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            kind = "channel" if channels else "option"
            raise AtkDl16Error(f"sigrok {kind} must use NAME=VALUE syntax")
        name, assigned = (part.strip() for part in parts)
        _validate_component("assignment name", name)
        if name in seen:
            raise AtkDl16Error(f"duplicate sigrok assignment: {name}")
        seen.add(name)
        if channels:
            try:
                channel = int(assigned, 10)
            except ValueError as exc:
                raise AtkDl16Error(f"sigrok channel must be 0..15, got {assigned!r}") from exc
            if not 0 <= channel <= 15:
                raise AtkDl16Error(f"sigrok channel must be 0..15, got {channel}")
            assigned = f"CH{channel}"
        elif any(character in assigned for character in ":\n\r"):
            raise AtkDl16Error(f"invalid sigrok option value: {assigned!r}")
        assignments.append(f"{name}={assigned}")
    return assignments


def decode_with_sigrok(
    capture_dir: str | Path,
    *,
    decoder: str,
    channels: list[str],
    options: list[str] | None = None,
    annotations: str | None = None,
) -> str:
    _validate_component("decoder", decoder)
    channel_assignments = _parse_assignments(channels, channels=True)
    option_assignments = _parse_assignments(options or [], channels=False)
    if not channel_assignments:
        raise AtkDl16Error("sigrok decode requires at least one --channel NAME=CH mapping")
    decoder_spec = ":".join((decoder, *channel_assignments, *option_assignments))
    annotation_spec = annotations or decoder
    with tempfile.TemporaryDirectory(prefix="atkdl16-sigrok-") as temporary:
        vcd = Path(temporary) / "capture.vcd"
        export_capture(capture_dir, vcd, format="vcd")
        return _run(["-i", str(vcd), "-I", "vcd", "-P", decoder_spec, "-A", annotation_spec])
