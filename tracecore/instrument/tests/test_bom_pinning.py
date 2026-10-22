"""Bộ giữa chu trình giữ phiên bản BOM đã ghim (FEAT-015 Task 3; FR-M1-04.1, FR-M1-04.2; AC-9, AC-10; S3).

``core.step_gate.start_cycle`` ghi ``Set Unit.cycle_bom_version`` qua hook ``tracecore_cycle_bom_version``
(``bom_versions.pin_cycle_version``); T4 (``bom.pack_context``), nhắc bảo dưỡng và ``init_counter`` đọc
``bom_versions.version_for_set_unit``. Review Focus 2.
"""

import subprocess  # nosec B404 - chỉ chạy script lint của chính repo
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, nowdate

from tracecore.core import step_gate
from tracecore.core.errors import BlockedError
from tracecore.instrument import bom, bom_versions, maintenance
from tracecore.patches.v0_1 import pin_cycle_bom_version
from tracecore.reprocessing import packing
from tracecore.tests.factories import (
	make_bom,
	make_instrument,
	make_maintenance,
	make_set_type,
	make_set_unit,
	make_t4_ready_set,
)
from tracecore.tests.utils import IsolatedTestCase

# Set Unit (→ Department), Instrument Set Type (→ Department, Item), Set BOM Item/Instrument (→ Item);
# CI tạo site mới chưa chạy Setup Wizard nên bỏ phụ thuộc ERPNext/HRMS (dữ liệu tạo qua factories)
test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION = "TR-004"
HOOK = "tracecore_cycle_bom_version"
APP_ROOT = Path(__file__).resolve().parents[3]


def _pinned(set_unit):
	return frappe.db.get_value("Set Unit", getattr(set_unit, "name", set_unit), "cycle_bom_version")


def _tomorrow():
	return getdate(add_days(nowdate(), 1))


def _ctx(set_unit, set_type):
	"""Ngữ cảnh hook T4 như ``packing._open`` dựng (``ctx["set_unit"]`` không có ``cycle_bom_version``)."""
	return {
		"set_unit": {"name": set_unit.name, "set_type": set_type.name, "current_cycle_no": 1},
		"set_type": {
			"name": set_type.name,
			"tray_image": set_type.tray_image,
			"current_bom_version": frappe.db.get_value(
				"Instrument Set Type", set_type.name, "current_bom_version"
			),
		},
		"station": "T4",
		"maint_actions": [],
	}


class TestBomPinning(IsolatedTestCase):
	def test_start_cycle_pins_effective_version(self):
		set_type = make_set_type("PNA", bom=[("PN-A1", 1)])
		make_bom(set_type, [("PN-A1", 1), ("PN-A2", 1)], version=2)  # hiệu lực hôm nay → áp dụng ngay
		unit = make_set_unit(set_type.name)
		self.assertEqual(_pinned(unit), 0)  # chưa có chu trình: chưa ghim

		step_gate.start_cycle(unit.name)
		self.assertEqual(_pinned(unit), 2)

		# v3 lên lịch ngày mai: chu trình bắt đầu hôm nay vẫn ghim v2; tiếp nhận ngày mai ghim v3
		make_bom(set_type, [("PN-A2", 1)], version=3, effective_from=_tomorrow())
		step_gate.start_cycle(unit.name)
		self.assertEqual(_pinned(unit), 2)
		step_gate.start_cycle(unit.name, on=_tomorrow())
		self.assertEqual(_pinned(unit), 3)
		# datetime cũng nhận (lấy ngày)
		step_gate.start_cycle(unit.name, on=datetime.combine(_tomorrow(), datetime.min.time()))
		self.assertEqual(_pinned(unit), 3)

	def test_pin_cycle_version_and_version_for_set_unit(self):
		set_type = make_set_type("PNB", bom=[("PN-B1", 1)])
		unit = make_set_unit(set_type.name)
		self.assertEqual(
			bom_versions.pin_cycle_version(
				{"set_unit": unit.name, "set_type": set_type.name, "cycle_no": 1, "on": nowdate()}
			),
			1,
		)
		yesterday = add_days(nowdate(), -1)
		self.assertIsNone(
			bom_versions.pin_cycle_version(
				{"set_unit": unit.name, "set_type": set_type.name, "cycle_no": 1, "on": yesterday}
			)
		)
		self.assertEqual(bom_versions.version_for_set_unit(unit.name), 1)
		self.assertEqual(bom_versions.version_for_set_unit({"name": unit.name}), 1)
		self.assertIsNone(bom_versions.version_for_set_unit("SU-NOT-THERE"))

	def test_in_flight_set_keeps_pinned_version_at_t4(self):
		ready = make_t4_ready_set(bom=(("PN-T1", 2), ("PN-T2", 1)))  # chu trình 1 mở khi v1 hiệu lực
		self.assertEqual(_pinned(ready.set_id), 1)
		make_bom(ready.set_type, [("PN-T3", 1)], version=2)  # v2 hiệu lực hôm nay khi bộ đang giữa chu trình
		self.assertEqual(bom_versions.effective_version(ready.set_type), 2)

		context = packing.get_context(ready.set_id, STATION)
		self.assertEqual(context["bom_version"], 1)
		self.assertEqual([(r["instrument"], r["qty"]) for r in context["bom"]], [("PN-T1", 2), ("PN-T2", 1)])

		result = packing.generate(
			set_id=ready.set_id,
			station=STATION,
			confirmed=["PN-T1", "PN-T2"],
			ci_batch=ready.ci_batch,
			pack_type=ready.pack_type,
			maint_actions=[],
			client_ts=datetime.now(timezone.utc).replace(tzinfo=None),
		)
		self.assertEqual(frappe.db.get_value("Pack", result["pack"]["cycle_id"], "bom_version"), 1)

		# chu trình kế tiếp (lần tiếp nhận sau) dùng phiên bản mới
		step_gate.start_cycle(ready.set_id)
		self.assertEqual(_pinned(ready.set_id), 2)
		unit = frappe.get_doc("Set Unit", ready.set_id)
		set_type = frappe.get_doc("Instrument Set Type", ready.set_type)
		self.assertEqual(bom.pack_context(_ctx(unit, set_type))["bom_version"], 2)

	def test_maintenance_reminders_follow_pinned_version(self):
		make_instrument("PN-M1", interval=5)
		make_instrument("PN-M2", interval=5)
		set_type = make_set_type("PNM", bom=[("PN-M1", 1)])
		unit = make_set_unit(set_type.name)
		make_maintenance(unit, "PN-M1", cycles_since=5)
		make_maintenance(unit, "PN-M2", cycles_since=5)
		step_gate.start_cycle(unit.name)  # ghim v1
		make_bom(set_type, [("PN-M2", 1)], version=2)  # v2 hiệu lực hôm nay chỉ có PN-M2

		ctx = _ctx(unit, set_type)
		self.assertEqual([i["instrument"] for i in maintenance.pack_context(ctx)["maintenance"]], ["PN-M1"])

		# init_counter theo phiên bản ghim: PN-M1 (v1) nhận, PN-M2 (chỉ ở v2) không
		maintenance.init_counter(unit.name, "PN-M1", 2, None, "Sổ giấy")
		with self.assertRaises(BlockedError) as raised:
			maintenance.init_counter(unit.name, "PN-M2", 2, None, "Sổ giấy")
		self.assertEqual(raised.exception.block.code, "COUNTER_INIT_INVALID")

		# form dụng cụ: khả năng khởi tạo theo cùng phiên bản ghim
		can_init = {
			r["set_unit"]: r["can_init"] for r in maintenance.instrument_counters("PN-M1", {"interval": 5})
		}
		self.assertTrue(can_init[unit.name])
		can_init = {
			r["set_unit"]: r["can_init"] for r in maintenance.instrument_counters("PN-M2", {"interval": 5})
		}
		self.assertFalse(can_init[unit.name])

		# giải phóng thiếu bom_version: đếm theo phiên bản ghim
		maintenance.on_set_released({"set_unit": unit.name, "set_type": set_type.name, "cycle_id": "CY-PN-1"})
		counters = dict(
			frappe.get_all(
				"Instrument Maintenance",
				filters={"set_unit": unit.name},
				fields=["instrument", "cycles_since_maint"],
				as_list=True,
			)
		)
		self.assertEqual(counters, {"PN-M1": 3, "PN-M2": 5})

		# chu trình kế tiếp ghim v2 → nhắc PN-M2
		step_gate.start_cycle(unit.name)
		self.assertEqual([i["instrument"] for i in maintenance.pack_context(ctx)["maintenance"]], ["PN-M2"])

	def test_unpinned_set_uses_effective_version(self):
		make_instrument("PN-U1", interval=5)
		make_instrument("PN-U2", interval=5)
		set_type = make_set_type("PNU", bom=[("PN-U1", 1)])
		unit = make_set_unit(set_type.name)  # bộ cũ, chưa có chu trình nào → không ghim
		make_maintenance(unit, "PN-U1", cycles_since=5)
		make_maintenance(unit, "PN-U2", cycles_since=5)
		make_bom(set_type, [("PN-U2", 1)], version=2)
		make_bom(set_type, [("PN-U1", 1)], version=3, effective_from=_tomorrow())

		self.assertEqual(_pinned(unit), 0)
		self.assertEqual(bom_versions.version_for_set_unit(unit.name), 2)
		ctx = _ctx(unit, set_type)
		self.assertEqual(bom.pack_context(ctx)["bom_version"], 2)
		self.assertEqual([i["instrument"] for i in maintenance.pack_context(ctx)["maintenance"]], ["PN-U2"])

		# loại bộ cũ chưa có dòng BOM nào: như FEAT-018, dùng phiên bản hiện hành của loại bộ
		legacy = make_set_type("PNL")
		legacy_unit = make_set_unit(legacy.name)
		self.assertEqual(bom_versions.version_for_set_unit(legacy_unit.name), 1)
		step_gate.start_cycle(legacy_unit.name)
		self.assertEqual(_pinned(legacy_unit), 0)
		self.assertEqual(bom.pack_context(_ctx(legacy_unit, legacy))["bom_version"], 1)

	def test_cycle_bom_version_written_only_by_step_gate(self):
		set_type = make_set_type("PNS", bom=[("PN-S1", 1)])
		unit = make_set_unit(set_type.name, cycle_bom_version=5)
		self.assertEqual(_pinned(unit), 0)  # tạo mới: giá trị nhập tay bị bỏ như các trường vòng đời khác
		step_gate.start_cycle(unit.name)

		doc = frappe.get_doc("Set Unit", unit.name)
		doc.cycle_bom_version = 7
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(_pinned(unit), 1)
		self.assertTrue(frappe.get_meta("Set Unit").get_field("cycle_bom_version").read_only)

		lint = subprocess.run(  # nosec B603 - đối số cố định
			[sys.executable, str(APP_ROOT / "scripts" / "check_architecture.py")],
			cwd=APP_ROOT,
			capture_output=True,
			text=True,
			check=False,
		)
		self.assertEqual(lint.returncode, 0, lint.stdout + lint.stderr)

	def test_pack_context_returns_tray_images_and_keeps_tray_image(self):
		set_type = make_set_type("PNI", bom=[("PN-I1", 1)], tray_image="/private/files/pni-1.jpg")
		frappe.db.set_value(
			"Instrument Set Type",
			set_type.name,
			{"tray_image_3": "/private/files/pni-3.jpg"},
			update_modified=False,
		)
		set_type.reload()
		unit = make_set_unit(set_type.name)

		result = bom.pack_context(_ctx(unit, set_type))
		self.assertEqual(set(result), {"bom", "bom_version", "tray_image", "tray_images"})
		self.assertEqual(result["tray_image"], "/private/files/pni-1.jpg")
		self.assertEqual(result["tray_images"], ["/private/files/pni-1.jpg", "/private/files/pni-3.jpg"])

		bare = make_set_type("PNJ", bom=[("PN-I1", 1)])
		bare_result = bom.pack_context(_ctx(make_set_unit(bare.name), bare))
		self.assertEqual((bare_result["tray_image"], bare_result["tray_images"]), (None, []))

	def test_patch_pins_running_cycles(self):
		set_type = make_set_type("PNP", bom=[("PN-P1", 1)])
		running, fresh, pinned = (make_set_unit(set_type.name) for _i in range(3))
		# dữ liệu có trước FEAT-015: bộ đang ở chu trình 3, chưa có trường ghim
		frappe.db.set_value("Set Unit", running.name, {"current_cycle_no": 3, "cycle_bom_version": 0})
		frappe.db.set_value("Set Unit", pinned.name, {"current_cycle_no": 2, "cycle_bom_version": 1})
		make_bom(set_type, [("PN-P2", 1)], version=2)  # current_bom_version của loại bộ → 2

		with patch("builtins.print"):
			pin_cycle_bom_version.execute()
		self.assertEqual(_pinned(running), 2)
		self.assertEqual(_pinned(fresh), 0)  # chưa có chu trình: không ghim
		self.assertEqual(_pinned(pinned), 1)  # đã ghim: giữ nguyên
		audit = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": "Set Unit", "ref_name": running.name, "action": "Update"},
			fields=["new_value"],
		)
		self.assertIn({"cycle_bom_version": 2}, [frappe.parse_json(row.new_value) for row in audit])

		# chạy lại không đổi gì
		count = frappe.db.count("Audit Log", {"ref_doctype": "Set Unit", "action": "Update"})
		with patch("builtins.print"):
			pin_cycle_bom_version.execute()
		self.assertEqual(frappe.db.count("Audit Log", {"ref_doctype": "Set Unit", "action": "Update"}), count)
		self.assertEqual(_pinned(running), 2)

	def test_start_cycle_without_hook_keeps_zero(self):
		set_type = make_set_type("PNH", bom=[("PN-H1", 1)])
		unit = make_set_unit(set_type.name)
		real_get_hooks = frappe.get_hooks

		def without_pin(hook=None, *args, **kwargs):
			if hook == HOOK:
				return []
			return real_get_hooks(hook, *args, **kwargs)

		self.assertIn("tracecore.instrument.bom_versions.pin_cycle_version", real_get_hooks(HOOK))
		with patch.object(frappe, "get_hooks", side_effect=without_pin):
			self.assertEqual(step_gate.start_cycle(unit.name), 1)
		self.assertEqual(_pinned(unit), 0)
		self.assertEqual(frappe.db.get_value("Set Unit", unit.name, "status"), "Processing")
