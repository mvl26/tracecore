"""HTTP cục bộ cho kiosk cùng máy: ``GET /health``, ``POST /print`` (chỉ nghe 127.0.0.1)."""

import base64
import binascii
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from tracecore_agent import __version__

log = logging.getLogger("tracecore_agent")
MAX_BODY = 1024 * 1024
MAX_PRINTER_NAME = 140


def make_server(cfg, queue):
	allowed_origin = "{0.scheme}://{0.netloc}".format(urlparse(cfg.server_url))

	class Handler(BaseHTTPRequestHandler):
		server_version = f"tracecore-agent/{__version__}"

		def log_message(self, fmt, *args):
			log.debug("%s - %s", self.address_string(), fmt % args)

		def _send(self, status, payload):
			body = json.dumps(payload).encode("utf-8")
			self.send_response(status)
			self.send_header("Content-Type", "application/json")
			self.send_header("Content-Length", str(len(body)))
			# Kiosk (trang trên server) gọi agent localhost → CORS chỉ cho đúng origin server
			if self.headers.get("Origin") == allowed_origin:
				self.send_header("Access-Control-Allow-Origin", allowed_origin)
				self.send_header("Access-Control-Allow-Headers", "Content-Type")
			self.end_headers()
			self.wfile.write(body)

		def _host_ok(self):
			# chống DNS rebinding: chỉ nhận Host là loopback đúng cổng đang nghe
			port = self.server.server_address[1]
			host = (self.headers.get("Host") or "").lower()
			return host in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

		def _origin_ok(self):
			# CLI/curl không gửi Origin; trình duyệt luôn gửi → chỉ chấp nhận đúng origin server TraceCore
			origin = self.headers.get("Origin")
			return origin is None or origin == allowed_origin

		def do_OPTIONS(self):
			ok = self._host_ok() and self.headers.get("Origin") == allowed_origin
			self._send(204 if ok else 403, {})

		def do_GET(self):
			if not self._host_ok():
				return self._send(403, {"error": "forbidden host"})
			if self.path != "/health":
				return self._send(404, {"error": "not found"})
			self._send(
				200,
				{
					"status": "ok",
					"version": __version__,
					"station": cfg.station,
					"queue_depth": queue.depth(),
					"printer_mode": cfg.printer_mode,
				},
			)

		def do_POST(self):
			if not (self._host_ok() and self._origin_ok()):
				return self._send(403, {"error": "forbidden origin"})
			if self.path != "/print":
				return self._send(404, {"error": "not found"})
			# bắt buộc JSON: trình duyệt phải preflight (OPTIONS) nên trang lạ không gửi "no-cors" được
			if not (self.headers.get("Content-Type") or "").startswith("application/json"):
				return self._send(415, {"error": "Content-Type must be application/json"})
			length = int(self.headers.get("Content-Length") or 0)
			if not 0 < length <= MAX_BODY:
				return self._send(400, {"error": "invalid body size"})
			try:
				data = json.loads(self.rfile.read(length))
				zpl = data["zpl"]
				preview = data.get("preview_png_b64")
				preview_png = base64.b64decode(preview, validate=True) if preview else None
			except (ValueError, KeyError, TypeError, binascii.Error):
				return self._send(400, {"error": "invalid JSON payload"})
			if not (isinstance(zpl, str) and zpl.lstrip().startswith("^XA") and zpl.rstrip().endswith("^XZ")):
				return self._send(400, {"error": "zpl must be a ^XA...^XZ label"})
			printer = data.get("printer")
			if printer is not None and not (
				isinstance(printer, str)
				and 0 < len(printer) <= MAX_PRINTER_NAME
				and printer.isprintable()
				and printer.strip()
			):
				return self._send(400, {"error": "printer must be a printable name up to 140 chars"})
			job_id = queue.enqueue(
				zpl, preview_png=preview_png, print_job=data.get("print_job"), printer=printer
			)
			self._send(202, {"job_id": job_id})

	return ThreadingHTTPServer((cfg.listen_host, cfg.listen_port), Handler)
