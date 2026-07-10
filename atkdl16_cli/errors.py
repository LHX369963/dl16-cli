class AtkDl16Error(Exception):
    """Base exception for atkdl16-cli."""


class ProtocolError(AtkDl16Error):
    """Raised when a command payload or protocol frame is invalid."""


class UsbBackendError(AtkDl16Error):
    """Raised when the selected USB backend cannot complete an operation."""


class FirmwareUpdateError(AtkDl16Error):
    """Raised when a guarded firmware update does not receive the recovered acknowledgement."""
