"""TraceCore Settings: cờ tính năng toàn site (FEAT-014 A-06 I7).

Single trong module ``TraceCore``. Chỉ TC R10 và System Manager ghi (quyền DocType); đổi cờ ghi Audit Log qua
doc_events (``hooks.py``), không xóa được. Đọc cờ qua dịch vụ của phân hệ (vd ``instrument.catalog.giai_enabled``).
"""

import re
from datetime import time

import frappe
from frappe import _
from frappe.model.document import Document

from tracecore.core import error_codes

_TIME = re.compile(r"^(\d{1,2}):(\d{2})$")


def parse_times(text):
	"""Danh sách giờ ``HH:MM`` cách nhau bởi dấu phẩy → list `time` tăng dần, không trùng (FEAT-008, A-55 Q3)."""
	times = set()
	for part in (text or "").split(","):
		part = part.strip()
		if not part:
			continue
		match = _TIME.match(part)
		if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
			frappe.throw(_("{0} is not a time of day (HH:MM).").format(part))
		times.add(time(int(match.group(1)), int(match.group(2))))
	return sorted(times)


class TraceCoreSettings(Document):
	def validate(self):
		# giờ nhắc nhật ký môi trường: lưu dạng chuẩn "HH:MM, HH:MM"
		self.env_reminder_times = ", ".join(t.strftime("%H:%M") for t in parse_times(self.env_reminder_times))
		error_codes.validate_rules(self)
