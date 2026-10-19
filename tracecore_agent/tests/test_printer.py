import time

import pytest

from tracecore_agent import printer as printer_mod


def test_send_tcp_delivers_bytes(printer):
	printer_mod.send_tcp("127.0.0.1", printer.port, "^XA^FDtest^FS^XZ")
	for _ in range(50):
		if printer.received:
			break
		time.sleep(0.02)
	assert printer.received == [b"^XA^FDtest^FS^XZ"]


def test_send_tcp_unreachable_raises():
	with pytest.raises(OSError):
		printer_mod.send_tcp("127.0.0.1", 1, "^XA^XZ", timeout=0.5)


def test_write_file_outputs_zpl_and_png(tmp_path):
	path = printer_mod.write_file(tmp_path / "out", "job1", "^XA^XZ", b"\x89PNG")
	assert path.endswith("job1.zpl")
	assert (tmp_path / "out" / "job1.zpl").read_text() == "^XA^XZ"
	assert (tmp_path / "out" / "job1.png").read_bytes() == b"\x89PNG"


def test_write_file_without_preview(tmp_path):
	printer_mod.write_file(tmp_path, "job2", "^XA^XZ", None)
	assert not (tmp_path / "job2.png").exists()
