from __future__ import annotations

from pathlib import Path

from .errors import AtkDl16Error


def prepare_capture_directory(path: str | Path, *, overwrite: bool = False) -> Path:
    """Create a capture directory without silently mixing old and new artifacts."""

    destination = Path(path)
    try:
        destination.mkdir(parents=True, exist_ok=True)
        artifacts = [destination / "manifest.json", destination / "wire.bin"]
        artifacts.extend(destination.glob("channel-*.bin"))
        existing = [item for item in artifacts if item.exists()]
        if existing and not overwrite:
            names = ", ".join(sorted(item.name for item in existing))
            raise AtkDl16Error(
                f"capture output {str(destination)!r} already contains {names}; "
                "choose another directory or use --force"
            )
        for item in existing:
            item.unlink()
    except AtkDl16Error:
        raise
    except OSError as exc:
        raise AtkDl16Error(f"cannot prepare capture output {str(destination)!r}: {exc}") from exc
    return destination
