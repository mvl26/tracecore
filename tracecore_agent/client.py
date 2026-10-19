"""Gọi RPC tracecore.v1.* của server bằng API key (ADR-006) — mỗi lệnh một X-Idempotency-Key."""

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime

from tracecore_agent import __version__


class ServerError(Exception):
	def __init__(self, status, body):
		super().__init__(f"HTTP {status}: {body[:200]}")
		self.status = status
		self.body = body


def client_ts():
	return datetime.now().astimezone().isoformat(timespec="seconds")


class ServerClient:
	def __init__(self, cfg, timeout=10.0):
		if urllib.parse.urlparse(cfg.server_url).scheme not in ("http", "https"):
			raise ValueError(f"Server URL must be http(s): {cfg.server_url}")
		self.cfg = cfg
		self.timeout = timeout

	def call(self, method, **data):
		body = json.dumps({**data, "client_ts": client_ts()}).encode("utf-8")
		request = urllib.request.Request(
			f"{self.cfg.server_url}/api/method/{method}",
			data=body,
			method="POST",
			headers={
				"Accept": "application/json",
				"Content-Type": "application/json",
				"Authorization": f"token {self.cfg.api_key}:{self.cfg.api_secret}",
				"X-Idempotency-Key": str(uuid.uuid4()),
				"X-TC-Station": self.cfg.station,
			},
		)
		try:
			# URL đã kiểm scheme http(s) trong __init__
			with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
				return json.loads(response.read() or b"{}").get("message")
		except urllib.error.HTTPError as error:
			raise ServerError(error.code, error.read().decode("utf-8", "replace")) from error

	def heartbeat(self, queue_depth, printer=None):
		return self.call(
			"tracecore.v1.agent.heartbeat",
			station=self.cfg.station,
			agent_version=__version__,
			queue_depth=queue_depth,
			printer=printer or self.cfg.printer_mode,
		)

	def test_label(self):
		return self.call("tracecore.v1.print.test_label", station=self.cfg.station)

	def ack(self, print_job, status, output_mode, output_ref=None, error=None):
		return self.call(
			"tracecore.v1.print.ack",
			print_job=print_job,
			status=status,
			output_mode=output_mode,
			output_ref=output_ref,
			error=error,
		)
