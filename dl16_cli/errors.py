class Dl16Error(Exception):
    """Base exception for dl16-cli."""


class ProtocolError(Dl16Error):
    """Raised when a command payload or protocol frame is invalid."""


class UsbBackendError(Dl16Error):
    """Raised when the selected USB backend cannot complete an operation."""
