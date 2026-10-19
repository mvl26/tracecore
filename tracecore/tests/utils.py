"""Tiện ích dùng chung cho test TraceCore."""

from contextlib import contextmanager

import frappe


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
