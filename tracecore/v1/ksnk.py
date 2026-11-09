"""RPC chỉ đọc tracecore.v1.ksnk.* — menu màn quản lý KSNK toàn viện (FEAT-056; A-131 b)."""

import frappe

from tracecore.ui import ksnk


@frappe.whitelist(methods=["GET"])
def nav():
	"""Mục menu theo vai trò người gọi và số việc chờ (hook ``tracecore_ksnk_badges``) trong một lần gọi."""
	return ksnk.nav()
