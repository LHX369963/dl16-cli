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
        self.cleared_halts = []
        self.reset_count = 0

    def __iter__(self):
        return iter(self.configs)

    def is_kernel_driver_active(self, interface):
        return True

    def detach_kernel_driver(self, interface):
        self.detached.append(interface)

    def set_configuration(self):
        self.configuration_set = True

    def clear_halt(self, endpoint):
        self.cleared_halts.append(endpoint)

    def reset(self):
        self.reset_count += 1


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


def test_pyusb_backend_open_claims_interface_without_resetting_active_configuration():
    from atkdl16_cli.usb import PyUsbBackend

    dev, out_ep, in_ep = make_supported_fake_device()
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    backend.open()
    assert backend.write_endpoint is out_ep
    assert backend.read_endpoint is in_ep
    assert dev.detached == [0]
    assert dev.claimed == [0]
    assert dev.configuration_set is False


def test_pyusb_backend_open_wraps_permission_error_with_udev_hint():
    from atkdl16_cli.errors import UsbBackendError
    from atkdl16_cli.usb import PyUsbBackend

    class PermissionUtil(FakeUtil):
        @staticmethod
        def claim_interface(device, interface):
            error = PermissionError("access denied")
            error.errno = 13
            raise error

    dev, _, _ = make_supported_fake_device()
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=PermissionUtil)
    with pytest.raises(UsbBackendError, match="udev/99-atk-dl16.rules"):
        backend.open()


def test_pyusb_backend_close_releases_interface_and_disposes_resources():
    from atkdl16_cli.usb import PyUsbBackend

    dev, _, _ = make_supported_fake_device()
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    backend.open()
    backend.close()
    assert dev.claimed == []
    assert dev.disposed is True


def test_pyusb_backend_recover_ffcc_link_clears_endpoints_resets_and_reopens():
    from atkdl16_cli.usb import PyUsbBackend

    dev, out_ep, in_ep = make_supported_fake_device()
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    backend.recover_ffcc_link()
    assert dev.cleared_halts == [0x02, 0x81]
    assert dev.reset_count == 1
    assert backend.write_endpoint is out_ep
    assert backend.read_endpoint is in_ep
    assert dev.claimed == [0]

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


def test_ffcc_transport_interleave_matches_recovered_four_word_lanes():
    from atkdl16_cli.usb import encode_ffcc_transport

    logical = b"".join(index.to_bytes(2, "little") for index in range(1024))
    wire = encode_ffcc_transport(logical)
    assert wire[:8] == b"\x00\x00\x04\x00\x08\x00\x0c\x00"
    assert wire[512:520] == b"\x01\x00\x05\x00\x09\x00\x0d\x00"
    assert wire[1024:1032] == b"\x02\x00\x06\x00\x0a\x00\x0e\x00"
    assert wire[1536:1544] == b"\x03\x00\x07\x00\x0b\x00\x0f\x00"


def test_ffcc_transport_decode_reverses_interleave():
    from atkdl16_cli.usb import decode_ffcc_transport, encode_ffcc_transport

    logical = bytes(range(256)) * 8
    assert decode_ffcc_transport(encode_ffcc_transport(logical)) == logical


def test_pyusb_backend_send_frame_pads_and_interleaves_ffcc_normal_command():
    from atkdl16_cli.usb import PyUsbBackend, encode_ffcc_transport

    out_ep = FakeIoEndpoint(0x02, 512)
    logical_response = b"\x12\x34" + bytes(2046)
    in_ep = FakeIoEndpoint(0x81, 512, read_data=encode_ffcc_transport(logical_response))
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil, timeout_ms=250)
    backend.open()
    response = backend.send_frame(b"abc")
    logical_request = b"abc" + bytes(2048 - 3)
    assert out_ep.writes == [(encode_ffcc_transport(logical_request), 250)]
    assert in_ep.reads == [(2048, 250)]
    assert response == logical_response


def test_pyusb_backend_write_frame_uses_ffcc_transport_without_reading():
    from atkdl16_cli.usb import PyUsbBackend, encode_ffcc_transport

    out_ep = FakeIoEndpoint(0x02, 512)
    in_ep = FakeIoEndpoint(0x81, 512, read_data=b"unused")
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    frame = b"\x00" * 8 + b"\x0a\x11\x01\x0b"
    assert backend.write_frame(frame) == 2048
    assert out_ep.writes == [(encode_ffcc_transport(frame.ljust(2048, b"\x00")), 1000)]
    assert in_ep.reads == []


def test_pyusb_backend_read_chunk_decodes_large_ffcc_capture_transfer():
    from atkdl16_cli.usb import PyUsbBackend, encode_ffcc_transport

    logical = (b"\x0a\x06\x03\x00\xff\x00\x00\x00\x0b").ljust(16384, b"\x00")
    out_ep = FakeIoEndpoint(0x02, 512)
    in_ep = FakeIoEndpoint(0x81, 512, read_data=encode_ffcc_transport(logical))
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    assert backend.read_chunk(size=16384) == logical


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


def test_pyusb_backend_write_chunk_does_not_consume_ack():
    from atkdl16_cli.usb import PyUsbBackend

    out_ep = FakeIoEndpoint(0x02, 512)
    in_ep = FakeIoEndpoint(0x81, 512, read_data=b"ack")
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(
        device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil, timeout_ms=250
    )
    assert backend.write_chunk(b"payload") == 7
    assert out_ep.writes == [(b"payload", 250)]
    assert in_ep.reads == []


def test_dry_run_backend_records_write_chunks_separately():
    from atkdl16_cli.usb import DryRunBackend

    backend = DryRunBackend()
    assert backend.write_chunk(b"one") == 3
    assert backend.written_chunks == [b"one"]


def test_pyusb_backend_wraps_endpoint_io_errors():
    from atkdl16_cli.errors import UsbBackendError
    from atkdl16_cli.usb import PyUsbBackend

    class BrokenEndpoint(FakeIoEndpoint):
        def write(self, data, timeout=None):
            raise RuntimeError("write failed")

        def read(self, size, timeout=None):
            raise RuntimeError("read failed")

    out_ep = BrokenEndpoint(0x02, 512)
    in_ep = BrokenEndpoint(0x81, 512)
    dev = FakeDevice(0x1A86, 0xFFCC, configs=[FakeConfig([FakeInterface([out_ep, in_ep])])])
    backend = PyUsbBackend(device=dev, usb_core=FakeCore([dev]), usb_util=FakeUtil)
    with pytest.raises(UsbBackendError, match="write failed"):
        backend.write_chunk(b"x")
    with pytest.raises(UsbBackendError, match="read failed"):
        backend.read_chunk()
