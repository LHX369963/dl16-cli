from atkdl16_cli import __version__
from atkdl16_cli.errors import AtkDl16Error, ProtocolError, UsbBackendError


def test_package_exports_version_string():
    assert isinstance(__version__, str)
    assert __version__


def test_error_hierarchy():
    assert issubclass(ProtocolError, AtkDl16Error)
    assert issubclass(UsbBackendError, AtkDl16Error)
