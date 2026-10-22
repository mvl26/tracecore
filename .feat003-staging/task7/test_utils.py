"""Tiện ích dùng chung cho test TraceCore."""

from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase

TEST_SAVEPOINT = "tc_isolated_test"


def assert_permission_matrix(testcase, doctype):
	"""Compare effective permissions with the generated SEC matrix, including absent roles."""
	from tracecore.setup.permissions import build_custom_docperms

	rights = ("read", "write", "create", "report", "submit", "cancel", "amend", "delete")
	expected = {row["role"]: tuple(row.get(right, 0) for right in rights) for row in build_custom_docperms({doctype})}
	actual = {row.role: tuple(row.get(right, 0) for right in rights) for row in frappe.get_meta(doctype).permissions if row.permlevel == 0}
	testcase.assertEqual(actual, expected, doctype)


@contextmanager
def local_context(**values):
	"""Patch Werkzeug Local fields while preserving existing context on every exit."""
	missing = object()
	previous = {field: getattr(frappe.local, field, missing) for field in values}
	try:
		for field, value in values.items():
			setattr(frappe.local, field, value)
		yield
	finally:
		for field, value in previous.items():
			if value is missing:
				if hasattr(frappe.local, field):
					delattr(frappe.local, field)
			else:
				setattr(frappe.local, field, value)


@contextmanager
def fixture_r10():
	"""Explicit authority for Administrator-only test fixture creation, always restored.

	Other actors retain their actual permissions, including negative security tests.
	Installation bootstrap tests also retain their native production path.
	"""
	if not frappe.flags.in_test or frappe.session.user != "Administrator" or frappe.flags.in_install:
		yield
		return
	admin = frappe.get_doc("User", "Administrator")
	had_r10 = any(row.role == "TC R10" for row in admin.roles)
	try:
		if not had_r10:
			admin.add_roles("TC R10")
		yield
	finally:
		if not had_r10:
			admin.reload().remove_roles("TC R10")


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
