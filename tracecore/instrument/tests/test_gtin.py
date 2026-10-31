"""GTIN-14 của loại bộ (A-76): tự cấp, nhập tay, cấp bù có xem trước, khóa sau khi dùng và mở khóa của R10."""

import json

import frappe

from tracecore.core import code_registry, gs1
from tracecore.core.errors import BlockedError
from tracecore.instrument import gtin as gtin_rules
from tracecore.tests.factories import make_pack, make_set_type, make_set_unit, make_user
from tracecore.tests.utils import IsolatedTestCase

SETTINGS = "TraceCore Settings"
PREFIX = "8930001"
SET_TYPE = "Instrument Set Type"


def declare(prefix=PREFIX, indicator="0"):
	frappe.db.set_single_value(SETTINGS, "gs1_company_prefix", prefix)
	frappe.db.set_single_value(SETTINGS, "gtin_indicator_digit", indicator)


def gtin_of(name):
	return frappe.db.get_value(SET_TYPE, name, "gtin")


class GtinCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		declare("")
		self.r10 = make_user("gtin-r10@example.com", ["TC R10"])
		self.r02 = make_user("gtin-r02@example.com", ["TC R02"])

	def as_user(self, user):
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")

	def candidates(self):
		return {row["set_type"]: row for row in gtin_rules.backfill_preview()["rows"]}


class TestAutoIssue(GtinCase):
	def test_new_set_type_gets_valid_gtin_and_counter_moves(self):
		declare()
		before = code_registry.gtin_range()["next_ref"]
		name = make_set_type("GTA1", gtin=None).name
		gtin = gtin_of(name)
		self.assertTrue(gs1.is_valid_gtin14(gtin), msg=gtin)
		self.assertEqual(gtin[1:8], PREFIX)
		self.assertEqual(code_registry.gtin_range()["next_ref"], before + 1)

	def test_no_prefix_keeps_blank(self):
		self.assertIsNone(gtin_of(make_set_type("GTA2", gtin=None).name))

	def test_deleted_set_type_does_not_give_its_gtin_back(self):
		declare()
		doc = make_set_type("GTA3", gtin=None)
		gtin = gtin_of(doc.name)
		frappe.delete_doc(SET_TYPE, doc.name, force=True)
		self.assertTrue(code_registry.is_issued(gtin))
		self.assertNotEqual(gtin_of(make_set_type("GTA4", gtin=None).name), gtin)

	def test_loaner_set_type_keeps_vendor_gtin(self):
		declare()
		vendor = gs1.make_gtin14("0", "4012345", 11)
		before = code_registry.gtin_range()["next_ref"]
		name = make_set_type("LN00991", gtin=vendor).name
		self.assertEqual(gtin_of(name), vendor)
		self.assertEqual(code_registry.gtin_range()["next_ref"], before)
		self.assertNotIn(name, self.candidates())


class TestManualEntry(GtinCase):
	def test_bad_check_digit_blocked(self):
		declare()
		doc = make_set_type("GTM1", gtin=None)
		bad = doc.gtin[:13] + str((int(doc.gtin[13]) + 1) % 10)
		doc.gtin = bad
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_duplicate_blocked(self):
		first = make_set_type("GTM2", gtin=gs1.make_gtin14("0", PREFIX, 500))
		other = make_set_type("GTM3", gtin=None)
		other.gtin = first.gtin
		with self.assertRaises(frappe.ValidationError):
			other.save()

	def _warned(self, doc, gtin):
		frappe.clear_messages()
		doc.gtin = gtin
		doc.save()
		return any("does not start with" in str(item) for item in frappe.local.message_log)

	def test_warns_when_not_under_declared_prefix(self):
		declare()
		doc = make_set_type("GTM4", gtin=gs1.make_gtin14("0", PREFIX, 501))
		self.assertTrue(self._warned(doc, gs1.make_gtin14("0", "4012345", 12)))
		self.assertFalse(self._warned(doc, gs1.make_gtin14("3", PREFIX, 502)))

	def test_form_context_flags_foreign_prefix(self):
		declare()
		doc = make_set_type("GTM5", gtin=gs1.make_gtin14("0", "4012345", 15))
		self.assertTrue(gtin_rules.context(doc.name)["foreign_prefix"])

	def test_loaner_type_is_not_warned(self):
		declare()
		doc = make_set_type("LN00992", gtin=gs1.make_gtin14("0", "4012345", 13))
		self.assertFalse(self._warned(doc, gs1.make_gtin14("0", "4012345", 14)))


class TestBackfill(GtinCase):
	def setUp(self):
		super().setUp()
		declare()
		self.blank = make_set_type("GTB1", gtin=None)
		frappe.db.set_value(SET_TYPE, self.blank.name, "gtin", None)
		self.demo = make_set_type("GTB2", gtin="19520000000056")
		self.real = make_set_type("GTB3", gtin=gs1.make_gtin14("0", PREFIX, 600))

	def _commit(self, rows=None, reason=None):
		preview = gtin_rules.backfill_preview()
		names = [row["set_type"] for row in (rows or preview["rows"])]
		return gtin_rules.backfill(names, preview["next_ref"], reason)

	def test_preview_lists_blank_and_demo_only(self):
		rows = self.candidates()
		self.assertIn(self.blank.name, rows)
		self.assertIn(self.demo.name, rows)
		self.assertNotIn(self.real.name, rows)
		self.assertIsNone(rows[self.blank.name]["current_gtin"])
		self.assertTrue(rows[self.demo.name]["is_demo"])

	def test_preview_writes_nothing(self):
		before = code_registry.gtin_range()["next_ref"]
		self.candidates()
		self.assertEqual(code_registry.gtin_range()["next_ref"], before)
		self.assertIsNone(gtin_of(self.blank.name))

	def test_commit_matches_preview_and_all_valid_unique(self):
		rows = self.candidates()
		result = self._commit()
		self.assertEqual(result["issued"], len(rows))
		values = [gtin_of(name) for name in rows]
		self.assertEqual(len(set(values)), len(values))
		for name, row in rows.items():
			self.assertEqual(gtin_of(name), row["new_gtin"])
			self.assertTrue(gs1.is_valid_gtin14(gtin_of(name)))
		self.assertEqual(self.candidates(), {})

	def test_commit_writes_audit_with_old_and_new(self):
		self._commit()
		row = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": SET_TYPE, "ref_name": self.demo.name, "action": "Update"},
			fields=["old_value", "new_value"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual(json.loads(row.old_value)["gtin"], "19520000000056")
		self.assertEqual(json.loads(row.new_value)["gtin"], gtin_of(self.demo.name))

	def test_stale_preview_rejected(self):
		preview = gtin_rules.backfill_preview()
		names = [row["set_type"] for row in preview["rows"]]
		code_registry.next_gtin(SET_TYPE, "OTHER")
		with self.assertRaises(BlockedError) as caught:
			gtin_rules.backfill(names, preview["next_ref"], None)
		self.assertEqual(caught.exception.block.code, "GTIN_BACKFILL_STALE")
		self.assertIsNone(gtin_of(self.blank.name))

	def test_used_demo_needs_reason_and_pack_keeps_old_gtin(self):
		unit = make_set_unit(self.demo.name)
		pack = make_pack(unit, gtin=self.demo.gtin)
		self.assertEqual(self.candidates()[self.demo.name]["pack_count"], 1)
		self.assertTrue(gtin_rules.backfill_preview()["needs_reason"])
		with self.assertRaises(BlockedError) as caught:
			self._commit()
		self.assertEqual(caught.exception.block.code, "REASON_REQUIRED")
		self._commit(reason="Thay mã thử")
		self.assertNotEqual(gtin_of(self.demo.name), "19520000000056")
		self.assertEqual(frappe.db.get_value("Pack", pack.name, "gtin"), "19520000000056")

	def test_no_prefix_blocks_preview(self):
		declare("")
		with self.assertRaises(BlockedError) as caught:
			gtin_rules.backfill_preview()
		self.assertEqual(caught.exception.block.code, "GS1_PREFIX_NOT_DECLARED")

	def test_range_too_small_blocks_whole_backfill(self):
		declare("89300012345")
		frappe.db.sql(
			"insert into tabSeries (name, current) values (%s, 9)",
			code_registry.gtin_series_key("89300012345"),
		)
		with self.assertRaises(BlockedError) as caught:
			gtin_rules.backfill_preview()
		self.assertEqual(caught.exception.block.code, "GTIN_RANGE_EXHAUSTED")

	def test_only_r10_may_backfill(self):
		preview = gtin_rules.backfill_preview()
		self.as_user(self.r02)
		with self.assertRaises(frappe.PermissionError):
			gtin_rules.backfill_preview()
		with self.assertRaises(frappe.PermissionError):
			gtin_rules.backfill([row["set_type"] for row in preview["rows"]], preview["next_ref"], None)


class TestLockAfterUse(GtinCase):
	def setUp(self):
		super().setUp()
		declare()
		self.doc = make_set_type("GTL1", gtin=None)
		self.old = self.doc.gtin
		self.unit = make_set_unit(self.doc.name)
		make_pack(self.unit, gtin=self.old)
		self.new = gs1.make_gtin14("0", PREFIX, 700)

	def test_normal_save_blocked_for_everyone(self):
		doc = frappe.get_doc(SET_TYPE, self.doc.name)
		doc.gtin = self.new
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		self.assertEqual(gtin_of(self.doc.name), self.old)

	def test_unlock_requires_r10(self):
		self.as_user(self.r02)
		with self.assertRaises(frappe.PermissionError):
			gtin_rules.change_locked(self.doc.name, self.new, "Nhập sai")
		self.assertEqual(gtin_of(self.doc.name), self.old)

	def test_unlock_requires_reason(self):
		self.as_user(self.r10)
		with self.assertRaises(BlockedError) as caught:
			gtin_rules.change_locked(self.doc.name, self.new, "  ")
		self.assertEqual(caught.exception.block.code, "REASON_REQUIRED")

	def test_unlock_keeps_validation(self):
		self.as_user(self.r10)
		with self.assertRaises(frappe.ValidationError):
			gtin_rules.change_locked(
				self.doc.name, self.new[:13] + str((int(self.new[13]) + 1) % 10), "Nhập sai"
			)
		with self.assertRaises(frappe.ValidationError):
			gtin_rules.change_locked(self.doc.name, "", "Nhập sai")

	def test_unlock_changes_gtin_logs_reason_and_retires_old(self):
		self.as_user(self.r10)
		gtin_rules.change_locked(self.doc.name, self.new, "Nhập sai khi khai báo")
		self.assertEqual(gtin_of(self.doc.name), self.new)
		frappe.set_user("Administrator")
		log = frappe.get_all(
			"Audit Log",
			filters={"ref_doctype": SET_TYPE, "ref_name": self.doc.name, "action": "Update"},
			fields=["reason", "user", "old_value", "new_value"],
			order_by="creation desc",
			limit=1,
		)[0]
		self.assertEqual((log.reason, log.user), ("Nhập sai khi khai báo", self.r10))
		self.assertEqual(json.loads(log.old_value)["gtin"], self.old)
		self.assertEqual(json.loads(log.new_value)["gtin"], self.new)
		# mã trên nhãn cũ không cấp lại cho loại bộ khác
		other = make_set_type("GTL2", gtin=gs1.make_gtin14("0", PREFIX, 701))
		other.gtin = self.old
		with self.assertRaises(frappe.ValidationError):
			other.save()

	def test_unlock_of_unused_gtin_rejected(self):
		free = make_set_type("GTL3", gtin=None)
		with self.assertRaises(BlockedError) as caught:
			gtin_rules.change_locked(free.name, self.new, "Nhập sai")
		self.assertEqual(caught.exception.block.code, "GTIN_NOT_LOCKED")

	def test_context_reports_lock(self):
		self.as_user(self.r10)
		state = gtin_rules.context(self.doc.name)
		self.assertTrue(state["locked"])
		self.assertTrue(state["can_unlock"])
		self.assertEqual(state["pack_count"], 1)
		self.assertEqual(state["prefix"], PREFIX)
		self.as_user(self.r02)
		self.assertFalse(gtin_rules.context(self.doc.name)["can_unlock"])
