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

class FakeEndpoint:
    def __init__(self, address, max_packet_size=64):
        self.bEndpointAddress = address
        self.wMaxPacketSize = max_packet_size
        self.writes = []
        self.reads = []


class FakeInterface:
    bInterfaceNumber = 0

    def __init__(self, endpoints):
        self._endpoints = endpoints

    def __iter__(self):
        return iter(self._endpoints)


class FakeConfig:
    def __init__(self, interfaces):
        self._interfaces = interfaces

    def __iter__(self):
        return iter(self._interfaces)


class FakeDevice:
    def __init__(self, vid, pid, bus=1, address=2, speed="high", configs=None):
        self.idVendor = vid
        self.idProduct = pid
        self.bus = bus
        self.address = address
        self.speed = speed
        self.configs = configs or []
        self.detached = []
        self.claimed = []
        self.configuration_set = False

    def __iter__(self):
        return iter(self.configs)

    def is_kernel_driver_active(self, interface):
        return True

    def detach_kernel_driver(self, interface):
        self.detached.append(interface)

    def set_configuration(self):
        self.configuration_set = True


class FakeCore:
    def __init__(self, devices):
        self.devices = devices

    def find(self, find_all=False, idVendor=None, idProduct=None):
        matches = [d for d in self.devices if (idVendor is None or d.idVendor == idVendor) and (idProduct is None or d.idProduct == idProduct)]
        if find_all:
            return matches
        return matches[0] if matches else None


class FakeUtil:
    ENDPOINT_OUT = 0
    ENDPOINT_IN = 0x80

    @staticmethod
    def endpoint_direction(address):
        return address & 0x80

    @staticmethod
    def claim_interface(device, interface):
        device.claimed.append(interface)

    @staticmethod
    def release_interface(device, interface):
        device.claimed.remove(interface)

    @staticmethod
    def dispose_resources(device):
        device.disposed = True


def make_supported_fake_device():
    out_ep = FakeEndpoint(0x02, 512)
    in_ep = FakeEndpoint(0x81, 512)
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    return dev, out_ep, in_ep


def test_pyusb_backend_lists_only_supported_devices():
    from atkdl16_cli.usb import PyUsbBackend

    supported, _, _ = make_supported_fake_device()
    unsupported = FakeDevice(0x1234, 0x5678)
    backend = PyUsbBackend(usb_core=FakeCore([supported, unsupported]), usb_util=FakeUtil)
    assert [item.usb_id for item in backend.list_devices()] == ["1a86:ffcc"]


def test_pyusb_backend_open_selects_endpoints_and_claims_interface_zero():
    from atkdl16_cli.usb import PyUsbBackend

    dev, out_ep, in_ep = make_supported_fake_device()
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    backend.open()
    assert backend.write_endpoint is out_ep
    assert backend.read_endpoint is in_ep
    assert dev.detached == [0]
    assert dev.claimed == [0]
    assert dev.configuration_set is True


def test_pyusb_backend_close_releases_interface_and_disposes_resources():
    from atkdl16_cli.usb import PyUsbBackend

    dev, _, _ = make_supported_fake_device()
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    backend.open()
    backend.close()
    assert dev.claimed == []
    assert dev.disposed is True

class FakeIoEndpoint(FakeEndpoint):
    def __init__(self, address, max_packet_size=64, read_data=b"\xaa\xbb"):
        super().__init__(address, max_packet_size)
        self.read_data = read_data

    def write(self, data, timeout=None):
        self.writes.append((bytes(data), timeout))
        return len(data)

    def read(self, size, timeout=None):
        self.reads.append((size, timeout))
        return list(self.read_data)


def test_pyusb_backend_send_frame_writes_and_reads_response():
    from atkdl16_cli.usb import PyUsbBackend

    out_ep = FakeIoEndpoint(0x02, 512)
    in_ep = FakeIoEndpoint(0x81, 512, read_data=b"\x12\x34")
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil, timeout_ms=250)
    backend.open()
    response = backend.send_frame(b"abc")
    assert out_ep.writes == [(b"abc", 250)]
    assert in_ep.reads == [(512, 250)]
    assert response == b"\x12\x34"


def test_pyusb_backend_read_chunk_opens_and_reads_bulk_in_without_writing():
    from atkdl16_cli.usb import PyUsbBackend

    out_ep = FakeIoEndpoint(0x02, 512)
    in_ep = FakeIoEndpoint(0x81, 512, read_data=b"capture")
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(
        device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil, timeout_ms=250
    )
    assert backend.read_chunk() == b"capture"
    assert in_ep.reads == [(512, 250)]
    assert out_ep.writes == []


def test_pyusb_backend_read_chunk_allows_size_and_timeout_override():
    from atkdl16_cli.usb import PyUsbBackend

    out_ep = FakeIoEndpoint(0x02, 512)
    in_ep = FakeIoEndpoint(0x81, 512, read_data=b"abc")
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    assert backend.read_chunk(size=4096, timeout_ms=900) == b"abc"
    assert in_ep.reads == [(4096, 900)]


def test_dry_run_backend_returns_queued_read_chunks():
    from atkdl16_cli.usb import DryRunBackend

    backend = DryRunBackend(read_chunks=[b"one", b"two"])
    assert backend.read_chunk() == b"one"
    assert backend.read_chunk() == b"two"
    assert backend.read_chunk() == b""
