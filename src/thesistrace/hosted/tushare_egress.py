import select
import socket
import socketserver

ALLOWED_HOST = "api.tushare.pro"
ALLOWED_PORT = 443
MAX_HEADER_BYTES = 16_384


class TushareConnectHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(10)
        request = self._read_headers()
        if not request:
            return
        if connect_authority(request) != (
            ALLOWED_HOST,
            ALLOWED_PORT,
        ):
            self.connection.sendall(
                b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            return
        try:
            upstream = socket.create_connection(
                (ALLOWED_HOST, ALLOWED_PORT),
                timeout=10,
            )
        except OSError:
            self.connection.sendall(
                b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            return
        with upstream:
            self.connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self.connection.settimeout(30)
            upstream.settimeout(30)
            self._relay(upstream)

    def _read_headers(self) -> bytes:
        payload = bytearray()
        while b"\r\n\r\n" not in payload:
            chunk = self.connection.recv(4096)
            if not chunk:
                break
            payload.extend(chunk)
            if len(payload) > MAX_HEADER_BYTES:
                return b""
        return bytes(payload)

    def _relay(self, upstream: socket.socket) -> None:
        peers = (self.connection, upstream)
        while True:
            readable, _, _ = select.select(peers, (), (), 30)
            if not readable:
                return
            for source in readable:
                payload = source.recv(65_536)
                if not payload:
                    return
                destination = upstream if source is self.connection else self.connection
                destination.sendall(payload)


class TushareEgressServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def connect_authority(
    request: bytes,
) -> tuple[str, int] | None:
    try:
        request_line = request.split(b"\r\n", 1)[0].decode("ascii")
        method, authority, version = request_line.split(" ")
        host, raw_port = authority.rsplit(":", 1)
        port = int(raw_port)
    except (UnicodeDecodeError, ValueError):
        return None
    if method != "CONNECT" or version not in {
        "HTTP/1.0",
        "HTTP/1.1",
    }:
        return None
    return host.lower(), port


def main() -> None:
    with TushareEgressServer(
        ("0.0.0.0", 8080),
        TushareConnectHandler,
    ) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
