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

		def do_OPTIONS(self):
			self._send(204 if self.headers.get("Origin") == allowed_origin else 403, {})

		def do_GET(self):
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
			if self.path != "/print":
				return self._send(404, {"error": "not found"})
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
			job_id = queue.enqueue(zpl, preview_png=preview_png, print_job=data.get("print_job"))
			self._send(202, {"job_id": job_id})

	return ThreadingHTTPServer((cfg.listen_host, cfg.listen_port), Handler)
