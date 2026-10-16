"""Test-only PostgreSQL reply-loss proxy; never logs packets or enters the learner sandbox."""

import selectors
import socket
import socketserver
from pathlib import Path
from threading import Event, Lock, Thread


class CommitReplyLoss:
    def __init__(self, host: str, port: int, arm: Path):
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("Fault proxy permits loopback test PostgreSQL only")
        self.arm, self.dropped, self.closed = arm, Event(), Event()
        self.lock = Lock()
        owner = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with socket.create_connection((host, port), timeout=5) as upstream:
                    upstream.settimeout(5)
                    self.request.settimeout(5)
                    buffered = bytearray()
                    with selectors.DefaultSelector() as selector:
                        selector.register(self.request, selectors.EVENT_READ, False)
                        selector.register(upstream, selectors.EVENT_READ, True)
                        try:
                            while not owner.closed.is_set():
                                for key, _ in selector.select(0.1):
                                    chunk = key.fileobj.recv(65536)
                                    if not chunk:
                                        return
                                    if not key.data:
                                        upstream.sendall(chunk)
                                        continue
                                    buffered.extend(chunk)
                                    while len(buffered) >= 5:
                                        length = int.from_bytes(buffered[1:5], "big")
                                        if not 4 <= length <= 1_048_576:
                                            raise ValueError(
                                                "Unexpected bounded test protocol frame"
                                            )
                                        if len(buffered) < length + 1:
                                            break
                                        packet = bytes(buffered[: length + 1])
                                        del buffered[: length + 1]
                                        with owner.lock:
                                            if (
                                                packet[:1] == b"C"
                                                and packet[5:] == b"COMMIT\x00"
                                                and owner.arm.exists()
                                                and not owner.dropped.is_set()
                                            ):
                                                owner.dropped.set()
                                                self.request.shutdown(socket.SHUT_RDWR)
                                                return
                                        self.request.sendall(packet)
                        except (ConnectionError, TimeoutError):
                            # Expected disconnect; independent DB assertions determine the outcome.
                            return

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
            block_on_close = False

        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.1})

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.closed.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
