import os
import time

from tracecore_agent import cli
from tracecore_agent.client import ServerClient
from tracecore_agent.jobqueue import MAX_ATTEMPTS, PrintQueue
from tracecore_agent.service import process_one

from .conftest import PNG, ZPL, write_ini


def test_hello_file_mode_end_to_end(ini, stub, tmp_path, capsys):
	assert cli.main(["--config", str(ini), "hello"]) == 0
	assert stub.methods() == [
		"tracecore.v1.agent.heartbeat",
		"tracecore.v1.print.test_label",
		"tracecore.v1.print.ack",
	]
	ack = stub.last("tracecore.v1.print.ack")["body"]
	assert (ack["print_job"], ack["status"], ack["output_mode"]) == ("42", "Printed", "File")
	assert ack["output_ref"].endswith(".zpl")
	assert open(ack["output_ref"], encoding="utf-8").read() == ZPL
	with open(ack["output_ref"][:-4] + ".png", "rb") as handle:
		assert handle.read() == PNG
	assert "Print Job 42: Printed" in capsys.readouterr().out


def test_hello_printer_mode(stub, printer, tmp_path):
	ini = write_ini(tmp_path / "agent.ini", stub.url, tmp_path, printer_host="127.0.0.1", printer_port=printer.port)
	assert cli.main(["--config", str(ini), "hello"]) == 0
	for _ in range(50):
		if printer.received:
			break
		time.sleep(0.02)
	assert printer.received == [ZPL.encode()]
	ack = stub.last("tracecore.v1.print.ack")["body"]
	assert (ack["status"], ack["output_mode"]) == ("Printed", "Printer")


def test_unreachable_printer_retries_then_acks_failed(cfg, stub):
	cfg.printer_host, cfg.printer_port = "127.0.0.1", 1
	queue = PrintQueue(cfg.db_path)
	job_id = queue.enqueue(ZPL, print_job="42")
	client = ServerClient(cfg)
	for _ in range(MAX_ATTEMPTS):
		process_one(cfg, queue, client)
	assert queue.get(job_id).status == "failed"
	acks = [r["body"] for r in stub.requests if r["method"].endswith("ack")]
	assert [(a["status"], a["output_mode"]) for a in acks] == [("Failed", "Printer")]


def test_health_command(ini, capsys):
	assert cli.main(["--config", str(ini), "health"]) == 0
	out = capsys.readouterr().out
	assert '"station": "TR-004"' in out


def test_missing_config_fails_cleanly(tmp_path, capsys):
	assert cli.main(["--config", os.path.join(tmp_path, "missing.ini"), "health"]) == 2
	assert "missing.ini" in capsys.readouterr().err
