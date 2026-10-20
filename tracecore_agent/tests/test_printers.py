import os
import time

from tracecore_agent import cli
from tracecore_agent.client import ServerClient
from tracecore_agent.jobqueue import MAX_ATTEMPTS, PrintQueue
from tracecore_agent.printers import PrinterDirectory
from tracecore_agent.service import process_one

from .conftest import ZPL, write_ini


def _printer(name, host="127.0.0.1", port=9100):
	return {"name": name, "host": host, "port": port, "language": "ZPL", "label_type": "", "method": ""}


class CountingDirectory:
	def __init__(self, mapping):
		self.mapping = mapping
		self.refreshes = 0

	def refresh(self):
		self.refreshes += 1

	def resolve(self, name):
		if name in self.mapping:
			return self.mapping[name]
		self.refresh()
		return None


def test_directory_resolves_after_refresh(cfg, stub):
	stub.printers = [_printer("PRN-001", "10.0.0.5", 9101), _printer("PRN-F", "")]
	directory = PrinterDirectory(cfg, ServerClient(cfg))
	directory.refresh()
	assert directory.resolve("PRN-001") == ("10.0.0.5", 9101)
	assert directory.resolve("PRN-F") == ("", 9100)
	assert directory.resolve(None) == (cfg.printer_host, cfg.printer_port)


def test_directory_unknown_refreshes_once_then_none(cfg, stub):
	directory = PrinterDirectory(cfg, ServerClient(cfg))
	assert directory.resolve("PRN-404") is None
	assert stub.methods().count("tracecore.v1.station.config") == 1
	stub.printers = [_printer("PRN-404", "10.0.0.9")]
	assert directory.resolve("PRN-404") == ("10.0.0.9", 9100)


def test_directory_refresh_failure_keeps_cache(cfg, stub):
	stub.printers = [_printer("PRN-001", "10.0.0.5")]
	directory = PrinterDirectory(cfg, ServerClient(cfg))
	directory.refresh()
	stub.fail_status = 500
	directory.refresh()
	assert directory.resolve("PRN-001") == ("10.0.0.5", 9100)


def test_process_routes_to_named_printer(cfg, stub, printer):
	queue = PrintQueue(cfg.db_path)
	queue.enqueue(ZPL, print_job="42", printer="PRN-001")
	directory = CountingDirectory({"PRN-001": ("127.0.0.1", printer.port)})
	job = process_one(cfg, queue, ServerClient(cfg), directory)
	assert job.status == "done"
	for _ in range(50):
		if printer.received:
			break
		time.sleep(0.02)
	assert printer.received == [ZPL.encode()]
	ack = stub.last("tracecore.v1.print.ack")["body"]
	assert (ack["status"], ack["output_mode"]) == ("Printed", "Printer")
	assert ack["output_ref"] == f"127.0.0.1:{printer.port}"


def test_named_printer_without_host_writes_file(cfg, stub):
	queue = PrintQueue(cfg.db_path)
	queue.enqueue(ZPL, print_job="42", printer="PRN-F")
	job = process_one(cfg, queue, ServerClient(cfg), CountingDirectory({"PRN-F": ("", 9100)}))
	assert job.status == "done"
	assert job.output_ref.endswith(".zpl") and os.path.exists(job.output_ref)
	assert stub.last("tracecore.v1.print.ack")["body"]["output_mode"] == "File"


def test_unknown_printer_fails_after_refresh(cfg, stub):
	queue = PrintQueue(cfg.db_path)
	job_id = queue.enqueue(ZPL, print_job="42", printer="PRN-404")
	directory = CountingDirectory({})
	client = ServerClient(cfg)
	process_one(cfg, queue, client, directory)
	assert directory.refreshes == 1
	assert queue.get(job_id).status == "pending"
	for _ in range(MAX_ATTEMPTS - 1):
		process_one(cfg, queue, client, directory)
	assert queue.get(job_id).status == "failed"
	acks = [r["body"] for r in stub.requests if r["method"].endswith("ack")]
	assert [a["status"] for a in acks] == ["Failed"]
	assert "Unknown printer PRN-404" in acks[0]["error"]


def test_hello_still_uses_ini_printer(stub, printer, tmp_path):
	ini = write_ini(
		tmp_path / "a.ini", stub.url, tmp_path, printer_host="127.0.0.1", printer_port=printer.port
	)
	assert cli.main(["--config", str(ini), "hello"]) == 0
	assert "tracecore.v1.station.config" not in stub.methods()


def test_config_command_prints_station_config(ini, stub, capsys):
	stub.printers = [_printer("PRN-001", "10.0.0.5")]
	assert cli.main(["--config", str(ini), "config"]) == 0
	assert '"PRN-001"' in capsys.readouterr().out


def test_config_command_failure_exits_1(ini, stub, capsys):
	stub.fail_status = 403
	assert cli.main(["--config", str(ini), "config"]) == 1
	assert "403" in capsys.readouterr().err
