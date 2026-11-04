"""Mã lệnh cho nút, tab, trạm ở màn trạm và tờ mã lệnh A4 (A-119, FEAT-083, FR-M9-23)."""

import io

from pypdf import PdfReader

from tracecore.core import command_codes, qr
from tracecore.setup.migrate_a64 import apply_yhct
from tracecore.tests.utils import IsolatedTestCase, bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
DANGEROUS = (
	"cancel",
	"discard",
	"void",
	"reject",
	"force",
	"remove",
	"emergency",
	"override",
	"late",
	"reset",
)


class TestParse(IsolatedTestCase):
	def test_do_tab_and_station_codes(self):
		self.assertEqual(command_codes.parse("CMD-DO-CONFIRM-PACK"), ("do", "CONFIRM-PACK"))
		self.assertEqual(
			command_codes.parse(" cmd-do-confirm-pack\r\n"), ("do", "CONFIRM-PACK")
		)  # máy quét gõ thường
		self.assertEqual(command_codes.parse("CMD-TAB-T2"), ("tab", "T2"))
		self.assertEqual(command_codes.parse("TR-004"), ("station", "TR-004"))

	def test_old_complete_load_code_is_an_alias(self):
		self.assertEqual(command_codes.parse("HOAN-THANH-NAP"), ("do", "COMPLETE-LOAD"))

	def test_unknown_or_data_codes_are_not_commands(self):
		for raw in (
			"CMD-DO-NOT-A-COMMAND",
			"CMD-DO-",
			"9520000DEMOSID000003",
			"NV-00001",
			"LR-261104-01",
			"",
			None,
			7,
		):
			self.assertIsNone(command_codes.parse(raw), raw)

	@bru("BRU-FLOW-003")
	def test_no_dangerous_button_has_a_command(self):
		for key, command in command_codes.COMMANDS.items():
			text = " ".join((key, *command["selectors"])).lower()
			for word in DANGEROUS:
				self.assertNotIn(word, text, key)

	def test_every_command_has_selectors_a_label_and_a_scope(self):
		for key, command in command_codes.COMMANDS.items():
			self.assertTrue(command["selectors"], key)
			self.assertTrue(command["label"], key)
			self.assertTrue(command["functions"], key)


class TestSheet(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		apply_yhct(dry_run=False)

	def codes(self, station):
		sheet = command_codes.for_station(station)
		return {row["code"] for group in sheet.values() for row in group}

	def test_sheet_has_stations_tabs_and_actions_of_that_station(self):
		sheet = command_codes.for_station("TR-004")  # dỡ lô rửa
		self.assertTrue(sheet["stations"] and sheet["actions"])
		self.assertIn("TR-001", {row["code"] for row in sheet["stations"]})
		self.assertTrue(all(row["label"] for group in sheet.values() for row in group))

	def test_actions_follow_the_functions_of_the_station(self):
		self.assertIn("CMD-DO-SUBMIT-RECEIPT", self.codes("TR-001"))  # T1
		self.assertNotIn("CMD-DO-SUBMIT-RECEIPT", self.codes("TR-006"))  # trạm đóng gói
		self.assertIn("CMD-DO-CONFIRM-PACK", self.codes("TR-006"))

	def test_unknown_station_gives_an_empty_sheet(self):
		sheet = command_codes.for_station("TR-999")
		self.assertEqual([len(group) for group in sheet.values()], [0, 0, 0])

	def test_pdf_has_a_qr_that_decodes_to_each_code(self):
		pdf = command_codes.sheet_pdf("TR-006")
		reader = PdfReader(io.BytesIO(pdf))
		self.assertGreaterEqual(len(reader.pages), 1)
		decoded = set()
		for page in reader.pages:
			for image in page.images:
				decoded.add(qr.decode_png(image.data))
		expected = self.codes("TR-006")
		self.assertTrue(expected <= decoded, expected - decoded)
		self.assertIn("TR-006", reader.pages[0].extract_text())
