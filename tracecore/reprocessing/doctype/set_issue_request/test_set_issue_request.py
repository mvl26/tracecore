"""Set Issue Request (FEAT-101, A-161): quyền chỉ đọc theo ma trận và lối vào ở phân hệ Dụng cụ và bộ."""

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.setup.permissions import FIXTURE_PATH, build_custom_docperms
from tracecore.v1 import navigation

DOCTYPE = "Set Issue Request"
READERS = {"TC R01", "TC R02", "TC R06", "TC R10", "System Manager"}


class TestSetIssueRequest(FrappeTestCase):
	def test_roles_only_read_the_request(self):
		records = [row for row in build_custom_docperms({DOCTYPE}) if row["parent"] == DOCTYPE]
		self.assertEqual({row["role"] for row in records}, READERS)
		for row in records:
			self.assertEqual(row["read"], 1)
			for flag in ("write", "create", "submit", "cancel", "delete", "amend"):
				self.assertFalse(row.get(flag), (row["role"], flag))

	def test_fixture_carries_the_generated_rows(self):
		fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
		shipped = {row["name"]: row for row in fixture if row["parent"] == DOCTYPE}
		generated = {row["name"]: row for row in build_custom_docperms({DOCTYPE}) if row["parent"] == DOCTYPE}
		self.assertEqual(shipped, generated)

	def test_request_list_opens_from_instruments_and_sets(self):
		frappe.set_user("Administrator")
		module = next(
			row for row in navigation._admin_modules(("instruments",)) if row["key"] == "instruments"
		)
		documents = next(section for section in module["sections"] if section["kind"] == "document")
		link = next(row for row in documents["links"] if row["doctype"] == DOCTYPE)
		self.assertEqual(link["route"], "/app/set-issue-request")
		flows = dict(navigation.ROLE_FLOWS["TC R02"])
		self.assertIn(DOCTYPE, dict(flows["instruments"])["document"])
		self.assertIn(DOCTYPE, dict(navigation.MANAGEMENT_GROUPS)["Instruments"])
