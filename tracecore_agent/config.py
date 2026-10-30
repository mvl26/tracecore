"""Đọc cấu hình agent (INI, quyền 600) — mẫu ở agent.ini.example."""

import configparser
import os
from dataclasses import dataclass, field

DEFAULT_CONFIG = "~/.tracecore-agent/agent.ini"
MACHINE_PREFIX = "machine:"


@dataclass
class MachineConfig:
	"""Một máy kết nối được (FEAT-024): mục ``[machine:<TB-####>]``, ``driver`` + các khóa của driver."""

	equipment: str
	driver: str
	options: dict


@dataclass
class AgentConfig:
	server_url: str
	api_key: str
	api_secret: str
	station: str
	output_dir: str
	db_path: str
	printer_host: str = ""
	printer_port: int = 9100
	listen_host: str = "127.0.0.1"
	listen_port: int = 8765
	machines: list = field(default_factory=list)
	# cân điện tử (FEAT-033, mục [scale]); port rỗng = trạm không có cân, GET /scale trả 503
	scale_port: str = ""
	scale_baudrate: int = 9600
	scale_timeout: float = 2.0
	scale_pattern: str = ""
	scale_request: str = ""

	@property
	def printer_mode(self):
		"""``printer`` khi có địa chỉ máy in, ngược lại ``file`` (ghi .zpl + ảnh xem trước)."""
		return "printer" if self.printer_host else "file"


def _machines(parser):
	return [
		MachineConfig(
			equipment=section[len(MACHINE_PREFIX) :].strip(),
			driver=parser[section].get("driver", "csv_generic").strip(),
			options={key: value for key, value in parser[section].items() if key != "driver"},
		)
		for section in parser.sections()
		if section.startswith(MACHINE_PREFIX)
	]


def load(path=DEFAULT_CONFIG):
	path = os.path.expanduser(str(path))
	# không nội suy `%` (định dạng giờ `%d/%m/%Y` của driver CSV); giữ hoa thường của `param.<tên>` (FEAT-024)
	parser = configparser.ConfigParser(interpolation=None)
	parser.optionxform = str
	if not parser.read(path, encoding="utf-8"):
		raise FileNotFoundError(f"Agent config not found: {path}")
	agent = parser["agent"] if parser.has_section("agent") else {}
	printer = parser["printer"] if parser.has_section("printer") else {}
	scale = parser["scale"] if parser.has_section("scale") else {}
	return AgentConfig(
		server_url=parser["server"]["url"].rstrip("/"),
		api_key=parser["server"]["api_key"],
		api_secret=parser["server"]["api_secret"],
		station=parser["station"]["id"],
		printer_host=(printer.get("host") or "").strip(),
		printer_port=int(printer.get("port") or 9100),
		listen_host=agent.get("listen_host") or "127.0.0.1",
		listen_port=int(agent.get("listen_port") or 8765),
		output_dir=os.path.expanduser(agent.get("output_dir") or "~/.tracecore-agent/labels"),
		db_path=os.path.expanduser(agent.get("db_path") or "~/.tracecore-agent/queue.sqlite3"),
		machines=_machines(parser),
		scale_port=(scale.get("port") or "").strip(),
		scale_baudrate=int(scale.get("baudrate") or 9600),
		scale_timeout=float(scale.get("timeout") or 2.0),
		scale_pattern=(scale.get("pattern") or "").strip(),
		scale_request=(scale.get("request") or "").strip(),
	)
