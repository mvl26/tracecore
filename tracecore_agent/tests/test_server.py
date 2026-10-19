import json
import threading
import urllib.error
import urllib.request

import pytest

from tracecore_agent.jobqueue import PrintQueue
from tracecore_agent.server import make_server


@pytest.fixture
def agent(cfg):
	queue = PrintQueue(cfg.db_path)
	server = make_server(cfg, queue)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f"http://127.0.0.1:{server.server_address[1]}", queue
	server.shutdown()
	server.server_close()


def request(url, data=None, method=None):
	body = json.dumps(data).encode() if data is not None else None
	req = urllib.request.Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
	try:
		with urllib.request.urlopen(req, timeout=5) as resp:
			return resp.status, json.loads(resp.read())
	except urllib.error.HTTPError as error:
		return error.code, json.loads(error.read() or b"{}")


def test_health_endpoint(agent):
	base, _ = agent
	status, body = request(f"{base}/health")
	assert status == 200
	assert body["status"] == "ok"
	assert body["station"] == "TR-004"
	assert body["queue_depth"] == 0
	assert body["printer_mode"] == "file"


def test_print_endpoint_enqueues(agent):
	base, queue = agent
	status, body = request(f"{base}/print", {"zpl": "^XA^FDx^FS^XZ", "print_job": "9"})
	assert status == 202
	assert body["job_id"]
	assert queue.depth() == 1
	assert queue.claim_next().print_job == "9"


def test_print_endpoint_rejects_bad_payload(agent):
	base, queue = agent
	assert request(f"{base}/print", {"zpl": "hello"})[0] == 400
	assert request(f"{base}/print", {"nothing": 1})[0] == 400
	assert queue.depth() == 0


def test_unknown_path_404(agent):
	base, _ = agent
	assert request(f"{base}/nope")[0] == 404
