"""A-127 (FEAT-090): QR mã lệnh cạnh nút xác nhận trên màn trạm."""

import base64

import frappe

from tracecore.core import command_codes, qr
from tracecore.setup.migrate_a64 import apply_yhct
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import station as station_api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
SETTINGS = "TraceCore Settings"


def _decode(data_uri):
	return qr.decode_png(base64.b64decode(data_uri.split(",", 1)[1]))


class TestScreenQr(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		apply_yhct(dry_run=False)

	def test_only_confirm_commands_of_the_station_get_a_qr(self):
		images = command_codes.screen_qr("TR-001")  # tiếp nhận
		self.assertEqual(set(images), {"SUBMIT-RECEIPT", "CONFIRM-SET"})
		self.assertTrue(images["CONFIRM-SET"].startswith("data:image/png;base64,"))
		self.assertEqual(_decode(images["CONFIRM-SET"]), "CMD-DO-CONFIRM-SET")
		packing = command_codes.screen_qr("TR-006")
		self.assertIn("CONFIRM-PACK", packing)
		for key in ("HELP", "MANUAL-PICK", "RESCAN-CARD", "PRINT-LABEL"):
			self.assertNotIn(key, packing)

	def test_screen_qr_keys_are_known_commands(self):
		self.assertTrue(set(command_codes.SCREEN_QR) <= set(command_codes.COMMANDS))
		self.assertEqual(command_codes.screen_qr("TR-999"), {})

	def test_rpc_returns_qr_by_setting(self):
		session = make_station_session(make_user("tc-cmd-qr@example.com"), "TR-001")
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "show_command_qr"), 1)  # mặc định bật
		result = station_api.commands(token=session["token"])
		self.assertTrue(result["show_qr"])
		self.assertEqual(_decode(result["qr"]["CONFIRM-SET"]), "CMD-DO-CONFIRM-SET")
		self.assertIn("CONFIRM-SET", result["commands"])  # danh sách bộ chọn giữ nguyên
		frappe.db.set_single_value(SETTINGS, "show_command_qr", 0)
		result = station_api.commands(token=session["token"])
		self.assertFalse(result["show_qr"])
		self.assertEqual(result["qr"], {})

	def test_patch_turns_it_on_only_when_never_set(self):
		from tracecore.patches.v0_1 import a127_show_command_qr

		frappe.db.sql("delete from tabSingles where doctype=%s and field='show_command_qr'", SETTINGS)
		a127_show_command_qr.execute()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "show_command_qr"), 1)
		frappe.db.set_single_value(SETTINGS, "show_command_qr", 0)
		a127_show_command_qr.execute()  # R10 đã tắt thì giữ nguyên
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "show_command_qr"), 0)

	def test_station_screen_decorates_buttons(self):
		path = frappe.get_app_path("tracecore", "ui", "page", "station", "station.js")
		with open(path, encoding="utf-8") as handle:
			source = handle.read()
		self.assertIn("decorateCommandButtons", source)
		self.assertIn("MutationObserver", source)
		self.assertIn("tc-cmd-qr", source)
		css = frappe.get_app_path("tracecore", "ui", "page", "station", "station.css")
		with open(css, encoding="utf-8") as handle:
			style = handle.read()
		self.assertIn(".tc-cmd-qr", style)
		self.assertIn('[data-surface="PDA"] .tc-cmd-qr', style)


class TestCommandQrRpc(IsolatedTestCase):
	"""A-128: ảnh QR cho mã lệnh của mọi nút, sinh tại server."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		apply_yhct(dry_run=False)
		self.session = make_station_session(make_user("tc-cmd-qr-all@example.com"), "TR-001")

	def test_images_for_valid_codes_only(self):
		codes = [
			"CMD-BTN-DISCARD",
			"CMD-BTN-CI-PICK.2",
			"CMD-DO-CONFIRM-SET",
			"CMD-DO-KHONG-CO",
			"<b>",
			"CMD-BTN-X.0",
		]
		result = station_api.command_qr(token=self.session["token"], codes=codes)
		self.assertTrue(result["ok"])
		images = result["qr"]
		self.assertEqual(set(images), {"CMD-BTN-DISCARD", "CMD-BTN-CI-PICK.2", "CMD-DO-CONFIRM-SET"})
		self.assertEqual(_decode(images["CMD-BTN-CI-PICK.2"]), "CMD-BTN-CI-PICK.2")

	def test_numeric_alias_codes(self):
		"""A-129: mã toàn số `99-NNNN` (bộ gõ tiếng Việt không đổi được) cũng có ảnh QR."""
		result = station_api.command_qr(token=self.session["token"], codes=["99-0001", "99-12", "99-00001"])
		self.assertEqual(set(result["qr"]), {"99-0001"})
		self.assertEqual(_decode(result["qr"]["99-0001"]), "99-0001")

	def test_codes_as_json_and_limit(self):
		import json

		many = [f"CMD-BTN-ROW.{n}" for n in range(2, 200)]
		result = station_api.command_qr(token=self.session["token"], codes=json.dumps(many))
		self.assertEqual(len(result["qr"]), command_codes.QR_BATCH_LIMIT)

	def test_setting_off_and_bad_session(self):
		frappe.db.set_single_value(SETTINGS, "show_command_qr", 0)
		self.assertEqual(
			station_api.command_qr(token=self.session["token"], codes=["CMD-BTN-DISCARD"])["qr"], {}
		)
		self.assertFalse(station_api.command_qr(token="khong-co", codes=["CMD-BTN-DISCARD"])["ok"])
