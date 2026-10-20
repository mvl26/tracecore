"""Tiện ích dùng chung cho test TraceCore."""

from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase

TEST_SAVEPOINT = "tc_isolated_test"


class IsolatedTestCase(FrappeTestCase):
	"""FrappeTestCase hoàn tác dữ liệu sau MỖI test (savepoint), không chỉ sau cả class.

	Dùng khi test sửa dữ liệu dùng chung với test khác trong class (mẫu nhãn mẫu, máy in của trạm…).
	"""

	def setUp(self):
		super().setUp()
		frappe.db.savepoint(TEST_SAVEPOINT)
		self.addCleanup(frappe.db.rollback, save_point=TEST_SAVEPOINT)


def bru(*ids):
	"""Gắn marker BRU cho test (kiểm bằng scripts/check_bru_coverage.py)."""

	def decorator(fn):
		fn.__bru__ = tuple(ids)
		return fn

	return decorator


class _FakeRequest:
	def __init__(self, headers):
		self.headers = headers


@contextmanager
def request_headers(headers):
	"""Giả lập frappe.local.request với các header cho trước (X-Idempotency-Key…)."""
	previous = getattr(frappe.local, "request", None)
	frappe.local.request = _FakeRequest(dict(headers))
	try:
		yield
	finally:
		if previous is None:
			del frappe.local.request
		else:
			frappe.local.request = previous
