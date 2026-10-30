"""Chạy hook mở rộng giữa các phân hệ (ADR-001: module nghiệp vụ gọi nhau qua hook, không import chéo).

M2 gọi ``extension.run("tracecore_pack_context", ctx)``; M1/M8 khai báo hàm xử lý trong ``hooks.py``
(``tracecore_pack_context = ["tracecore.instrument.bom.pack_context", …]``).
"""

import frappe


def run(hook, *args, **kwargs):
	"""Gọi lần lượt từng hàm đã khai báo cho ``hook`` (theo thứ tự trong ``hooks.py``).

	Trả danh sách kết quả của các hàm, bỏ kết quả ``None`` (``0``/``False``/``{}`` vẫn được giữ).
	Ngoại lệ của hàm hook không bị nuốt: nơi gọi quyết định xử lý hay hoàn tác.
	"""
	paths = frappe.get_hooks(hook)
	if isinstance(paths, str):
		paths = [paths]
	results = []
	for path in paths:
		result = frappe.get_attr(path)(*args, **kwargs)
		if result is not None:
			results.append(result)
	return results
