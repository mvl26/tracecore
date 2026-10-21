"""Mã đối tượng (FEAT-005 Task 4): cấp mã cuộn nhãn, vô hiệu mã khi thiết bị ngừng sử dụng, in nhãn QR đối tượng.

`v1.codes.issue_rolls` cấp ``CN-#####`` hàng loạt trong một transaction (Review Focus 1); `v1.print.object_label`
in nhãn QR qua đường server (A-05 R1) và chặn mã ``Disabled``/thiết bị ``Retired`` (Review Focus 4, R4);
`v1.print.object_preview` cho R10/R02 xem trước.
"""

import base64
import io
import json
import uuid
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from PIL import Image

from tracecore.core import code_registry, qr
from tracecore.core.errors import HTTP_STATUS
from tracecore.equipment.status import set_status
from tracecore.tests.factories import (
	deactivate_printers,
	make_equipment,
	make_item,
	make_label_items,
	make_printer,
	make_roll,
	make_user,
)
from tracecore.tests.utils import IsolatedTestCase, bru, request_headers
from tracecore.v1 import codes as codes_api
from tracecore.v1 import equipment as equipment_api
from tracecore.v1 import print as print_api

test_ignore = ["Asset", "Item", "User"]

PRINTER_STATION = "TR-004"
LABEL_STATION = "TR-003"


def now_ts():
	return datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(timespec="seconds")


def call(fn, key=None, **kwargs):
	frappe.local.response.pop("http_status_code", None)
	kwargs.setdefault("client_ts", now_ts())
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4())}):
		return fn(**kwargs)


def read(fn, **kwargs):
	"""RPC chỉ đọc (không `@idempotent`), vẫn có request giả để mã HTTP được đặt."""
	frappe.local.response.pop("http_status_code", None)
	with request_headers({}):
		return fn(**kwargs)


def http_status():
	return frappe.local.response.get("http_status_code")


def as_user(roles, fn, caller=call, **kwargs):
	email = make_user(
		f"codes-{'-'.join(r.lower().replace(' ', '') for r in roles) or 'none'}@example.com", roles
	)
	frappe.set_user(email)
	try:
		return caller(fn, **kwargs)
	finally:
		frappe.set_user("Administrator")


def rejects(code):
	return frappe.db.count("Audit Log", {"action": "Reject", "reason": code})


def series_current():
	return frappe.db.sql("select current from tabSeries where name = %s", "CN-")[0][0]


def batch_codes(item):
	return frappe.get_all(
		"Code Registry", filters={"prefix": "CN", "ref_doctype": "Item", "ref_name": item}, pluck="name"
	)


class TestIssueRolls(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.steam_item = make_label_items()[0]

	@bru("BRU-ID-006")
	def test_issue_rolls_sequential_registered_and_atomic(self):
		result = call(codes_api.issue_rolls, item=self.steam_item, count=5)
		self.assertTrue(result["ok"])
		self.assertEqual(result["item"], self.steam_item)
		codes = result["codes"]
		self.assertEqual(len(codes), 5)
		numbers = [int(code.removeprefix("CN-")) for code in codes]
		self.assertEqual(numbers, list(range(numbers[0], numbers[0] + 5)))
		for code in codes:
			self.assertRegex(code, r"^CN-\d{5}$")
			row = frappe.db.get_value(
				"Code Registry", code, ["prefix", "ref_doctype", "ref_name", "status"], as_dict=True
			)
			self.assertEqual(
				(row.prefix, row.ref_doctype, row.ref_name, row.status),
				("CN", "Item", self.steam_item, "Active"),
			)
			self.assertEqual(code_registry.roll_label_item(code), self.steam_item)

		# lỗi ở mã thứ 3: không còn mã nào của loạt, bộ đếm không thủng số
		before = set(batch_codes(self.steam_item))
		series_before = series_current()
		real_register = code_registry.register
		calls = []

		def flaky(*args, **kwargs):
			calls.append(args[0])
			if len(calls) == 3:
				raise frappe.ValidationError("disk full")
			return real_register(*args, **kwargs)

		with patch.object(code_registry, "register", side_effect=flaky):
			with self.assertRaises(frappe.ValidationError):
				call(codes_api.issue_rolls, item=self.steam_item, count=5)
		self.assertEqual(len(calls), 3)
		self.assertEqual(set(batch_codes(self.steam_item)), before)
		for code in calls:
			self.assertFalse(code_registry.is_issued(code), code)
		self.assertEqual(series_current(), series_before)
		# lần cấp sau tiếp nối liền số, không bỏ qua số của loạt lỗi
		again = call(codes_api.issue_rolls, item=self.steam_item, count=1)["codes"][0]
		self.assertEqual(again, calls[0])

	def test_issue_rolls_200_in_one_call(self):
		codes = call(codes_api.issue_rolls, item=self.steam_item, count=200)["codes"]
		self.assertEqual(len(set(codes)), 200)
		numbers = [int(code.removeprefix("CN-")) for code in codes]
		self.assertEqual(numbers, list(range(numbers[0], numbers[0] + 200)))

	def test_issue_rolls_requires_r10_or_sm_before_any_write(self):
		keys = frappe.db.count("Idempotency Key")
		audit_rows = frappe.db.count("Audit Log")
		issued = frappe.db.count("Code Registry")
		for roles in (["TC R04"], ["TC R02"], []):
			with self.assertRaises(frappe.PermissionError, msg=roles):
				as_user(roles, codes_api.issue_rolls, item=self.steam_item, count=3)
		self.assertEqual(frappe.db.count("Idempotency Key"), keys)
		self.assertEqual(frappe.db.count("Audit Log"), audit_rows)
		self.assertEqual(frappe.db.count("Code Registry"), issued)
		for roles in (["TC R10"], ["System Manager"]):
			self.assertTrue(as_user(roles, codes_api.issue_rolls, item=self.steam_item, count=1)["ok"])

	def test_issue_rolls_rejects_non_label_item_and_bad_count(self):
		packaging = make_item("VT-BAO-GOI-T4", "Packaging").name
		unmethod = make_item("VT-NHAN-KHONG-PP", "Label").name
		issued = frappe.db.count("Code Registry")
		before = rejects("ROLL_NOT_LABEL")
		for item in (packaging, unmethod, "KHONG-CO-ITEM", None):
			result = call(codes_api.issue_rolls, item=item, count=2)
			self.assertFalse(result["ok"], item)
			self.assertEqual(result["error"]["code"], "ROLL_NOT_LABEL")
			self.assertTrue(
				result["error"]["title"] and result["error"]["reason"] and result["error"]["action"]
			)
			self.assertEqual(http_status(), 422)
		self.assertEqual(rejects("ROLL_NOT_LABEL"), before + 4)
		before = rejects("COUNT_OUT_OF_RANGE")
		for count in (0, 201, -1, "abc", 2.5, None, True):
			result = call(codes_api.issue_rolls, item=self.steam_item, count=count)
			self.assertFalse(result["ok"], count)
			self.assertEqual(result["error"]["code"], "COUNT_OUT_OF_RANGE")
			self.assertEqual(http_status(), 422)
		self.assertEqual(rejects("COUNT_OUT_OF_RANGE"), before + 7)
		self.assertEqual(frappe.db.count("Code Registry"), issued)
		# số lượng dạng chuỗi số (từ hộp thoại Desk) được nhận
		self.assertEqual(len(call(codes_api.issue_rolls, item=self.steam_item, count="2")["codes"]), 2)

	def test_issue_rolls_replay_same_key_same_codes(self):
		key = str(uuid.uuid4())
		ts = now_ts()
		first = call(codes_api.issue_rolls, key=key, item=self.steam_item, count=3, client_ts=ts)
		issued = frappe.db.count("Code Registry")
		second = call(codes_api.issue_rolls, key=key, item=self.steam_item, count=3, client_ts=ts)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Code Registry"), issued)

	def test_issue_rolls_is_whitelisted_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[codes_api.issue_rolls], ["POST"])
		self.assertEqual(frappe.get_attr("tracecore.v1.codes.issue_rolls"), codes_api.issue_rolls)


class TestDisableOnRetire(IsolatedTestCase):
	@bru("BRU-ID-006")
	def test_retire_equipment_disables_tb_code(self):
		equipment = make_equipment(name="Máy ngừng mã", serial="SN-CODE-RET")
		self.assertEqual(frappe.db.get_value("Code Registry", equipment.name, "status"), "Active")
		set_status(equipment.name, "Retired", "Hết khấu hao")
		row = frappe.db.get_value(
			"Code Registry", equipment.name, ["status", "disabled_reason", "disabled_on"], as_dict=True
		)
		self.assertEqual(row.status, "Disabled")
		self.assertEqual(row.disabled_reason, "Hết khấu hao")
		self.assertTrue(row.disabled_on)
		# tra cứu lịch sử vẫn được, kèm cảnh báo
		result = equipment_api.get(qr=equipment.name)
		self.assertTrue(result["ok"])
		self.assertEqual(result["equipment"]["name"], equipment.name)
		self.assertEqual(result["warning"]["code"], "EQUIPMENT_RETIRED")
		# mã đã vô hiệu không bao giờ được cấp lại
		with self.assertRaises(code_registry.CodeAlreadyIssuedError):
			code_registry.register(equipment.name, "TB", "Equipment", equipment.name)
		for _ in range(3):
			self.assertNotEqual(code_registry.next_code("TB"), equipment.name)

	def test_other_status_changes_keep_code_active(self):
		equipment = make_equipment(name="Máy khóa mã", serial="SN-CODE-LOCK")
		for status in ("Locked", "Repair", "Ready"):
			set_status(equipment.name, status)
			self.assertEqual(frappe.db.get_value("Code Registry", equipment.name, "status"), "Active")

	def test_retire_equipment_without_registry_row_still_retires(self):
		equipment = make_equipment(name="Máy cũ chưa có sổ", serial="SN-CODE-LEGACY")
		frappe.db.delete("Code Registry", {"name": equipment.name})
		set_status(equipment.name, "Retired", "Cũ")
		self.assertEqual(frappe.db.get_value("Equipment", equipment.name, "status"), "Retired")

	def test_zone_station_deactivation_keeps_code_active(self):
		self.assertEqual(frappe.db.get_value("Code Registry", LABEL_STATION, "status"), "Active")
		station = frappe.get_doc("Zone Station", LABEL_STATION)
		station.is_active = 0
		station.save()
		self.assertEqual(frappe.db.get_value("Code Registry", LABEL_STATION, "status"), "Active")


class ObjectLabelCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		deactivate_printers(PRINTER_STATION)
		self.steam_item = make_label_items()[0]
		self.host_printer = make_printer(PRINTER_STATION, self.steam_item, host="10.0.0.50", name="Desk host")
		self.agent_printer = make_printer(PRINTER_STATION, self.steam_item, host="", name="Agent only")
		enqueue = patch("tracecore.core.print_server.frappe.enqueue")
		self.enqueue = enqueue.start()
		self.addCleanup(enqueue.stop)


class TestObjectLabel(ObjectLabelCase):
	def test_object_label_creates_job_and_dispatches_for_host_printer(self):
		equipment = make_equipment(name="Máy hấp in nhãn", serial="SN-LBL-01")
		result = call(
			print_api.object_label, label_object="Equipment", code=equipment.name, printer=self.host_printer
		)
		self.assertEqual(result["ok"], True)
		self.assertEqual(result["status"], "Queued")
		self.assertIsNone(result["warning"])
		job = frappe.get_doc("Print Job", result["print_job"])
		self.assertEqual(
			(job.status, job.printer, job.station, job.ref_doctype, job.ref_name, job.template),
			(
				"Queued",
				self.host_printer,
				PRINTER_STATION,
				"Equipment",
				equipment.name,
				"Object label - Equipment",
			),
		)
		self.assertIn(f"^FDMA,{equipment.name}^FS", job.payload)
		self.assertIn("May hap in nhan", job.payload)  # máy in không Unicode: bỏ dấu
		data = json.loads(job.data)
		self.assertEqual(
			(data["label_object"], data["code"], data["dispatch"]), ("Equipment", equipment.name, "server")
		)
		self.enqueue.assert_called_once()
		self.assertEqual(self.enqueue.call_args.kwargs["job"], str(job.name))

	def test_object_label_for_station_and_roll(self):
		station = call(
			print_api.object_label, label_object="Station", code=LABEL_STATION, printer=self.host_printer
		)
		job = frappe.get_doc("Print Job", station["print_job"])
		self.assertEqual((job.ref_doctype, job.ref_name), ("Zone Station", LABEL_STATION))
		self.assertIn(f"^FDMA,{LABEL_STATION}^FS", job.payload)
		roll = make_roll(self.steam_item)
		result = call(print_api.object_label, label_object="Roll", code=roll, printer=self.host_printer)
		job = frappe.get_doc("Print Job", result["print_job"])
		self.assertEqual((job.ref_doctype, job.ref_name), ("Item", self.steam_item))
		self.assertIn(f"^FDMA,{roll}^FS", job.payload)
		self.assertEqual(json.loads(job.data)["code"], roll)

	def test_object_label_for_registered_card_and_location(self):
		card = code_registry.register_card("HOSP-CARD-0042", "Zone Station", LABEL_STATION)
		result = call(
			print_api.object_label, label_object="Employee Card", code=card, printer=self.host_printer
		)
		self.assertTrue(result["ok"], result)
		job = frappe.get_doc("Print Job", result["print_job"])
		self.assertEqual((job.ref_doctype, job.ref_name), ("Zone Station", LABEL_STATION))
		self.assertIn("^FDMA,HOSP-CARD-0042^FS", job.payload)
		location = code_registry.next_code("KE", "Zone Station", LABEL_STATION)
		result = call(
			print_api.object_label, label_object="Location", code=location, printer=self.host_printer
		)
		self.assertTrue(result["ok"], result)

	def test_object_label_agent_only_printer_waits_with_warning(self):
		equipment = make_equipment(name="Máy agent", serial="SN-LBL-AG")
		result = call(
			print_api.object_label, label_object="Equipment", code=equipment.name, printer=self.agent_printer
		)
		self.assertTrue(result["ok"])
		self.assertEqual(result["status"], "Waiting")
		self.assertEqual(result["warning"]["code"], "PRINTER_AGENT_ONLY")
		self.assertTrue(result["warning"]["reason"] and result["warning"]["action"])
		self.assertIsNone(http_status())
		job = frappe.get_doc("Print Job", result["print_job"])
		self.assertEqual(job.status, "Waiting")
		self.assertNotIn("dispatch", json.loads(job.data))
		self.enqueue.assert_not_called()
		# đổi cuộn ở trạm không phát hành nhãn đối tượng đang chờ (chỉ nhãn gói)
		self.assertNotIn(
			job.name, [row["print_job"] for row in core_set_roll(self.agent_printer, self.steam_item)]
		)

	@bru("BRU-ID-006")
	def test_object_label_blocked_for_disabled_code_and_retired_equipment(self):
		retired = make_equipment(name="Máy đã ngừng", serial="SN-LBL-RET")
		set_status(retired.name, "Retired", "Hỏng")
		legacy = make_equipment(name="Máy ngừng trước FEAT-005", serial="SN-LBL-LEG")
		set_status(legacy.name, "Retired", "Cũ")
		frappe.db.set_value("Code Registry", legacy.name, "status", "Active")  # dữ liệu cũ: mã chưa vô hiệu
		roll = make_roll(self.steam_item)
		code_registry.disable(roll, "Cuộn hỏng")
		jobs = frappe.db.count("Print Job")
		before = {code: rejects(code) for code in ("EQUIPMENT_RETIRED", "CODE_DISABLED")}
		cases = (
			("Equipment", retired.name, "EQUIPMENT_RETIRED"),
			("Equipment", legacy.name, "EQUIPMENT_RETIRED"),
			("Roll", roll, "CODE_DISABLED"),
		)
		for label_object, code, expected in cases:
			result = call(
				print_api.object_label, label_object=label_object, code=code, printer=self.host_printer
			)
			self.assertFalse(result["ok"], code)
			self.assertEqual(result["error"]["code"], expected)
			self.assertTrue(
				result["error"]["title"] and result["error"]["reason"] and result["error"]["action"]
			)
			self.assertEqual(http_status(), 409)
		self.assertEqual(rejects("EQUIPMENT_RETIRED"), before["EQUIPMENT_RETIRED"] + 2)
		self.assertEqual(rejects("CODE_DISABLED"), before["CODE_DISABLED"] + 1)
		self.assertEqual(frappe.db.count("Print Job"), jobs)
		self.enqueue.assert_not_called()
		# mã trạm bị vô hiệu tay cũng chặn
		code_registry.disable(LABEL_STATION, "Thử")
		result = call(
			print_api.object_label, label_object="Station", code=LABEL_STATION, printer=self.host_printer
		)
		self.assertEqual(result["error"]["code"], "CODE_DISABLED")

	def test_object_label_unknown_code_rejected(self):
		jobs = frappe.db.count("Print Job")
		cases = (
			("Equipment", "TB-9999", "EQUIPMENT_NOT_FOUND", 404),
			("Roll", "CN-99999", "ROLL_NOT_FOUND", 404),
			("Station", "TR-999", "CODE_NOT_FOUND", 404),
			("Location", "KE-9999", "CODE_NOT_FOUND", 404),
			("Employee Card", "NOT-REGISTERED-1", "SCAN_INVALID", 422),
			# mã sai loại: mã thiết bị không in thành nhãn trạm
			("Station", "TB-0001", "SCAN_INVALID", 422),
			("Equipment", LABEL_STATION, "SCAN_INVALID", 422),
			("Equipment", "TB 0001", "SCAN_INVALID", 422),
			("Equipment", "", "SCAN_INVALID", 422),
			("Equipment", "X" * 41, "SCAN_INVALID", 422),
		)
		for label_object, code, expected, status in cases:
			before = rejects(expected)
			result = call(
				print_api.object_label, label_object=label_object, code=code, printer=self.host_printer
			)
			self.assertFalse(result["ok"], (label_object, code))
			self.assertEqual(result["error"]["code"], expected, (label_object, code))
			self.assertEqual(http_status(), status, (label_object, code))
			self.assertEqual(rejects(expected), before + 1, (label_object, code))
		# cuộn của Item không còn là nhãn
		packaging = make_item("VT-BAO-GOI-T4L", "Packaging").name
		roll = make_roll(packaging)
		result = call(print_api.object_label, label_object="Roll", code=roll, printer=self.host_printer)
		self.assertEqual(result["error"]["code"], "ROLL_NOT_LABEL")
		self.assertEqual(frappe.db.count("Print Job"), jobs)

	def test_object_label_bad_parameters_are_400_without_writes(self):
		equipment = make_equipment(name="Máy tham số", serial="SN-LBL-BAD")
		inactive = make_printer(PRINTER_STATION, self.steam_item, host="10.0.0.51", name="Off")
		frappe.db.set_value("Printer", inactive, "is_active", 0)
		audit_rows = frappe.db.count("Audit Log")
		keys = frappe.db.count("Idempotency Key")
		for kwargs in (
			{"label_object": "Pack", "printer": self.host_printer},
			{"label_object": "Equipment", "printer": None},
			{"label_object": "Equipment", "printer": "PRN-NOPE"},
			{"label_object": "Equipment", "printer": inactive},
			{"label_object": "Equipment", "printer": ["x"]},
		):
			with self.assertRaises(frappe.ValidationError, msg=kwargs) as ctx:
				call(print_api.object_label, code=equipment.name, **kwargs)
			self.assertEqual(ctx.exception.http_status_code, 400, kwargs)
		self.assertEqual(frappe.db.count("Audit Log"), audit_rows)
		self.assertEqual(frappe.db.count("Idempotency Key"), keys)

	def test_object_label_missing_template_is_render_failed(self):
		equipment = make_equipment(name="Máy không mẫu", serial="SN-LBL-NOTPL")
		frappe.db.set_value("Label Template", {"label_object": "Equipment"}, "is_active", 0)
		result = call(
			print_api.object_label, label_object="Equipment", code=equipment.name, printer=self.host_printer
		)
		self.assertEqual(result["error"]["code"], "LABEL_RENDER_FAILED")
		self.assertEqual(http_status(), 422)
		self.assertFalse(frappe.local.message_log)

	def test_object_label_requires_roles(self):
		equipment = make_equipment(name="Máy quyền", serial="SN-LBL-ROLE")
		jobs = frappe.db.count("Print Job")
		keys = frappe.db.count("Idempotency Key")
		for roles in (["TC R02"], ["TC R04"], []):
			with self.assertRaises(frappe.PermissionError, msg=roles):
				as_user(
					roles,
					print_api.object_label,
					label_object="Equipment",
					code=equipment.name,
					printer=self.host_printer,
				)
		self.assertEqual(frappe.db.count("Print Job"), jobs)
		self.assertEqual(frappe.db.count("Idempotency Key"), keys)
		for roles in (["TC R10"], ["System Manager"]):
			result = as_user(
				roles,
				print_api.object_label,
				label_object="Equipment",
				code=equipment.name,
				printer=self.host_printer,
			)
			self.assertTrue(result["ok"], roles)

	def test_object_label_replay_same_key_one_job(self):
		equipment = make_equipment(name="Máy lặp in", serial="SN-LBL-REPLAY")
		key = str(uuid.uuid4())
		ts = now_ts()
		kwargs = {
			"label_object": "Equipment",
			"code": equipment.name,
			"printer": self.host_printer,
			"client_ts": ts,
		}
		first = call(print_api.object_label, key=key, **kwargs)
		jobs = frappe.db.count("Print Job")
		self.assertEqual(call(print_api.object_label, key=key, **kwargs), first)
		self.assertEqual(frappe.db.count("Print Job"), jobs)

	def test_object_label_uses_the_rendered_template_without_requery(self):
		# mẫu bị tắt giữa lúc render và lúc tạo job không được làm lỗi 500 (None.name): chỉ tra mẫu một lần
		from tracecore.core import print as core_print

		equipment = make_equipment(name="Máy một lần tra mẫu", serial="SN-LBL-ONCE")
		real = core_print.active_template
		with patch.object(core_print, "active_template", side_effect=real) as lookup:
			result = call(
				print_api.object_label,
				label_object="Equipment",
				code=equipment.name,
				printer=self.host_printer,
			)
		self.assertTrue(result["ok"], result)
		self.assertEqual(lookup.call_count, 1)
		self.assertEqual(
			frappe.db.get_value("Print Job", result["print_job"], "template"), "Object label - Equipment"
		)

	def test_object_label_is_whitelisted_post_only(self):
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[print_api.object_label], ["POST"])
		self.assertEqual(frappe.get_attr("tracecore.v1.print.object_label"), print_api.object_label)


def core_set_roll(printer, label_item):
	from tracecore.core import print as core_print

	return core_print.set_roll(printer, make_roll(label_item))["released_jobs"]


class TestObjectPreview(ObjectLabelCase):
	def test_object_preview_returns_png_zpl_and_hri(self):
		equipment = make_equipment(name="Máy xem trước", serial="SN-LBL-PREV")
		jobs = frappe.db.count("Print Job")
		for roles in (["TC R10"], ["TC R02"], ["System Manager"]):
			result = as_user(
				roles, print_api.object_preview, caller=read, label_object="Equipment", code=equipment.name
			)
			self.assertTrue(result["ok"], roles)
			self.assertEqual(result["hri"], equipment.name)
			self.assertIn(f"^FDMA,{equipment.name}^FS", result["zpl"])
			png = base64.b64decode(result["png_b64"])
			image = Image.open(io.BytesIO(png))
			self.assertEqual(image.size, (590, 354))
			# QR bên trái như mẫu mặc định (cột chữ từ x = 210): phần cắt ra giải lại đúng mã
			crop = io.BytesIO()
			image.crop((0, 0, 205, 354)).save(crop, format="PNG")
			self.assertEqual(qr.decode_png(crop.getvalue()), equipment.name)
		self.assertEqual(frappe.db.count("Print Job"), jobs)

	def test_object_preview_requires_roles_and_blocks_disabled(self):
		equipment = make_equipment(name="Máy xem trước 2", serial="SN-LBL-PREV2")
		with self.assertRaises(frappe.PermissionError):
			as_user(
				["TC R04"],
				print_api.object_preview,
				caller=read,
				label_object="Equipment",
				code=equipment.name,
			)
		set_status(equipment.name, "Retired", "Hỏng")
		result = read(print_api.object_preview, label_object="Equipment", code=equipment.name)
		self.assertEqual(result["error"]["code"], "EQUIPMENT_RETIRED")
		self.assertEqual(http_status(), 409)


class TestNewErrorCodes(IsolatedTestCase):
	def test_http_status_codes_new(self):
		self.assertEqual(HTTP_STATUS["CODE_DISABLED"], 409)
		self.assertEqual(HTTP_STATUS["COUNT_OUT_OF_RANGE"], 422)
		self.assertEqual(HTTP_STATUS["CODE_NOT_FOUND"], 404)


class TestListRolls(IsolatedTestCase):
	"""`v1.codes.list_rolls`: mã cuộn Active của một Item nhãn, để in lại nhãn cuộn đã cấp (in lỗi, mất nhãn)."""

	def setUp(self):
		super().setUp()
		self.steam_item, self.plasma_item = make_label_items()

	def test_list_rolls_returns_active_rolls_of_the_item_in_order(self):
		issued = call(codes_api.issue_rolls, item=self.steam_item, count=3)["codes"]
		other = call(codes_api.issue_rolls, item=self.plasma_item, count=1)["codes"]
		code_registry.disable(issued[1], "Cuộn hỏng")
		result = read(codes_api.list_rolls, item=self.steam_item)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["item"], self.steam_item)
		codes = result["codes"]
		self.assertIn(issued[0], codes)
		self.assertIn(issued[2], codes)
		self.assertNotIn(issued[1], codes)  # Disabled không in lại được
		self.assertNotIn(other[0], codes)
		self.assertEqual(codes, sorted(codes))
		self.assertEqual(set(codes), set(batch_codes(self.steam_item)) - {issued[1]})
		self.assertFalse(result["truncated"])

	def test_list_rolls_caps_the_list(self):
		call(codes_api.issue_rolls, item=self.steam_item, count=3)
		with patch.object(codes_api, "MAX_LIST_ROLLS", 2):
			result = read(codes_api.list_rolls, item=self.steam_item)
		self.assertEqual(len(result["codes"]), 2)
		self.assertTrue(result["truncated"])

	def test_list_rolls_requires_roles_first(self):
		audit_rows = frappe.db.count("Audit Log")
		for roles in (["TC R02"], ["TC R04"], []):
			with self.assertRaises(frappe.PermissionError, msg=roles):
				as_user(roles, codes_api.list_rolls, caller=read, item=self.steam_item)
		self.assertEqual(frappe.db.count("Audit Log"), audit_rows)
		for roles in (["TC R10"], ["System Manager"]):
			self.assertTrue(as_user(roles, codes_api.list_rolls, caller=read, item=self.steam_item)["ok"])

	def test_list_rolls_rejects_non_label_item(self):
		packaging = make_item("VT-BAO-GOI-LIST", "Packaging").name
		for item in (packaging, "KHONG-CO", None):
			result = read(codes_api.list_rolls, item=item)
			self.assertEqual(result["error"]["code"], "ROLL_NOT_LABEL", item)
			self.assertEqual(http_status(), 422)

	def test_list_rolls_is_whitelisted_read(self):
		self.assertEqual(frappe.get_attr("tracecore.v1.codes.list_rolls"), codes_api.list_rolls)
		self.assertIn("GET", frappe.allowed_http_methods_for_whitelisted_func[codes_api.list_rolls])


class TestJobStatus(ObjectLabelCase):
	"""`v1.print.job_status`: R10 theo dõi lệnh in đã gửi từ Desk (Đã in / Không in được / Đang chờ agent)."""

	def _job(self, printer):
		tag = uuid.uuid4().hex[:8]
		equipment = make_equipment(name=f"Máy theo dõi {tag}", serial=f"SN-JS-{tag}")
		result = call(print_api.object_label, label_object="Equipment", code=equipment.name, printer=printer)
		return str(result["print_job"])

	def test_job_status_reports_status_attempts_error_printed_at(self):
		from tracecore.core import print as core_print

		queued = self._job(self.host_printer)
		waiting = self._job(self.agent_printer)
		failed = self._job(self.host_printer)
		printed = self._job(self.host_printer)
		core_print.ack(failed, "Failed", "Printer", output_ref="10.0.0.50:9100", error="Máy in tắt")
		core_print.ack(printed, "Printed", "Printer", output_ref="10.0.0.50:9100")

		result = read(print_api.job_status, names=json.dumps([queued, waiting, failed, printed, "PJ-NONE"]))
		self.assertTrue(result["ok"], result)
		jobs = result["jobs"]
		self.assertEqual(set(jobs), {queued, waiting, failed, printed})  # tên không có: bỏ qua
		self.assertEqual(set(jobs[queued]), {"status", "attempts", "error", "printed_at"})
		self.assertEqual((jobs[queued]["status"], jobs[queued]["printed_at"]), ("Queued", None))
		self.assertEqual(jobs[waiting]["status"], "Waiting")
		self.assertEqual((jobs[failed]["status"], jobs[failed]["error"]), ("Failed", "Máy in tắt"))
		self.assertEqual(jobs[printed]["status"], "Printed")
		self.assertEqual(jobs[printed]["attempts"], 1)
		self.assertIsInstance(jobs[printed]["printed_at"], str)
		self.assertTrue(jobs[printed]["printed_at"])
		# danh sách Python, tên dạng số (Print Job tự tăng, JSON của Desk gửi số) cũng được
		self.assertEqual(read(print_api.job_status, names=[queued])["jobs"][queued]["status"], "Queued")
		self.assertEqual(read(print_api.job_status, names=[int(queued)])["jobs"][queued]["status"], "Queued")

	def test_job_status_requires_roles_first(self):
		job = self._job(self.host_printer)
		for roles in (["TC R02"], ["TC R04"], ["TC Agent"], []):
			with self.assertRaises(frappe.PermissionError, msg=roles):
				as_user(roles, print_api.job_status, caller=read, names=[job])
		for roles in (["TC R10"], ["System Manager"]):
			result = as_user(roles, print_api.job_status, caller=read, names=[job])
			self.assertEqual(result["jobs"][job]["status"], "Queued", roles)

	def test_job_status_bad_names_are_400(self):
		too_many = [f"PJ-{index}" for index in range(print_api.MAX_STATUS_JOBS + 1)]
		for names in (
			None,
			"",
			"not json",
			json.dumps({"a": 1}),
			[None],
			[True],
			[0],
			["  "],
			too_many,
			json.dumps(too_many),
		):
			with self.assertRaises(frappe.ValidationError, msg=names) as ctx:
				read(print_api.job_status, names=names)
			self.assertEqual(ctx.exception.http_status_code, 400, names)

	def test_job_status_is_whitelisted_read(self):
		self.assertEqual(frappe.get_attr("tracecore.v1.print.job_status"), print_api.job_status)
