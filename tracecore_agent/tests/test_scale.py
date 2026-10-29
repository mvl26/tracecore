"""Cân điện tử RS-232/USB qua agent: ``GET /scale`` (FEAT-033, FR-M3-01.2, EI-HW-004, NFR-AVAIL-04)."""

import threading

import pytest

from tracecore_agent import config, scale
from tracecore_agent.jobqueue import PrintQueue
from tracecore_agent.server import make_server
from tracecore_agent.tests.test_server import request


class FakeConnection:
	"""Cổng nối tiếp giả: trả lần lượt các dòng đã cho rồi để trống (hết giờ)."""

	def __init__(self, lines):
		self.lines = [line if isinstance(line, bytes) else line.encode() for line in lines]
		self.written = []
		self.flushed = False

	def __enter__(self):
		return self

	def __exit__(self, *exc):
		return False

	def reset_input_buffer(self):
		self.flushed = True

	def write(self, data):
		self.written.append(data)

	def readline(self):
		return self.lines.pop(0) if self.lines else b""


def opener_for(lines, seen=None):
	def opener(**kwargs):
		if seen is not None:
			seen.update(kwargs)
		return FakeConnection(lines)

	return opener


@pytest.mark.parametrize(
	("line", "kg"),
	[
		("ST,GS,   12.34 kg", 12.34),
		("  12,5 kg\r\n", 12.5),
		("+0005.20 kg", 5.2),
		("12340 g", 12.34),
		("12.5", 12.5),  # không có đơn vị: lấy đơn vị mặc định (kg)
		("N    0.000 kg", 0.0),
	],
)
def test_parse_reads_kg_and_converts_grams(line, kg):
	assert scale.parse(line) == pytest.approx(kg)


@pytest.mark.parametrize("line", ["", "ERR", "ST,GS", "kg", "   \r\n"])
def test_parse_ignores_lines_without_a_number(line):
	assert scale.parse(line) is None


def test_parse_uses_the_configured_pattern():
	assert scale.parse("W=7.25;", pattern=r"W=(\d+\.\d+);") == 7.25


def test_read_weight_takes_the_first_reading_after_flushing():
	connection = FakeConnection(["", "ERR", "ST,GS,  4.50 kg", "ST,GS,  9.99 kg"])
	cfg = type(
		"Cfg",
		(),
		{
			"scale_port": "COM3",
			"scale_baudrate": 9600,
			"scale_timeout": 2.0,
			"scale_pattern": "",
			"scale_request": "",
		},
	)()
	assert scale.read_weight(cfg, opener=lambda **kwargs: connection) == 4.5
	assert connection.flushed


def test_read_weight_sends_the_request_command_when_configured():
	connection = FakeConnection(["1.00 kg"])
	cfg = type(
		"Cfg",
		(),
		{
			"scale_port": "COM3",
			"scale_baudrate": 9600,
			"scale_timeout": 2.0,
			"scale_pattern": "",
			"scale_request": "P\\r\\n",
		},
	)()
	scale.read_weight(cfg, opener=lambda **kwargs: connection)
	assert connection.written == [b"P\r\n"]


def test_read_weight_passes_port_and_baudrate_to_the_opener():
	seen = {}
	cfg = type(
		"Cfg",
		(),
		{
			"scale_port": "/dev/ttyUSB0",
			"scale_baudrate": 4800,
			"scale_timeout": 1.5,
			"scale_pattern": "",
			"scale_request": "",
		},
	)()
	scale.read_weight(cfg, opener=opener_for(["2 kg"], seen))
	assert seen["port"] == "/dev/ttyUSB0"
	assert seen["baudrate"] == 4800


def test_read_weight_without_a_port_is_not_configured():
	cfg = type(
		"Cfg",
		(),
		{
			"scale_port": "",
			"scale_baudrate": 9600,
			"scale_timeout": 1.0,
			"scale_pattern": "",
			"scale_request": "",
		},
	)()
	with pytest.raises(scale.ScaleError, match="not configured"):
		scale.read_weight(cfg, opener=opener_for(["1 kg"]))


def test_read_weight_without_any_reading_times_out():
	cfg = type(
		"Cfg",
		(),
		{
			"scale_port": "COM3",
			"scale_baudrate": 9600,
			"scale_timeout": 0.05,
			"scale_pattern": "",
			"scale_request": "",
		},
	)()
	with pytest.raises(scale.ScaleError, match="no reading"):
		scale.read_weight(cfg, opener=opener_for(["", "ERR"]))


def test_read_weight_reports_a_port_that_cannot_be_opened():
	def broken(**kwargs):
		raise OSError("port busy")

	cfg = type(
		"Cfg",
		(),
		{
			"scale_port": "COM3",
			"scale_baudrate": 9600,
			"scale_timeout": 0.05,
			"scale_pattern": "",
			"scale_request": "",
		},
	)()
	with pytest.raises(scale.ScaleError, match="port busy"):
		scale.read_weight(cfg, opener=broken)


def test_config_reads_the_scale_section(tmp_path, stub):
	from tracecore_agent.tests.conftest import write_ini

	path = write_ini(tmp_path / "agent.ini", stub.url, tmp_path)
	path.write_text(
		path.read_text(encoding="utf-8")
		+ "[scale]\nport = COM5\nbaudrate = 4800\ntimeout = 1.5\npattern = (\\d+)\nrequest = P\n",
		encoding="utf-8",
	)
	cfg = config.load(path)
	assert (cfg.scale_port, cfg.scale_baudrate, cfg.scale_timeout) == ("COM5", 4800, 1.5)
	assert (cfg.scale_pattern, cfg.scale_request) == ("(\\d+)", "P")


def test_config_without_a_scale_section_has_no_port(cfg):
	assert cfg.scale_port == ""
	assert cfg.scale_baudrate == 9600


@pytest.fixture
def scaled_agent(cfg, monkeypatch):
	queue = PrintQueue(cfg.db_path)
	server = make_server(cfg, queue)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f"http://127.0.0.1:{server.server_address[1]}", cfg, monkeypatch
	server.shutdown()
	server.server_close()


def test_scale_endpoint_returns_kg(scaled_agent):
	base, cfg, monkeypatch = scaled_agent
	cfg.scale_port = "COM3"
	monkeypatch.setattr(scale, "read_weight", lambda cfg: 7.25)
	status, body, headers = request(f"{base}/scale", headers={"Origin": cfg.server_url})
	assert (status, body) == (200, {"kg": 7.25, "unit": "kg"})
	assert headers.get("Access-Control-Allow-Origin") == cfg.server_url


def test_scale_endpoint_answers_503_when_the_scale_does_not_respond(scaled_agent):
	base, cfg, monkeypatch = scaled_agent

	def fail(cfg):
		raise scale.ScaleError("no reading")

	monkeypatch.setattr(scale, "read_weight", fail)
	status, body, _ = request(f"{base}/scale")
	assert status == 503
	assert body["error"] == "no reading"


def test_scale_endpoint_rejects_a_foreign_origin_and_host(scaled_agent):
	base, cfg, monkeypatch = scaled_agent
	monkeypatch.setattr(scale, "read_weight", lambda cfg: 1.0)
	assert request(f"{base}/scale", headers={"Origin": "http://evil.example"})[0] == 403
	port = base.rsplit(":", 1)[1]
	assert request(f"{base}/scale", headers={"Host": f"evil.example:{port}"})[0] == 403
