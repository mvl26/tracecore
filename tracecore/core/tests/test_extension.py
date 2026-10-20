from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import extension

PATH = "tracecore.core.tests.test_extension."


def hook_a(*args, **kwargs):
	return ("a", args, kwargs)


def hook_b(*args, **kwargs):
	return "b"


def hook_returns_none(*args, **kwargs):
	return None


def hook_returns_falsy(*args, **kwargs):
	return 0


def hook_raises(*args, **kwargs):
	raise ValueError("hook failed")


class TestExtension(FrappeTestCase):
	def test_run_collects_results_in_hook_order(self):
		paths = [PATH + "hook_b", PATH + "hook_returns_none", PATH + "hook_a"]
		with patch("frappe.get_hooks", return_value=paths) as get_hooks:
			results = extension.run("tracecore_demo_hook", 1, key=2)
		get_hooks.assert_called_once_with("tracecore_demo_hook")
		self.assertEqual(results, ["b", ("a", (1,), {"key": 2})])

	def test_run_drops_only_none_results(self):
		paths = [PATH + "hook_returns_falsy", PATH + "hook_returns_none"]
		with patch("frappe.get_hooks", return_value=paths):
			self.assertEqual(extension.run("tracecore_demo_hook"), [0])

	def test_run_without_registered_hooks_returns_empty_list(self):
		self.assertEqual(extension.run("tracecore_hook_nobody_registered", "ctx"), [])

	def test_run_accepts_a_single_dotted_path(self):
		with patch("frappe.get_hooks", return_value=PATH + "hook_b"):
			self.assertEqual(extension.run("tracecore_demo_hook"), ["b"])

	def test_run_lets_hook_exceptions_propagate(self):
		paths = [PATH + "hook_b", PATH + "hook_raises", PATH + "hook_a"]
		with patch("frappe.get_hooks", return_value=paths), self.assertRaises(ValueError):
			extension.run("tracecore_demo_hook")

	def test_run_with_unknown_dotted_path_fails_loudly(self):
		with patch("frappe.get_hooks", return_value=["tracecore.core.no_such_module.hook"]):
			with self.assertRaises(ImportError):
				extension.run("tracecore_demo_hook")
