"""Xử lý hàng đợi in: in ra máy in hoặc file, báo kết quả về server (Print Job)."""

import logging

from tracecore_agent import printer

log = logging.getLogger("tracecore_agent")


class UnknownPrinter(OSError):
	"""Tên Printer không có trong cấu hình trạm (D11: agent chỉ in tới máy in của trạm)."""


def _target(cfg, job, directory):
	"""(host, port) đích của lệnh in; host rỗng = chế độ file. Lệnh không có tên → máy in trong INI."""
	if not job.printer:
		return cfg.printer_host, cfg.printer_port
	target = directory.resolve(job.printer) if directory else None
	if target is None:
		raise UnknownPrinter(f"Unknown printer {job.printer}")
	return target


def process_one(cfg, queue, client=None, directory=None):
	"""In lệnh kế tiếp trong hàng đợi; trả Job đã xử lý (hoặc None nếu hàng đợi rỗng)."""
	job = queue.claim_next()
	if not job:
		return None
	mode = "Printer" if job.printer or cfg.printer_mode == "printer" else "File"
	try:
		host, port = _target(cfg, job, directory)
		mode = "Printer" if host else "File"
		if host:
			printer.send_tcp(host, port, job.zpl)
			output_ref = f"{host}:{port}"
		else:
			output_ref = printer.write_file(cfg.output_dir, job.id, job.zpl, job.preview_png)
	except OSError as error:
		status = queue.mark_failed(job.id, error)
		log.warning("print job %s failed (%s): %s", job.id, status, error)
		if status == "failed" and client and job.print_job:
			_ack(client, job.print_job, "Failed", mode, error=str(error))
		return queue.get(job.id)

	queue.mark_done(job.id, output_ref)
	if client and job.print_job:
		_ack(client, job.print_job, "Printed", mode, output_ref=output_ref)
	return queue.get(job.id)


def _ack(client, print_job, status, mode, output_ref=None, error=None):
	try:
		client.ack(print_job, status, mode, output_ref=output_ref, error=error)
	except Exception as exc:  # server lỗi không được chặn việc in (NFR-AVAIL-04)
		log.warning("could not report print job %s: %s", print_job, exc)
