"""Tiện ích dùng chung cho test TraceCore."""

from contextlib import contextmanager

import frappe
from frappe.tests.utils import FrappeTestCase
from pymysql import OperationalError

TEST_SAVEPOINT = "tc_isolated_test"


def assert_permission_matrix(testcase, doctype):
	"""Compare effective permissions with the generated SEC matrix, including absent roles."""
	from tracecore.setup.permissions import build_custom_docperms

	rights = ("read", "write", "create", "report", "submit", "cancel", "amend", "delete")
	expected = {
		row["role"]: tuple(row.get(right, 0) for right in rights) for row in build_custom_docperms({doctype})
	}
	actual = {
		row.role: tuple(row.get(right, 0) for right in rights)
		for row in frappe.get_meta(doctype).permissions
		if row.permlevel == 0
	}
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
def as_non_deleter():
	"""Người dùng không phải R10: xóa danh mục luôn bị chặn (A-37 d). Administrator xóa được danh mục chưa dùng (A-64)."""
	from tracecore.tests.factories import make_user

	user = make_user("non-deleter@example.com", ["TC R02"])
	previous = frappe.session.user
	frappe.set_user(user)
	try:
		yield
	finally:
		frappe.set_user(previous)


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


SAVEPOINT_MISSING = 1305  # MariaDB: SAVEPOINT ... does not exist


def rollback_to_test_savepoint():
	"""Hoàn tác về savepoint của `IsolatedTestCase`; savepoint đã mất thì rollback thường.

	Câu lệnh gây commit ngầm giữa test (DDL lần đầu chạm trên site mới, luồng đăng nhập/OTP) hủy savepoint; khi đó
	``ROLLBACK TO SAVEPOINT`` ném 1305 làm test lỗi ở bước dọn dù phần kiểm tra đã đạt (CI site mới).
	"""
	try:
		frappe.db.rollback(save_point=TEST_SAVEPOINT)
	except OperationalError as error:
		if error.args[0] != SAVEPOINT_MISSING:
			raise
		frappe.db.rollback()


class IsolatedTestCase(FrappeTestCase):
	"""FrappeTestCase hoàn tác dữ liệu sau MỖI test (savepoint), không chỉ sau cả class.

	Dùng khi test sửa dữ liệu dùng chung với test khác trong class (mẫu nhãn mẫu, máy in của trạm…).
	"""

	def setUp(self):
		super().setUp()
		frappe.db.savepoint(TEST_SAVEPOINT)
		self.addCleanup(rollback_to_test_savepoint)


def bru(*ids):
	"""Gắn marker BRU cho test (kiểm bằng scripts/check_bru_coverage.py)."""

	def decorator(fn):
		fn.__bru__ = tuple(ids)
		return fn

	return decorator


class _FakeRequest:
	host = "localhost"  # frappe.utils.get_url (link tới chứng từ trong ERPNext) đọc request.host

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


LOCAL_PRINTERS_FLAG = "tracecore_allow_local_printers"


def allow_local_printers(testcase):
	"""Bật cờ site_config ``tracecore_allow_local_printers`` cho một test (máy in giả trên 127.0.0.1); tự tắt sau test."""
	had, before = LOCAL_PRINTERS_FLAG in frappe.conf, frappe.conf.get(LOCAL_PRINTERS_FLAG)
	frappe.conf[LOCAL_PRINTERS_FLAG] = 1

	def restore():
		if had:
			frappe.conf[LOCAL_PRINTERS_FLAG] = before
		else:
			frappe.conf.pop(LOCAL_PRINTERS_FLAG, None)

	testcase.addCleanup(restore)
