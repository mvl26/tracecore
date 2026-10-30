import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

PNG = b"\x89PNG\r\n\x1a\nfake-preview"
ZPL = "^XA^CI28^FO30,40^BXN,6,200,0,0,1,_,1^FD_180049520000TEST1^FS^XZ"


class StubFrappe:
	"""Server Frappe giả: ghi lại request RPC và trả response cố định."""

	def __init__(self):
		self.requests = []
		self.fail_status = None
		self.printers = []
		# FEAT-024: mã HTTP trả cho từng cycle_ref của ingest_machine_data (thiếu = 200)
		self.ingest_status = {}
		self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
		self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
		threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

	def methods(self):
		return [r["method"] for r in self.requests]

	def last(self, method):
		return [r for r in self.requests if r["method"] == method][-1]

	def _handler(self):
		stub = self

		class Handler(BaseHTTPRequestHandler):
			def log_message(self, *args):
				pass

			def do_POST(self):
				body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
				method = self.path.rsplit("/", 1)[-1]
				# header HTTP không phân biệt hoa thường (urllib tự đổi kiểu chữ)
				headers = {key.lower(): value for key, value in self.headers.items()}
				stub.requests.append({"method": method, "headers": headers, "body": body})
				if stub.fail_status:
					self.send_response(stub.fail_status)
					self.end_headers()
					self.wfile.write(b'{"exc_type": "PermissionError"}')
					return
				if method.endswith("ingest_machine_data"):
					ref = (body.get("cycle") or {}).get("cycle_ref")
					status = stub.ingest_status.get(ref, 200)
					ok = status == 200
					message = (
						{"ok": ok, "name": "ME-261026-01"} if ok else {"ok": False, "error": {"code": "X"}}
					)
					payload = json.dumps({"message": message}).encode()
					self.send_response(status)
					self.send_header("Content-Type", "application/json")
					self.send_header("Content-Length", str(len(payload)))
					self.end_headers()
					self.wfile.write(payload)
					return
				if method.endswith("test_label"):
					message = {
						"print_job": "42",
						"giai": "9520000TEST1",
						"zpl": ZPL,
						"preview_png_b64": base64.b64encode(PNG).decode(),
					}
				elif method.endswith("station.config"):
					# như tracecore.v1.station.config: `station` là dict thông tin trạm
					message = {
						"station": {
							"name": body.get("station"),
							"label": "T4 Packing",
							"zone": "ZONE-CLEAN",
							"zone_type": "Clean",
							"step": "T4",
							"is_active": 1,
						},
						"printers": stub.printers,
						"peripherals": [],
					}
				elif method.endswith("ack"):
					message = {"ok": True, "status": body.get("status")}
				else:
					message = {"ok": True, "server_time": "2026-10-19T09:00:00+07:00"}
				payload = json.dumps({"message": message}).encode()
				self.send_response(200)
				self.send_header("Content-Type", "application/json")
				self.send_header("Content-Length", str(len(payload)))
				self.end_headers()
				self.wfile.write(payload)

		return Handler

	def close(self):
		self.httpd.shutdown()
		self.httpd.server_close()


class FakePrinter:
	"""Máy in ZPL giả trên TCP: nhận và lưu toàn bộ byte của mỗi kết nối."""

	def __init__(self):
		self.received = []
		self.sock = socket.socket()
		self.sock.bind(("127.0.0.1", 0))
		self.sock.listen()
		self.port = self.sock.getsockname()[1]
		threading.Thread(target=self._serve, daemon=True).start()

	def _serve(self):
		while True:
			try:
				conn, _ = self.sock.accept()
			except OSError:
				return
			chunks = []
			with conn:
				while data := conn.recv(4096):
					chunks.append(data)
			self.received.append(b"".join(chunks))

	def close(self):
		self.sock.close()


@pytest.fixture
def stub():
	server = StubFrappe()
	yield server
	server.close()


@pytest.fixture
def printer():
	fake = FakePrinter()
	yield fake
	fake.close()


def write_ini(path, server_url, tmp_path, printer_host="", printer_port=9100):
	path.write_text(
		"[server]\n"
		f"url = {server_url}\napi_key = key123\napi_secret = secret456\n"
		"[station]\nid = TR-004\n"
		f"[printer]\nhost = {printer_host}\nport = {printer_port}\n"
		"[agent]\nlisten_host = 127.0.0.1\nlisten_port = 0\n"
		f"output_dir = {tmp_path / 'labels'}\ndb_path = {tmp_path / 'queue.sqlite3'}\n",
		encoding="utf-8",
	)
	return path


@pytest.fixture
def ini(tmp_path, stub):
	return write_ini(tmp_path / "agent.ini", stub.url, tmp_path)


@pytest.fixture
def cfg(ini):
	from tracecore_agent import config

	return config.load(ini)
