"""Bộ thẻ test theo vai trò (#1829)."""

import json
import os
import tempfile
from unittest.mock import patch

import frappe

from tracecore.core import station_auth
from tracecore.setup import test_cards
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestTestCards(IsolatedTestCase):
	def run_it(self):
		self.path = os.path.join(tempfile.mkdtemp(), "cards.json")
		return test_cards.create_test_cards(out_path=self.path)

	def entries(self):
		with open(self.path, encoding="utf8") as handle:
			return json.load(handle)

	def test_creates_a_card_per_role_with_different_competency(self):
		result = self.run_it()
		self.assertEqual(result["count"], len(test_cards.SPECS))
		self.assertGreaterEqual(result["count"], 8)
		rows = {row["role"]: row for row in self.entries()}
		self.assertEqual(
			set(rows), {"TC R01", "TC R02", "TC R03", "TC R04", "TC R05", "TC R06", "TC R08", "TC R09"}
		)
		r03 = frappe.db.get_value("Employee", {"tc_card_id": rows["TC R03"]["card"]}, "name")
		self.assertTrue(station_auth.can_work_at(r03, "TR-001"))
		self.assertFalse(station_auth.can_work_at(r03, "TR-004"))
		r08 = frappe.db.get_value("Employee", {"tc_card_id": rows["TC R08"]["card"]}, "name")
		self.assertTrue(station_auth.can_work_at(r08, "TR-008"))
		self.assertFalse(station_auth.can_work_at(r08, "TR-001"))
		self.assertEqual(rows["TC R09"]["stations"], [])

	def test_result_and_output_hold_no_secret(self):
		with patch("builtins.print") as printed:
			result = self.run_it()
		secrets = [row["pin"] for row in self.entries()]
		text = json.dumps(result) + str(printed.call_args_list)
		for pin in secrets:
			self.assertNotIn(pin, text)
		self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

	def test_runs_outside_the_test_runner_as_administrator(self):
		# bench execute: không có cờ in_test nên hook account đòi R10 khi tạo User
		frappe.set_user("Administrator")
		frappe.flags.in_test = False
		self.addCleanup(setattr, frappe.flags, "in_test", True)
		result = self.run_it()
		self.assertEqual(result["count"], len(test_cards.SPECS))
		self.assertFalse(frappe.db.exists("Has Role", {"parent": "Administrator", "role": "TC R10"}))

	def test_second_run_keeps_cards_and_pins(self):
		self.run_it()
		first = self.entries()
		test_cards.create_test_cards(out_path=self.path)
		self.assertEqual(self.entries(), first)

	def test_refuses_a_non_test_site_without_the_flag(self):
		with (
			patch.object(test_cards, "_is_test_site", return_value=False),
			self.assertRaises(frappe.ValidationError),
		):
			test_cards.create_test_cards(out_path=os.path.join(tempfile.mkdtemp(), "never.json"))

	def test_output_file_must_be_outside_the_public_site_files(self):
		with self.assertRaises(frappe.ValidationError):
			test_cards.create_test_cards(out_path=frappe.get_site_path("public", "files", "cards.json"))

	def test_r01_card_can_work_at_the_sterilization_unload_stations(self):
		spec = next(row for row in test_cards.SPECS if row[0] == "TC R01")
		self.assertEqual(spec[2], ("STERI_UNLOAD",))
