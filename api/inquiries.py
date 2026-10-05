"""Vercel Function for portfolio contact enquiries."""
from http.server import BaseHTTPRequestHandler

from lib.admin_backend import MAX_BODY_BYTES, handle_inquiry_request


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = MAX_BODY_BYTES + 1
        if length > MAX_BODY_BYTES:
            status, headers, body = 413, [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")], b'{"error":"Request is too large."}'
        else:
            body = self.rfile.read(length) if length else b""
            status, headers, body = handle_inquiry_request(self.command, self.path, self.headers, body, production=True)
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return
