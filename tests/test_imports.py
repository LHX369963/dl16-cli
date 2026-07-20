from dl16_cli import __version__
from dl16_cli.errors import Dl16Error, ProtocolError, UsbBackendError


def test_package_exports_version_string():
    assert isinstance(__version__, str)
    assert __version__


def test_error_hierarchy():
    assert issubclass(ProtocolError, Dl16Error)
    assert issubclass(UsbBackendError, Dl16Error)
