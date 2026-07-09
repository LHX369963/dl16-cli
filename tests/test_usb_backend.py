import pytest

from atkdl16_cli.errors import ProtocolError
from atkdl16_cli.usb import PyUsbUnavailableError, is_supported_usb_id, parse_usb_id


def test_parse_usb_id_accepts_lower_and_upper_hex():
    assert parse_usb_id("1a86:ffcc") == (0x1A86, 0xFFCC)
    assert parse_usb_id("04B4:6A6A") == (0x04B4, 0x6A6A)


@pytest.mark.parametrize("text", ["", "1a86", "1a86-ffcc", "xyz:ffcc", "10000:0001", "1:2:3"])
def test_parse_usb_id_rejects_malformed_values(text):
    with pytest.raises(ProtocolError):
        parse_usb_id(text)


def test_is_supported_usb_id_matches_reverse_evidence():
    assert is_supported_usb_id(0x1A86, 0xFFCC)
    assert is_supported_usb_id(0x1A86, 0x6A6B)
    assert is_supported_usb_id(0x04B4, 0x6A6A)
    assert not is_supported_usb_id(0x1234, 0x5678)


def test_pyusb_unavailable_error_is_usb_backend_error():
    from atkdl16_cli.errors import UsbBackendError

    assert issubclass(PyUsbUnavailableError, UsbBackendError)
