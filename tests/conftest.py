import os
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Iterable, NamedTuple, Union

import pytest

# Qt widgets render off-screen during tests.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@dataclass
class Route:
    """A scripted response. body may be bytes or a callable yielding chunks (streamed)."""
    body: Union[bytes, str, Callable[[], Iterable[bytes]]] = b''
    status: int = 200
    headers: dict = field(default_factory=lambda: {'Content-Type': 'text/html; charset=utf-8'})
    delay: float = 0.0


class Request(NamedTuple):
    method: str
    path: str
    time: float  # time.monotonic() when it arrived
    body: str
    headers: dict


class WebServer:
    def __init__(self):
        self.routes = {}
        self.requests = []  # every Request received, in order
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_GET(self):
                self._respond('GET')

            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                self._respond('POST', self.rfile.read(length).decode('utf-8'))

            def _respond(self, method, body=''):
                path = self.path.split('?', 1)[0]
                server.requests.append(Request(method, path, time.monotonic(), body, dict(self.headers)))
                route = server.routes.get((method, path)) or server.routes.get(path)
                if route is None:
                    route = Route(body=b'not found', status=404)
                time.sleep(route.delay)
                body = route.body.encode('utf-8') if isinstance(route.body, str) else route.body
                self.send_response(route.status)
                for name, value in route.headers.items():
                    self.send_header(name, value)
                try:
                    if callable(body):
                        self.send_header('Connection', 'close')
                        self.end_headers()
                        for chunk in body():
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    else:
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                except (ConnectionError, OSError):
                    pass  # the client went away (e.g. a cancelled download)

            def log_message(self, *args):
                pass

        class QuietServer(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass  # clients hanging up mid-response (cancelled downloads) are expected

        self._httpd = QuietServer(('127.0.0.1', 0), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def url(self, path='/'):
        return f'http://127.0.0.1:{self._httpd.server_port}{path}'

    def route(self, path, route: Route, method=None):
        self.routes[(method, path) if method else path] = route

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def web():
    server = WebServer()
    yield server
    server.close()
