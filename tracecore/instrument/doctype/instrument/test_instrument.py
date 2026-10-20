import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.factories import make_instrument


def _audit_rows(name, action):
	return frappe.get_all(
		"Audit Log",
		filters={"ref_doctype": "Instrument", "ref_name": name, "action": action},
		fields=["new_value"],
	)


def _instrument_doc(code, **kwargs):
	return frappe.get_doc(
		{"doctype": "Instrument", "instrument_code": code, "instrument_name": "Test instrument", **kwargs}
	)


class TestInstrument(FrappeTestCase):
	def test_instrument_code_normalized(self):
		doc = _instrument_doc("kc-01").insert()
		self.assertEqual(doc.name, "KC-01")
		self.assertEqual(doc.instrument_code, "KC-01")
		self.assertTrue(frappe.db.exists("Instrument", "KC-01"))

		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC 01").insert()
		self.assertFalse(frappe.db.exists("Instrument", "KC 01"))

	def test_instrument_code_allows_only_letters_digits_hyphen(self):
		for bad in ("kc_01", "KC/01", "KC.01", "<KC>", "", "  "):
			with self.assertRaises(frappe.ValidationError, msg=repr(bad)):
				_instrument_doc(bad).insert()
		doc = _instrument_doc("  a1-b2-c3 ").insert()
		self.assertEqual(doc.name, "A1-B2-C3")

	def test_instrument_code_unique(self):
		make_instrument("KC-DUP")
		with self.assertRaises(frappe.DuplicateEntryError):
			_instrument_doc("kc-dup").insert()

	def test_maintenance_interval_not_negative_and_optional(self):
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-NEG", maint_interval_cycles=-1).insert()
		blank = _instrument_doc("KC-BLK").insert()
		self.assertFalse(blank.maint_interval_cycles)
		self.assertFalse(blank.maint_type)
		due = _instrument_doc(
			"KC-DUE", maint_interval_cycles=50, maint_type="Lubrication", max_cycles=500
		).insert()
		self.assertEqual(
			(due.maint_interval_cycles, due.maint_type, due.max_cycles), (50, "Lubrication", 500)
		)

	def test_maintenance_type_options(self):
		for index, maint_type in enumerate(
			("Lubrication", "Blade Check", "Screw Tightening", "Battery Replacement")
		):
			doc = _instrument_doc(f"KC-MT{index}", maint_interval_cycles=10, maint_type=maint_type).insert()
			self.assertEqual(doc.maint_type, maint_type)
		with self.assertRaises(frappe.ValidationError):
			_instrument_doc("KC-MTX", maint_interval_cycles=10, maint_type="Polishing").insert()

	def test_factory_returns_existing_instrument(self):
		first = make_instrument("KC-FAC", name="Kelly forceps", interval=40, maint_type="Screw Tightening")
		again = make_instrument("KC-FAC")
		self.assertEqual(first.name, again.name)
		self.assertEqual(
			(again.instrument_name, again.maint_interval_cycles, again.maint_type),
			("Kelly forceps", 40, "Screw Tightening"),
		)

	def test_create_writes_audit_log_and_delete_blocked(self):
		doc = make_instrument("KC-AUD", name="Audit scissors", image="/files/kc-aud.png")
		created = _audit_rows(doc.name, "Create")
		self.assertEqual(len(created), 1)
		self.assertEqual(frappe.parse_json(created[0].new_value)["image"], "/files/kc-aud.png")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Instrument", doc.name)
		self.assertTrue(frappe.db.exists("Instrument", doc.name))
