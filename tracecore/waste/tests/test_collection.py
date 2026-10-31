"""Thu gom chất thải theo khoa (FEAT-047, UC-34, FR-M10-02, .1, .3-.6, FR-M10-01.5, BRU-WST-001, BRU-WST-002, BRU-ID-006)."""

import frappe
from frappe.utils import add_to_date, get_datetime

from tracecore.core.errors import BlockedError
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_waste_station,
	make_waste_type,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.waste import collection

CARD = "WASTE-GIVER-CARD"


class WasteCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.station = make_waste_station()
		self.department = make_department("Khoa Ngoai Waste")
		self.giver = make_employee(card=CARD, department=self.department, first_name="Giao").name
		self.collector = make_employee(first_name="Thu gom").name
		self.waste = make_waste_type(std_weight_kg=2).name

	def record(self, lines=None, card=CARD, **kwargs):
		lines = lines if lines is not None else [self.line()]
		return collection.record(self.station, self.collector, card, lines, **kwargs)

	def line(self, **kwargs):
		return {
			"waste_type": self.waste,
			"qty": 2,
			"weight_kg": 5,
			"weight_source": "Scale",
			**kwargs,
		}

	def containers(self, doc):
		return frappe.get_all(
			"Waste Container",
			filters={"collection": doc.name},
			fields=["name", "status", "weight_kg", "waste_type", "department", "collected_at", "storage_due"],
			order_by="name asc",
		)

	def assert_blocked(self, code, **kwargs):
		with self.assertRaises(BlockedError) as ctx:
			self.record(**kwargs)
		self.assertEqual(ctx.exception.block.code, code)


class TestRecord(WasteCase):
	def test_submits_collection_with_giver_department_and_collector(self):
		doc = self.record()
		self.assertEqual(doc.docstatus, 1)
		self.assertRegex(doc.name, r"^TG-\d{4}-\d{5}$")
		self.assertEqual(
			(doc.delivered_by, doc.department, doc.collected_by, doc.station),
			(self.giver, self.department, self.collector, self.station),
		)
		self.assertEqual((doc.total_containers, doc.total_weight_kg), (2, 5))

	@bru("BRU-ID-006")
	def test_each_bag_gets_a_system_code(self):
		rows = self.containers(self.record())
		self.assertEqual(len(rows), 2)
		for row in rows:
			self.assertRegex(row.name, r"^CT-\d{6}-\d{5}$")
			self.assertEqual(row.status, "Collected")
			self.assertEqual(row.department, self.department)
		self.assertEqual(sum(row.weight_kg for row in rows), 5)

	def test_weight_is_split_and_remainder_goes_to_last_bag(self):
		rows = self.containers(self.record([self.line(qty=3, weight_kg=1)]))
		self.assertEqual([row.weight_kg for row in rows], [0.333, 0.333, 0.334])

	@bru("BRU-WST-002")
	def test_storage_time_starts_at_collection(self):
		doc = self.record()
		for row in self.containers(doc):
			self.assertEqual(get_datetime(row.collected_at), get_datetime(doc.collected_at))
			self.assertEqual(
				get_datetime(row.storage_due), add_to_date(get_datetime(doc.collected_at), hours=48)
			)

	def test_container_cannot_be_created_by_hand(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Waste Container", "waste_type": self.waste, "weight_kg": 1}).insert(
				ignore_permissions=True
			)

	@bru("BRU-WST-001")
	def test_each_line_has_exactly_one_type(self):
		self.assert_blocked("WASTE_TYPE_INVALID", lines=[self.line(waste_type=None)])
		self.assert_blocked("WASTE_TYPE_INVALID", lines=[self.line(waste_type=[self.waste, self.waste])])

	def test_several_types_on_one_collection(self):
		other = make_waste_type(waste_group="General").name
		doc = self.record([self.line(), self.line(waste_type=other, qty=1, weight_kg=3)])
		self.assertEqual((doc.total_containers, doc.total_weight_kg), (3, 8))
		self.assertEqual(len({row.waste_type for row in self.containers(doc)}), 2)

	def test_inactive_type_is_refused(self):
		frappe.db.set_value("Waste Type", self.waste, "is_active", 0)
		self.assert_blocked("WASTE_TYPE_INVALID")

	def test_empty_and_bad_quantities_are_refused(self):
		self.assert_blocked("WASTE_EMPTY", lines=[])
		for qty in (0, -1, 1.5, "x", None):
			with self.subTest(qty=qty):
				self.assert_blocked("WASTE_QTY_INVALID", lines=[self.line(qty=qty)])
		self.assert_blocked("WASTE_QTY_INVALID", lines=[self.line(weight_kg=-2)])

	def test_missing_weight_is_converted_from_standard_bag(self):
		doc = self.record([self.line(weight_kg=None, weight_source=None)])
		self.assertEqual((doc.lines[0].weight_kg, doc.lines[0].weight_source), (4, "Converted"))

	def test_manual_weight_needs_confirmation_on_the_server(self):
		"""FR-M10-02.1: cân lỗi thì nhập tay, bắt buộc xác nhận và ghi nguồn."""
		self.assert_blocked("WASTE_WEIGHT_UNCONFIRMED", lines=[self.line(weight_source="Manual")])
		self.assert_blocked("WASTE_WEIGHT_UNCONFIRMED", lines=[self.line(weight_source="Bogus")])
		doc = self.record([self.line(weight_source="Manual", weight_confirmed=1)])
		self.assertEqual((doc.lines[0].weight_source, doc.lines[0].weight_confirmed), ("Manual", 1))

	def test_total_weight_is_allocated_by_standard_weight(self):
		"""UC-34 A2: chỉ có cân tổng của xe."""
		other = make_waste_type(std_weight_kg=1).name
		doc = self.record([{"waste_type": self.waste, "qty": 1}, {"waste_type": other, "qty": 2}], total_kg=8)
		self.assertEqual([row.weight_kg for row in doc.lines], [4, 4])
		self.assertEqual({row.weight_source for row in doc.lines}, {"Converted"})
		self.assert_blocked("WASTE_TOTAL_INVALID", total_kg=-1)


class TestGiver(WasteCase):
	def test_unknown_or_disabled_card_is_refused(self):
		self.assert_blocked("WASTE_GIVER_INVALID", card="NOPE")
		self.assert_blocked("WASTE_GIVER_INVALID", card=None)
		frappe.db.set_value("Employee", self.giver, "tc_card_enabled", 0)
		self.assert_blocked("WASTE_GIVER_INVALID")

	def test_giver_must_belong_to_a_ward(self):
		frappe.db.set_value("Employee", self.giver, "department", None)
		self.assert_blocked("WASTE_GIVER_INVALID")
		frappe.db.set_value("Employee", self.giver, "department", self.department)
		frappe.db.set_value("Department", self.department, "tc_is_ward", 0)
		self.assert_blocked("WASTE_GIVER_INVALID")

	def test_giver_lookup_returns_name_and_department(self):
		self.assertEqual(
			collection.giver(CARD),
			{
				"employee": self.giver,
				"employee_name": frappe.db.get_value("Employee", self.giver, "employee_name"),
				"department": self.department,
			},
		)


class TestMisclassified(WasteCase):
	def bad_line(self, **kwargs):
		return self.line(misclassified=1, misclass_note="Sharps outside the box", **kwargs)

	@bru("BRU-WST-001")
	def test_bags_are_held_and_not_counted_and_nc_is_created(self):
		doc = self.record([self.line(), self.bad_line(qty=1, weight_kg=3)])
		self.assertEqual((doc.total_containers, doc.total_weight_kg, doc.held_kg), (3, 5, 3))
		rows = self.containers(doc)
		held = [row for row in rows if row.status == "Held"]
		self.assertEqual(len(held), 1)
		nc = frappe.get_all(
			"Incident CAPA",
			filters={"source_doctype": "Waste Container", "source_name": held[0].name},
			fields=["incident_type", "employee"],
		)
		self.assertEqual(
			[(row.incident_type, row.employee) for row in nc], [("Waste Misclassification", self.giver)]
		)

	def test_note_is_required(self):
		self.assert_blocked("WASTE_NOTE_REQUIRED", lines=[self.line(misclassified=1)])

	def test_release_counts_the_bag_once(self):
		doc = self.record([self.bad_line(qty=1, weight_kg=3)])
		name = self.containers(doc)[0].name
		collection.release_held(name, "Re-sorted by the ward", "r02@example.com")
		doc.reload()
		self.assertEqual((doc.total_weight_kg, doc.held_kg), (3, 0))
		row = frappe.db.get_value(
			"Waste Container", name, ["status", "released_by", "release_note"], as_dict=True
		)
		self.assertEqual(
			(row.status, row.released_by, row.release_note),
			("Collected", "r02@example.com", "Re-sorted by the ward"),
		)
		with self.assertRaises(BlockedError) as ctx:
			collection.release_held(name, "Again", "r02@example.com")
		self.assertEqual(ctx.exception.block.code, "WASTE_NOT_HELD")

	def test_release_needs_a_note(self):
		doc = self.record([self.bad_line(qty=1, weight_kg=3)])
		with self.assertRaises(BlockedError) as ctx:
			collection.release_held(self.containers(doc)[0].name, " ", "r02@example.com")
		self.assertEqual(ctx.exception.block.code, "WASTE_NOTE_REQUIRED")


class TestReceiptAndCancel(WasteCase):
	def test_acknowledge_by_rescanning_the_giver_card(self):
		doc = self.record()
		collection.acknowledge(doc.name, CARD)
		doc.reload()
		self.assertEqual(doc.acknowledged_by, self.giver)
		self.assertTrue(doc.acknowledged_at)

	def test_colleague_of_the_same_ward_may_acknowledge_but_not_others(self):
		doc = self.record()
		make_employee(card="WASTE-COLLEAGUE", department=self.department, first_name="Cung khoa")
		other = make_department("Khoa Khac Waste")
		make_employee(card="WASTE-OTHER", department=other, first_name="Khac khoa")
		with self.assertRaises(BlockedError) as ctx:
			collection.acknowledge(doc.name, "WASTE-OTHER")
		self.assertEqual(ctx.exception.block.code, "WASTE_GIVER_INVALID")
		collection.acknowledge(doc.name, "WASTE-COLLEAGUE")

	def test_cancel_retires_the_bags_and_cannot_be_deleted(self):
		doc = self.record()
		doc.cancel()
		self.assertEqual({row.status for row in self.containers(doc)}, {"Cancelled"})
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Waste Collection", doc.name, ignore_permissions=True)


class TestLabels(WasteCase):
	def jobs(self, doc):
		names = [row.name for row in self.containers(doc)]
		return frappe.get_all(
			"Print Job",
			filters={"ref_doctype": "Waste Container", "ref_name": ["in", names]},
			fields=["status", "station"],
		)

	def test_no_printer_keeps_collection_and_waits_with_warning(self):
		doc = self.record()
		rows = self.jobs(doc)
		self.assertEqual([row.status for row in rows], ["Waiting", "Waiting"])
		self.assertEqual(collection.labels_of(doc)["warning"]["code"], "NO_PRINTER_AT_STATION")

	def test_label_goes_to_another_waste_station_printer(self):
		"""W1: PDA không có máy in thì đẩy lệnh sang trạm WST có máy in."""
		other = "TR-WST2"
		zone = frappe.db.get_value("Zone Station", self.station, "parent_zone")
		frappe.get_doc(
			{
				"doctype": "Zone Station",
				"is_zone": 0,
				"is_active": 1,
				"zone_station_name": "Waste printer",
				"parent_zone": zone,
				"functions": [{"station_function": "WASTE"}],
			}
		).insert(ignore_permissions=True, set_name=other)
		from unittest.mock import patch

		printers = {other: {"name": "PR-1"}}
		with (
			patch("tracecore.core.print.object_printer", side_effect=printers.get),
			patch("tracecore.core.print.render_object", return_value=("^XA^XZ", frappe._dict(name="T"))),
			patch("tracecore.core.print.create_job", return_value="JOB") as job,
		):
			self.record()
		self.assertEqual({call.kwargs["station"] for call in job.call_args_list}, {other})
		self.assertEqual({call.kwargs["status"] for call in job.call_args_list}, {"Queued"})
