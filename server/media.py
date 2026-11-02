"""Tiny LAN-only HTTP server that hands the alarm file to the Nest."""

import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

log = logging.getLogger(__name__)


def make_media_server(host: str, port: int, path: Path, content_type: str) -> ThreadingHTTPServer:
    """Serve exactly one file at /<filename>; everything else is a 404."""
    data = path.read_bytes()
    route = "/" + quote(path.name)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._send(body=True)

        def do_HEAD(self):
            self._send(body=False)

        def _send(self, body: bool):
            if self.path.split("?", 1)[0] != route:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if body:
                self.wfile.write(data)

        def log_message(self, fmt, *args):
            log.debug("media %s - %s", self.client_address[0], fmt % args)

    return ThreadingHTTPServer((host, port), Handler)
