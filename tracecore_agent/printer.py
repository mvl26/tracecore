"""Đầu ra lệnh in: gửi ZPL thô qua TCP 9100 hoặc ghi file khi trạm chưa có máy in."""

import os
import socket


def send_tcp(host, port, zpl, timeout=5.0):
	with socket.create_connection((host, int(port)), timeout=timeout) as conn:
		conn.sendall(zpl.encode("utf-8"))


def write_file(output_dir, job_id, zpl, preview_png):
	"""Ghi ``<job_id>.zpl`` (+ ``<job_id>.png`` nếu có ảnh xem trước); trả đường dẫn file .zpl."""
	output_dir = str(output_dir)
	os.makedirs(output_dir, exist_ok=True)
	zpl_path = os.path.join(output_dir, f"{job_id}.zpl")
	with open(zpl_path, "w", encoding="utf-8") as handle:
		handle.write(zpl)
	if preview_png:
		with open(os.path.join(output_dir, f"{job_id}.png"), "wb") as handle:
			handle.write(preview_png)
	return zpl_path
