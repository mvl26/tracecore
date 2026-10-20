"""Dòng lệnh agent: ``python3 -m tracecore_agent [--config PATH] serve|health|hello|config``."""

import argparse
import base64
import json
import logging
import sys
import threading
import time

from tracecore_agent import __version__, config
from tracecore_agent.client import ServerClient
from tracecore_agent.jobqueue import PrintQueue
from tracecore_agent.printers import PrinterDirectory
from tracecore_agent.server import make_server
from tracecore_agent.service import process_one

log = logging.getLogger("tracecore_agent")
HEARTBEAT_SECONDS = 30
POLL_SECONDS = 1.0
CONFIG_REFRESH_BEATS = 10


def cmd_health(cfg, queue):
	print(
		json.dumps(
			{
				"version": __version__,
				"station": cfg.station,
				"server": cfg.server_url,
				"printer_mode": cfg.printer_mode,
				"queue_depth": queue.depth(),
			},
			indent=1,
		)
	)
	return 0


def cmd_hello(cfg, queue):
	"""In một nhãn thử: heartbeat → server tạo Print Job → in/ghi file → báo kết quả."""
	client = ServerClient(cfg)
	client.heartbeat(queue.depth())
	label = client.test_label()
	preview = base64.b64decode(label["preview_png_b64"]) if label.get("preview_png_b64") else None
	queue.enqueue(label["zpl"], preview_png=preview, print_job=label["print_job"])
	job = process_one(cfg, queue, client)
	status = "Printed" if job and job.status == "done" else "Failed"
	mode = "Printer" if cfg.printer_mode == "printer" else "File"
	print(f"Print Job {label['print_job']}: {status} ({mode}) {job.output_ref or job.error}")
	return 0 if status == "Printed" else 1


def cmd_config(cfg, queue):
	"""In cấu hình trạm (máy in) lấy từ server."""
	try:
		station = ServerClient(cfg).station_config()
	except Exception as error:  # ServerError, mất mạng, JSON hỏng
		print(f"tracecore_agent: cannot read station config: {error}", file=sys.stderr)
		return 1
	print(json.dumps(station, indent=1, ensure_ascii=False))
	return 0


def cmd_serve(cfg, queue):
	server = make_server(cfg, queue)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	log.info("agent %s listening on %s:%s", __version__, *server.server_address)
	client = ServerClient(cfg)
	directory = PrinterDirectory(cfg, client)
	directory.refresh()
	beats = 0
	next_heartbeat = 0.0
	try:
		while True:
			if time.monotonic() >= next_heartbeat:
				try:
					client.heartbeat(queue.depth())
				except Exception as error:  # mất mạng không được dừng agent
					log.warning("heartbeat failed: %s", error)
				next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
				beats += 1
				if beats % CONFIG_REFRESH_BEATS == 0:
					directory.refresh()
			if not process_one(cfg, queue, client, directory):
				time.sleep(POLL_SECONDS)
	except KeyboardInterrupt:
		return 0
	finally:
		server.shutdown()


COMMANDS = {"config": cmd_config, "health": cmd_health, "hello": cmd_hello, "serve": cmd_serve}


def main(argv=None):
	parser = argparse.ArgumentParser(prog="tracecore_agent", description="TraceCore Station Agent")
	parser.add_argument("--config", default=config.DEFAULT_CONFIG)
	parser.add_argument("command", choices=sorted(COMMANDS))
	args = parser.parse_args(argv)
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
	try:
		cfg = config.load(args.config)
	except (FileNotFoundError, KeyError) as error:
		print(f"tracecore_agent: cannot load config {args.config}: {error}", file=sys.stderr)
		return 2
	return COMMANDS[args.command](cfg, PrintQueue(cfg.db_path))
