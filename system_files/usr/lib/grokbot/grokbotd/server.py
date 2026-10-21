"""Transports: unix socket (newline-delimited JSON-RPC) and HTTP on
127.0.0.1 (POST /v1/rpc, GET /v1/health, GET /v1/schema)."""
import json
import os
import re
import socket
import socketserver
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import VERSION, audit, paths, policy

MAX_BODY = 64 * 1024


def _host_ok(host, port):
    """DNS-rebinding guard: the Host header must name loopback."""
    if not host:
        return False
    host = host.lower()
    return bool(re.fullmatch(r"(127\.0\.0\.1|localhost|[a-z0-9][a-z0-9.-]*\.app\.localhost):%d" % port, host))


def _origin_ok(origin):
    return bool(re.fullmatch(r"https?://[a-z0-9.-]+(:\d+)?", origin or ""))


class UnixHandler(socketserver.StreamRequestHandler):
    def handle(self):
        creds = self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, _ = struct.unpack("3i", creds)
        if uid != os.getuid():
            audit.record(transport="unix", principal="local:uid=%d" % uid, decision="deny",
                         error="foreign_uid", pid=pid)
            return
        principal = "local:uid=%d" % uid
        while True:
            line = self.rfile.readline(MAX_BODY + 1)
            if not line:
                return
            if len(line) > MAX_BODY:
                resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "request too large"}}
            else:
                try:
                    req = json.loads(line)
                except ValueError:
                    req = None
                resp = self.server.dispatcher.handle(req, principal, "unix")
            self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class HttpHandler(BaseHTTPRequestHandler):
    server_version = "grokbotd/" + VERSION
    sys_version = ""

    def log_message(self, fmt, *args):
        pass  # the audit log records RPC calls; access logs would leak titles

    def _send(self, code, body, origin=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self):
        uid = policy.tcp_peer_uid(self.client_address[1], self.server.server_address[1])
        if uid != os.getuid():
            audit.record(transport="http", principal="http:uid=%s" % uid, decision="deny",
                         error="foreign_uid")
            self._send(403, {"error": "forbidden"})
            return None
        if not _host_ok(self.headers.get("Host"), self.server.server_address[1]):
            audit.record(transport="http", principal="http:bad-host", decision="deny",
                         error="bad_host", host=self.headers.get("Host"))
            self._send(403, {"error": "forbidden host"})
            return None
        origin = self.headers.get("Origin")
        if origin is None:
            return ("http:no-origin", None)
        if not _origin_ok(origin):
            return ("http:bad-origin", None)
        return ("origin:" + origin, origin if policy.origin_known(origin) else None)

    def do_OPTIONS(self):
        g = self._guard()
        if g is None:
            return
        principal, cors = g
        if not cors:
            audit.record(transport="http", principal=principal, decision="deny", error="preflight")
            self._send(403, {"error": "origin not allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", cors)
        self.send_header("Access-Control-Allow-Methods", "POST, GET")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self):
        g = self._guard()
        if g is None:
            return
        _, cors = g
        if self.path == "/v1/health":
            self._send(200, {"ok": True, "service": "grokbotd", "version": VERSION}, cors)
        elif self.path == "/v1/schema":
            self._send(200, self.server.dispatcher.schema, cors)
        else:
            self._send(404, {"error": "not found"}, cors)

    def do_POST(self):
        g = self._guard()
        if g is None:
            return
        principal, cors = g
        if self.path != "/v1/rpc":
            self._send(404, {"error": "not found"}, cors)
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # Forces a CORS preflight for browsers: no "simple" form POSTs.
            audit.record(transport="http", principal=principal, decision="deny", error="content_type")
            self._send(415, {"error": "Content-Type must be application/json"}, cors)
            return
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            self._send(413, {"error": "body too large"}, cors)
            return
        try:
            req = json.loads(self.rfile.read(n) or b"null")
        except ValueError:
            req = None
        resp = self.server.dispatcher.handle(req, principal, "http")
        code = 200
        if "error" in resp and resp["error"]["code"] == -32001:
            code = 403
        self._send(code, resp, cors)


class HttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(dispatcher, http=True):
    sock = paths.socket_path()
    os.makedirs(os.path.dirname(sock), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(sock), 0o700)
    if os.path.exists(sock):
        os.unlink(sock)
    old = os.umask(0o177)
    try:
        us = UnixServer(sock, UnixHandler)
    finally:
        os.umask(old)
    us.dispatcher = dispatcher
    threads = [threading.Thread(target=us.serve_forever, daemon=True)]
    hs = None
    if http:
        hs = HttpServer(("127.0.0.1", paths.http_port()), HttpHandler)
        hs.dispatcher = dispatcher
        threads.append(threading.Thread(target=hs.serve_forever, daemon=True))
    for t in threads:
        t.start()
    return us, hs
