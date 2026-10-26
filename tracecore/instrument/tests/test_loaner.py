"""Bộ mượn (FEAT-017, A-38; UC-04; FR-M1-05.5, FR-M1-07, FR-M1-08): nhận, tái xử lý, trả hãng, gia hạn, quá hạn."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import code_registry, step_gate
from tracecore.core.errors import BlockedError
from tracecore.instrument import loaner
from tracecore.tests import factories
from tracecore.tests.factories import (
	ALL_GATES,
	make_department,
	make_pack_type,
	make_supplier,
	make_user,
	next_free_test_gtin,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import loaner as api

test_ignore = ["Item", "Batch", "Department", "User", "Employee", "Supplier"]
DOCTYPE = "Loaner Set"
LINES = (("Kìm gặm xương Kerrison", 2), ("Mũi khoan 3 mm", 4))


def blocked(case, code, fn, *args, **kwargs):
	with case.assertRaises(BlockedError) as caught:
		fn(*args, **kwargs)
	case.assertEqual(caught.exception.block.code, code)


class LoanerCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r02 = make_user("ln-r02@example.com", ["TC R02"])
		self.r04 = make_user("ln-r04@example.com", ["TC R04"])
		self.supplier = make_supplier("Hãng mượn Medi")
		self.gtin = next_free_test_gtin()
		self.addCleanup(frappe.set_user, "Administrator")

	def draft(self, lines=LINES, gtin=None, **fields):
		values = {
			"doctype": DOCTYPE,
			"supplier": self.supplier,
			"set_name": "Bộ khoan cột sống",
			"method": "Steam",
			"gtin": gtin or self.gtin,
			"pack_type": make_pack_type(),
			"department": make_department(),
			"received_on": today(),
			"expected_return": add_days(today(), 7),
			"items": [{"instrument_name": name, "qty": qty} for name, qty in lines],
			**fields,
		}
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def received(self, **kwargs):
		doc = self.draft(**kwargs)
		frappe.set_user(self.r02)
		doc.submit()
		frappe.set_user("Administrator")
		return frappe.get_doc(DOCTYPE, doc.name)

	def sterile(self, doc):
		"""Bộ mượn qua đủ T1→T5 (Vô khuẩn) với gói của chu trình đang trong kho."""
		factories.make_cycle(doc.set_unit, passed=ALL_GATES)
		cycle_no = frappe.db.get_value("Set Unit", doc.set_unit, "current_cycle_no")
		pack = factories.make_pack(doc.set_unit, status="In Sterile Stock", cycle_no=cycle_no)
		code_registry.register(pack.name, code_registry.CYCLE_PREFIX, "Pack", pack.name)
		step_gate.bind_cycle(doc.set_unit, pack.name, None)
		self.assertEqual(frappe.db.get_value("Set Unit", doc.set_unit, "status"), "Sterile")
		return pack.name


class TestReceive(LoanerCase):
	def test_receive_creates_instruments_set_type_and_ln_set_id(self):
		doc = self.received()
		self.assertEqual(doc.status, "Received")
		unit = frappe.get_doc("Set Unit", doc.set_unit)
		self.assertTrue(unit.is_loaner)
		self.assertTrue(unit.name.startswith(f"{code_registry.company_prefix()}LN"), unit.name)
		self.assertEqual((unit.status, unit.set_type, unit.department), ("New", doc.set_type, doc.department))
		self.assertEqual(frappe.db.get_value("Code Registry", unit.name, "status"), "Active")
		set_type = frappe.get_doc("Instrument Set Type", doc.set_type)
		self.assertTrue(set_type.name.startswith("LN"))
		self.assertEqual((set_type.gtin, set_type.method), (self.gtin, "Steam"))
		for row in doc.items:
			self.assertTrue(row.instrument.startswith("LNI-"), row.instrument)
			instrument = frappe.get_doc("Instrument", row.instrument)
			self.assertEqual(instrument.instrument_name, row.instrument_name)
			self.assertEqual(instrument.manufacturer, self.supplier)
		bom = frappe.get_all(
			"Set BOM Item", filters={"set_type": doc.set_type, "bom_version": 1}, fields=["instrument", "qty"]
		)
		self.assertEqual(
			sorted((row.instrument, row.qty) for row in bom),
			sorted((row.instrument, row.qty) for row in doc.items),
		)

	def test_same_vendor_set_reuses_set_type_and_instruments(self):
		first = self.received()
		again = self.received()
		self.assertEqual(again.set_type, first.set_type)
		self.assertEqual([row.instrument for row in again.items], [row.instrument for row in first.items])
		self.assertNotEqual(again.set_unit, first.set_unit)
		self.assertEqual(frappe.db.get_value("Instrument Set Type", first.set_type, "current_bom_version"), 1)
		changed = self.received(lines=(("Kìm gặm xương Kerrison", 3), ("Mũi khoan 3 mm", 4)))
		self.assertEqual(changed.set_type, first.set_type)
		self.assertEqual(frappe.db.get_value("Instrument Set Type", first.set_type, "current_bom_version"), 2)

	def test_receive_rules(self):
		with self.assertRaises(frappe.ValidationError):
			self.draft(expected_return=add_days(today(), -1))
		with self.assertRaises(frappe.ValidationError):
			self.draft(lines=())
		with self.assertRaises(frappe.ValidationError):
			self.draft(lines=(("Kìm", 0),))
		doc = self.draft()
		frappe.set_user(self.r04)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(DOCTYPE, doc.name).submit()

	def test_service_fields_cannot_be_typed(self):
		doc = self.draft()
		doc.status = "Returned"
		doc.set_unit = None
		doc.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "status"), "Draft")

	def test_receipt_pdf_lists_set_id_and_bom(self):
		doc = self.received()
		html = frappe.get_print(DOCTYPE, doc.name, loaner.RECEIPT_FORMAT)
		for text in (doc.set_unit, doc.name, "Kìm gặm xương Kerrison", "Mũi khoan 3 mm"):
			self.assertIn(text, html)


class TestReprocessingGate(LoanerCase):
	def test_new_loaner_is_blocked_at_t4_until_washed_and_assembled(self):
		doc = self.received()
		block = step_gate.check(doc.set_unit, "T4")
		self.assertEqual(block.code, "STATUS_INVALID_FOR_STATION")
		self.assertIn(doc.set_unit, block.reason)
		factories.make_cycle(doc.set_unit, passed=("T1", "T2"))
		self.assertEqual(step_gate.check(doc.set_unit, "T4").code, "GATE_PREV_NOT_PASSED")
		factories.make_assembly_record(doc.set_unit)
		self.assertIsNone(step_gate.check(doc.set_unit, "T4"))


class TestReturn(LoanerCase):
	def lines(self, doc, *values):
		return [
			{"idx": row.idx, "returned_qty": returned, "damaged_qty": damaged, "note": note}
			for row, (returned, damaged, note) in zip(doc.items, values, strict=True)
		]

	def test_return_needs_full_reprocessing_after_last_use(self):
		doc = self.received()
		frappe.set_user(self.r02)
		blocked(
			self,
			"LOANER_NOT_REPROCESSED",
			loaner.return_set,
			doc.name,
			self.lines(doc, (2, 0, ""), (4, 0, "")),
		)

	@bru("BRU-ID-001")
	def test_return_lists_missing_and_damaged_and_ends_the_set_id(self):
		doc = self.received()
		pack = self.sterile(doc)
		frappe.set_user(self.r02)
		result = loaner.return_set(
			doc.name, self.lines(doc, (2, 1, "Mẻ lưỡi"), (3, 0, "Mất 1 mũi")), "Trả sau ca mổ"
		)
		frappe.set_user("Administrator")
		doc.reload()
		self.assertEqual((doc.status, doc.missing_count, doc.damaged_count), ("Returned", 1, 1))
		self.assertEqual(result["status"], "Returned")
		self.assertEqual(frappe.db.get_value("Set Unit", doc.set_unit, "status"), "Returned")
		self.assertEqual(frappe.db.get_value("Code Registry", doc.set_unit, "status"), "Disabled")
		row = frappe.db.get_value("Pack", pack, ["status", "void_reason"], as_dict=True)
		self.assertEqual((row.status, row.void_reason), ("Void", "Returned Unused"))
		self.assertEqual(frappe.db.get_value("Code Registry", pack, "status"), "Disabled")
		incident = frappe.get_doc("Incident CAPA", doc.incident)
		self.assertEqual((incident.incident_type, incident.set_unit), ("Missing Instrument", doc.set_unit))
		with self.assertRaises(frappe.ValidationError):
			step_gate.force_status(doc.set_unit, "Processing", "thử")
		frappe.set_user(self.r02)
		blocked(
			self, "LOANER_NOT_RECEIVED", loaner.return_set, doc.name, self.lines(doc, (2, 0, ""), (4, 0, ""))
		)
		frappe.set_user("Administrator")
		html = frappe.get_print(DOCTYPE, doc.name, loaner.RETURN_FORMAT)
		for text in (doc.set_unit, "Mất 1 mũi", "Mẻ lưỡi"):
			self.assertIn(text, html)

	def test_full_return_has_no_incident(self):
		doc = self.received()
		self.sterile(doc)
		frappe.set_user(self.r02)
		loaner.return_set(doc.name, self.lines(doc, (2, 0, ""), (4, 0, "")))
		self.assertFalse(frappe.db.get_value(DOCTYPE, doc.name, "incident"))

	def test_return_rules(self):
		doc = self.received()
		self.sterile(doc)
		frappe.set_user(self.r04)
		blocked(
			self, "LOANER_NOT_ALLOWED", loaner.return_set, doc.name, self.lines(doc, (2, 0, ""), (4, 0, ""))
		)
		frappe.set_user(self.r02)
		for values in (((3, 0, ""), (4, 0, "")), ((2, 3, ""), (4, 0, "")), ((-1, 0, ""), (4, 0, ""))):
			blocked(self, "LOANER_RETURN_QTY_INVALID", loaner.return_set, doc.name, self.lines(doc, *values))
		only_first = self.lines(doc, (2, 0, ""), (4, 0, ""))[:1]
		blocked(self, "LOANER_RETURN_QTY_INVALID", loaner.return_set, doc.name, only_first)
		self.assertEqual(frappe.db.get_value("Set Unit", doc.set_unit, "status"), "Sterile")


class TestExtendAndOverdue(LoanerCase):
	def test_extend_needs_reason_and_a_valid_date(self):
		doc = self.received()
		new_date = add_days(today(), 20)
		frappe.set_user(self.r02)
		blocked(self, "REASON_REQUIRED", loaner.extend, doc.name, new_date, " ")
		blocked(self, "LOANER_DATES_INVALID", loaner.extend, doc.name, add_days(today(), -3), "Ca mổ dời")
		loaner.extend(doc.name, new_date, "Ca mổ dời sang tuần sau")
		frappe.set_user("Administrator")
		self.assertEqual(
			getdate(frappe.db.get_value(DOCTYPE, doc.name, "expected_return")), getdate(new_date)
		)
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{"ref_doctype": DOCTYPE, "ref_name": doc.name, "reason": "Ca mổ dời sang tuần sau"},
			)
		)

	def test_overdue_loaner_reminds_r02_once_a_day(self):
		doc = self.received()
		frappe.db.set_value(DOCTYPE, doc.name, "expected_return", add_days(today(), -1))
		loaner.remind_overdue()
		filters = {"for_user": self.r02, "document_type": DOCTYPE, "document_name": doc.name}
		self.assertEqual(frappe.db.count("Notification Log", filters), 1)
		loaner.remind_overdue()
		self.assertEqual(frappe.db.count("Notification Log", filters), 1)


class TestLoanerApi(LoanerCase):
	def test_rpc_returns_blocks_as_body(self):
		doc = self.received()
		frappe.set_user(self.r02)
		lines = [{"idx": 1, "returned_qty": 2}, {"idx": 2, "returned_qty": 4}]
		result = api.return_set(doc.name, frappe.as_json(lines))
		self.assertEqual((result["ok"], result["error"]["code"]), (False, "LOANER_NOT_REPROCESSED"))
		result = api.extend(doc.name, add_days(today(), 9), "Gia hạn")
		self.assertTrue(result["ok"])

	def test_rpc_receive_submits_the_draft(self):
		doc = self.draft()
		frappe.set_user(self.r02)
		result = api.receive(doc.name)
		self.assertEqual((result["ok"], result["status"]), (True, "Received"))
		self.assertTrue(result["set_unit"])
