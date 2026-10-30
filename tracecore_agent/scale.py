"""Cân điện tử RS-232/USB: đọc một số cân qua cổng nối tiếp cho ``GET /scale`` (FEAT-033, FR-M3-01.2, EI-HW-004).

Cân gửi từng dòng văn bản (ví dụ ``ST,GS,  12.34 kg``). Agent xả bộ đệm, (tùy chọn) gửi lệnh yêu cầu rồi lấy dòng đầu
tiên có số; ``g`` đổi sang kg. Cổng không mở được hoặc hết giờ không có số → `ScaleError`, kiosk chuyển sang nhập tay
có xác nhận (NFR-AVAIL-04). `pyserial` chỉ nạp khi cần để máy không có cân không phải cài.
"""

import re
import time

DEFAULT_PATTERN = r"([-+]?\d+(?:[.,]\d+)?)\s*(kg|g)?"


class ScaleError(Exception):
	"""Cân không đọc được; thông báo ngắn trả về kiosk."""


def parse(line, pattern=None):
	"""kg từ một dòng cân, hoặc None nếu dòng không có số. Nhóm 1 là số, nhóm 2 (nếu có) là đơn vị ``kg`` hoặc ``g``."""
	if isinstance(line, bytes):
		line = line.decode("ascii", errors="ignore")
	match = re.search(pattern or DEFAULT_PATTERN, line)
	if not match:
		return None
	try:
		value = float(match.group(1).replace(",", "."))
	except ValueError:
		return None
	unit = match.group(2) if match.re.groups >= 2 else None
	return value / 1000 if unit == "g" else value


def _serial(**kwargs):
	try:
		import serial
	except ImportError:
		raise ScaleError("pyserial is not installed") from None
	return serial.Serial(**kwargs)


def read_weight(cfg, opener=None):
	"""Số kg hiện trên cân (làm tròn 3 lẻ). `opener(port=, baudrate=, timeout=)` thay cho `serial.Serial` khi test."""
	if not cfg.scale_port:
		raise ScaleError("scale is not configured")
	opener = opener or _serial
	try:
		connection = opener(port=cfg.scale_port, baudrate=cfg.scale_baudrate, timeout=cfg.scale_timeout)
		with connection:
			connection.reset_input_buffer()
			if cfg.scale_request:
				connection.write(cfg.scale_request.encode("ascii").decode("unicode_escape").encode("latin-1"))
			deadline = time.monotonic() + cfg.scale_timeout
			while time.monotonic() < deadline:
				kg = parse(connection.readline(), cfg.scale_pattern or None)
				if kg is not None:
					return round(kg, 3)
	except ScaleError:
		raise
	except Exception as error:
		raise ScaleError(str(error) or error.__class__.__name__) from None
	raise ScaleError("no reading from the scale")
