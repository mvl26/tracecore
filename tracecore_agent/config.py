"""Đọc cấu hình agent (INI, quyền 600) — mẫu ở agent.ini.example."""

import configparser
import os
from dataclasses import dataclass

DEFAULT_CONFIG = "~/.tracecore-agent/agent.ini"


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

	@property
	def printer_mode(self):
		"""``printer`` khi có địa chỉ máy in, ngược lại ``file`` (ghi .zpl + ảnh xem trước)."""
		return "printer" if self.printer_host else "file"


def load(path=DEFAULT_CONFIG):
	path = os.path.expanduser(str(path))
	parser = configparser.ConfigParser()
	if not parser.read(path, encoding="utf-8"):
		raise FileNotFoundError(f"Agent config not found: {path}")
	agent = parser["agent"] if parser.has_section("agent") else {}
	printer = parser["printer"] if parser.has_section("printer") else {}
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
	)
