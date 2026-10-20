"""Minimal SNMPv1 client (GET and broadcast discovery) without external dependencies."""

from __future__ import annotations

import os
import socket
import time

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_DEVICE_DESCR = "1.3.6.1.2.1.25.3.2.1.3.1"
OID_BROTHER_STATUS = "1.3.6.1.4.1.2435.3.3.9.1.6.1.0"  # 32 byte raster status block

PORT = 161

Value = bytes | int | None


class SnmpError(Exception):
    pass


def _tlv(tag: int, payload: bytes) -> bytes:
    n = len(payload)
    if n < 0x80:
        length = bytes([n])
    else:
        raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
        length = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + length + payload


def _int(value: int) -> bytes:
    return _tlv(0x02, value.to_bytes(max(1, (value.bit_length() + 8) // 8), "big", signed=True))


def _oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.split(".")]
    out = bytearray([parts[0] * 40 + parts[1]])
    for part in parts[2:]:
        chunk = [part & 0x7F]
        part >>= 7
        while part:
            chunk.append(0x80 | (part & 0x7F))
            part >>= 7
        out += bytes(reversed(chunk))
    return _tlv(0x06, bytes(out))


def _read(buf: bytes, pos: int = 0) -> tuple[int, bytes, int]:
    """Read one TLV, return (tag, value, position after it)."""
    if pos + 2 > len(buf):
        raise SnmpError("truncated response")
    tag, length = buf[pos], buf[pos + 1]
    pos += 2
    if length & 0x80:
        k = length & 0x7F
        length = int.from_bytes(buf[pos:pos + k], "big")
        pos += k
    if pos + length > len(buf):
        raise SnmpError("truncated response")
    return tag, buf[pos:pos + length], pos + length


def _request(oid: str, community: str, request_id: int) -> bytes:
    varbinds = _tlv(0x30, _tlv(0x30, _oid(oid) + b"\x05\x00"))
    pdu = _tlv(0xA0, _int(request_id) + _int(0) + _int(0) + varbinds)
    return _tlv(0x30, _int(0) + _tlv(0x04, community.encode()) + pdu)


def _parse_response(data: bytes) -> tuple[int, int, Value]:
    """Return (request id, error status, value)."""
    _, message, _ = _read(data)
    _, _, pos = _read(message)  # version
    _, _, pos = _read(message, pos)  # community
    tag, pdu, _ = _read(message, pos)
    if tag != 0xA2:
        raise SnmpError("unexpected PDU type")
    _, request_id, pos = _read(pdu)
    _, error, pos = _read(pdu, pos)
    _, _, pos = _read(pdu, pos)  # error index
    _, varbinds, _ = _read(pdu, pos)
    _, varbind, _ = _read(varbinds)
    _, _, pos = _read(varbind)  # oid
    vtag, value, _ = _read(varbind, pos)
    if vtag == 0x04:
        parsed: Value = value
    elif vtag in (0x02, 0x41, 0x42, 0x43):
        parsed = int.from_bytes(value, "big", signed=vtag == 0x02)
    else:
        parsed = None
    return int.from_bytes(request_id, "big"), int.from_bytes(error, "big"), parsed


def get(host: str, oid: str, community: str = "public", timeout: float = 1.5, retries: int = 2) -> Value:
    """SNMP GET of a single OID. Returns None if the agent does not know the OID."""
    request_id = int.from_bytes(os.urandom(3), "big")
    message = _request(oid, community, request_id)
    try:
        address = socket.getaddrinfo(host, PORT, socket.AF_INET, socket.SOCK_DGRAM)[0][4]
    except socket.gaierror as exc:
        raise SnmpError(f"Host {host!r} nicht gefunden") from exc
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _ in range(retries + 1):
            sock.sendto(message, address)
            deadline = time.monotonic() + timeout
            while (remaining := deadline - time.monotonic()) > 0:
                sock.settimeout(remaining)
                try:
                    data, _ = sock.recvfrom(4096)
                except (socket.timeout, ConnectionResetError):
                    break
                try:
                    rid, error, value = _parse_response(data)
                except SnmpError:
                    continue
                if rid == request_id:
                    return None if error else value
    raise SnmpError(f"Keine SNMP-Antwort von {host}")


def _broadcast_addresses() -> list[str]:
    addresses = {"255.255.255.255"}
    local = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            local.add(info[4][0])
    except socket.gaierror:
        pass
    try:  # the primary interface; connect() on UDP sends nothing
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            local.add(probe.getsockname()[0])
    except OSError:
        pass
    for ip in local:
        if not ip.startswith("127."):
            addresses.add(ip.rsplit(".", 1)[0] + ".255")  # assumes a /24 network
    return sorted(addresses)


def discover(oid: str = OID_DEVICE_DESCR, community: str = "public", timeout: float = 2.0) -> dict[str, Value]:
    """Broadcast a GET and collect the answers as {ip: value}."""
    request_id = int.from_bytes(os.urandom(3), "big")
    message = _request(oid, community, request_id)
    found: dict[str, Value] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for address in _broadcast_addresses():
            try:
                sock.sendto(message, (address, PORT))
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            sock.settimeout(remaining)
            try:
                data, (ip, _) = sock.recvfrom(4096)
            except socket.timeout:
                break
            except ConnectionResetError:
                continue
            try:
                rid, error, value = _parse_response(data)
            except SnmpError:
                continue
            if rid == request_id and not error:
                found[ip] = value
    return found
