"""RPC `station.commands` và `station.command_sheet` (A-119, FEAT-083, FR-M9-23)."""

import base64
import io

import frappe
from pypdf import PdfReader

from tracecore.setup.migrate_a64 import apply_yhct
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import station as station_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]


class TestStationCommands(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		apply_yhct(dry_run=False)
		self.user = make_user("tc-commands@example.com")
		self.session = make_station_session(self.user, "TR-006")  # đóng gói

	def test_commands_of_the_session_station_only(self):
		result = station_api.commands(token=self.session["token"])
		self.assertTrue(result["ok"])
		commands = result["commands"]
		self.assertIn("CONFIRM-PACK", commands)
		self.assertNotIn("SUBMIT-RECEIPT", commands)  # T1 không áp dụng cho trạm đóng gói
		self.assertEqual(commands["CONFIRM-PACK"], ['[data-action="confirm-pack"]'])

	def test_commands_need_a_valid_session(self):
		self.assertFalse(station_api.commands(token="khong-co-phien")["ok"])

	def test_command_sheet_returns_an_a4_pdf(self):
		result = station_api.command_sheet(station="TR-006")
		self.assertTrue(result["ok"])
		self.assertEqual(result["filename"], "TR-006-COMMANDS.pdf")
		page = PdfReader(io.BytesIO(base64.b64decode(result["pdf_b64"]))).pages[0]
		self.assertAlmostEqual(float(page.mediabox.width) * 25.4 / 72, 210, delta=2)

	def test_command_sheet_rejects_unknown_station_and_other_roles(self):
		with self.assertRaises(Exception):
			station_api.command_sheet(station="TR-999")
		frappe.set_user(make_user("tc-commands-none@example.com"))
		with self.assertRaises(frappe.PermissionError):
			station_api.command_sheet(station="TR-006")
