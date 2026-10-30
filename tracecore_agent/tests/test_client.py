import re
from datetime import datetime

import pytest

from tracecore_agent.client import ServerClient, ServerError

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def test_client_sends_auth_and_idempotency_headers(cfg, stub):
	client = ServerClient(cfg)
	result = client.heartbeat(queue_depth=3)
	assert result["ok"] is True
	sent = stub.last("tracecore.v1.agent.heartbeat")
	assert sent["headers"]["authorization"] == "token key123:secret456"
	assert UUID.match(sent["headers"]["x-idempotency-key"])
	assert sent["headers"]["x-tc-station"] == "TR-004"
	assert sent["body"]["station"] == "TR-004"
	assert sent["body"]["queue_depth"] == 3
	assert datetime.fromisoformat(sent["body"]["client_ts"]).utcoffset() is not None


def test_each_call_gets_new_idempotency_key(cfg, stub):
	client = ServerClient(cfg)
	client.heartbeat(queue_depth=0)
	client.heartbeat(queue_depth=0)
	keys = {r["headers"]["x-idempotency-key"] for r in stub.requests}
	assert len(keys) == 2


def test_client_raises_on_http_error(cfg, stub):
	stub.fail_status = 403
	with pytest.raises(ServerError) as info:
		ServerClient(cfg).test_label()
	assert info.value.status == 403


def test_client_rejects_non_http_url(cfg):
	cfg.server_url = "file:///etc/passwd"
	with pytest.raises(ValueError):
		ServerClient(cfg)


def test_client_station_config(cfg, stub):
	stub.printers = [{"name": "PRN-001", "host": "10.0.0.5", "port": 9100}]
	result = ServerClient(cfg).station_config()
	assert result["printers"][0]["name"] == "PRN-001"
	sent = stub.last("tracecore.v1.station.config")
	assert sent["body"]["station"] == "TR-004"


def test_station_config_returns_station_dict_like_the_server(cfg, stub):
	"""`station.config` thật trả `station` là dict (name, zone, step…), kèm máy in và thiết bị ngoại vi."""
	config = ServerClient(cfg).station_config()
	assert config["station"]["name"] == "TR-004"
	assert config["station"]["is_active"] == 1
	assert config["printers"] == stub.printers
	assert config["peripherals"] == []
