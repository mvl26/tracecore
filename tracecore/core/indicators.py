"""Sổ hàm tính chỉ số KSNK (FEAT-056, A-113, architecture §5.2 "M9 không import module nghiệp vụ").

Mỗi module M11-M17 khai báo trong ``hooks.py``::

    tracecore_ic_indicators = ["tracecore.compliance_audit.indicators.register"]

Hàm đăng ký trả ``{source_method: hàm hoặc đường dẫn hàm}``; hàm tính nhận ``(period, department)`` (``department``
rỗng = toàn viện) và trả ``(tử số, mẫu số, cỡ mẫu)``. ``IC Indicator.source_method`` chọn một khóa trong sổ này;
engine M9 (`admin_reports.indicator`) gọi hàm khi khóa kỳ.
"""

from collections.abc import Callable

import frappe

from tracecore.core import extension

HOOK = "tracecore_ic_indicators"


def registry() -> dict[str, Callable]:
	"""Gộp hàm tính của mọi module; một khóa chỉ được một module đăng ký."""
	merged: dict[str, Callable] = {}
	for result in extension.run(HOOK):
		for key, fn in (result or {}).items():
			if key in merged:
				raise ValueError(f"IC indicator method {key} is registered twice")
			merged[key] = frappe.get_attr(fn) if isinstance(fn, str) else fn
	return merged
