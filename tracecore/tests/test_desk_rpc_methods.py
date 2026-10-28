"""JS Desk gọi RPC chỉ nhận GET (``@frappe.whitelist(methods=["GET"])``) phải gửi GET.

``frappe.xcall`` luôn gửi POST và Frappe trả 403 "Không được phép" cho method sai: ma trận năng lực (FEAT-037), trung
tâm thông báo (FEAT-010) và chứng chỉ trên form Nhân viên (FEAT-036) từng hỏng vì vậy. Test quét mọi file JS của app.
"""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

APP_PATH = frappe.get_app_path("tracecore")
WHITELIST = re.compile(r"@frappe\.whitelist\(([^)]*)\)\s*\ndef (\w+)")
CONSTANT = re.compile(r"const (\w+) = \"(tracecore\.v1\.[\w.]+)\"")
XCALL = re.compile(r"\.xcall\(\s*(?:\"([\w.]+)\"|(\w+) \+ \"(\w+)\")")
FRAPPE_CALL = re.compile(r"frappe\.call\(\{(.*?)\}\);", re.S)
METHOD_ARG = re.compile(r"method: (?:\"([\w.]+)\"|(\w+) \+ \"(\w+)\")")


def get_only_methods():
	"""Tên đầy đủ ``tracecore.v1.<module>.<hàm>`` của mọi RPC chỉ nhận GET."""
	names = set()
	v1 = os.path.join(APP_PATH, "v1")
	for root, _dirs, files in os.walk(v1):
		if "tests" in root.split(os.sep):
			continue
		for file in files:
			if not file.endswith(".py"):
				continue
			module = os.path.relpath(os.path.join(root, file), APP_PATH)[:-3].replace(os.sep, ".")
			with open(os.path.join(root, file), encoding="utf-8") as handle:
				source = handle.read()
			for args, name in WHITELIST.findall(source):
				if re.search(r"methods=\[\"GET\"\]", args):
					names.add(f"tracecore.{module}.{name}")
	return names


def js_files():
	for root, dirs, files in os.walk(APP_PATH):
		dirs[:] = [d for d in dirs if d not in ("node_modules", "dist", "__pycache__")]
		for file in files:
			if file.endswith(".js"):
				yield os.path.join(root, file)


def _resolve(literal, constant, suffix, constants):
	return literal or (constants.get(constant, "") + suffix)


class TestDeskRpcMethods(FrappeTestCase):
	def test_scanner_sees_the_get_only_methods(self):
		methods = get_only_methods()
		self.assertIn("tracecore.v1.competency.matrix", methods)
		self.assertIn("tracecore.v1.notification.inbox", methods)
		self.assertNotIn("tracecore.v1.competency.grant", methods)

	def test_get_only_methods_are_never_called_with_post(self):
		methods = get_only_methods()
		wrong = []
		for path in js_files():
			with open(path, encoding="utf-8") as handle:
				script = handle.read()
			constants = dict(CONSTANT.findall(script))
			name = os.path.relpath(path, APP_PATH)
			for literal, constant, suffix in XCALL.findall(script):
				method = _resolve(literal, constant, suffix, constants)
				if method in methods:
					wrong.append(f"{name}: xcall {method}")
			for block in FRAPPE_CALL.findall(script):
				match = METHOD_ARG.search(block)
				if not match:
					continue
				method = _resolve(*match.groups(), constants)
				if method in methods and 'type: "GET"' not in block:
					wrong.append(f"{name}: frappe.call {method} without type GET")
		self.assertFalse(wrong, wrong)
