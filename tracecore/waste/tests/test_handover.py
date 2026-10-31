"""Đơn vị xử lý và phiếu bàn giao chất thải (FEAT-049, UC-36, FR-M10-03.5, FR-M10-04, FR-M10-05, BRU-WST-003, BRU-WST-004, A-62)."""

import frappe
from frappe.utils import add_days, add_to_date, flt, today

from tracecore.core import notification
from tracecore.core.errors import BlockedError
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_user,
	make_waste_location,
	make_waste_station,
	make_waste_type,
	make_waste_vendor,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.waste import collection, handover, storage, vendors

CARD = "WASTE-HAND-CARD"
CARD_2 = "WASTE-HAND-CARD-2"
SIGNATURE = "data:image/png;base64,iVBORw0KGgo="


class HandoverCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		self.station = make_waste_station()
		self.department = make_department("Khoa Ban Giao A")
		self.department_2 = make_department("Khoa Ban Giao B")
		make_employee(card=CARD, department=self.department, first_name="Giao A")
		make_employee(card=CARD_2, department=self.department_2, first_name="Giao B")
		self.employee = make_employee(first_name="Kho").name
		self.waste = make_waste_type(waste_group="Sharp Infectious").name
		self.general = make_waste_type(waste_group="General").name
		self.location = make_waste_location([self.waste, self.general])
		self.vendor = make_waste_vendor([self.waste, self.general], rate=1000)

	def bags(self, qty=1, weight=1, waste=None, card=CARD):
		doc = collection.record(
			self.station,
			self.employee,
			card,
			[{"waste_type": waste or self.waste, "qty": qty, "weight_kg": weight, "weight_source": "Scale"}],
		)
		names = frappe.get_all(
			"Waste Container", filters={"collection": doc.name}, pluck="name", order_by="name"
		)
		for name in names:
			storage.store(name, self.location)
		return names

	def draft(self, *bags, vendor=None):
		doc = handover.create(self.station, self.employee, vendor or self.vendor)
		for bag in bags:
			handover.add(doc.name, bag)
		return frappe.get_doc("Waste Handover", doc.name)

	def fill(self, doc, kg=None, **kwargs):
		values = {
			"weights": [
				{
					"waste_type": row.waste_type,
					"handover_kg": kg if kg is not None else row.collected_kg,
					"weight_source": "Scale",
				}
				for row in doc.lines
			],
			"vendor_signer": "Nguyen Van A",
			"vendor_signature": SIGNATURE,
			"hazard_document_no": "CTNH-1",
			"transporter": "Xe A",
			"contract_no": "HD-1",
			"hazard_document_scan": "/files/ctnh.pdf",
			**kwargs,
		}
		return handover.sign(doc.name, self.employee, **values)

	def assert_blocked(self, code, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as ctx:
			fn(*args, **kwargs)
		self.assertEqual(ctx.exception.block.code, code)
		return ctx.exception.block

	def post(self, *bags, **kwargs):
		doc = self.draft(*bags)
		self.fill(doc, **kwargs)
		return handover.submit(doc.name)


class TestVendor(HandoverCase):
	def test_active_vendor_is_listed_with_its_types(self):
		row = next(row for row in vendors.selectable() if row["name"] == self.vendor)
		self.assertEqual(sorted(row["waste_types"]), sorted([self.waste, self.general]))

	def test_vendor_needs_license_and_types(self):
		with self.assertRaises(frappe.ValidationError):
			make_waste_vendor([])
		with self.assertRaises(frappe.ValidationError):
			make_waste_vendor([self.waste], license_no="")

	def test_expired_license_turns_vendor_expired_and_hides_it(self):
		vendor = make_waste_vendor([self.waste], license_valid_to=add_days(today(), 1))
		frappe.db.set_value("Waste Treatment Vendor", vendor, "license_valid_to", add_days(today(), -1))
		vendors.run_daily()
		self.assertEqual(frappe.db.get_value("Waste Treatment Vendor", vendor, "status"), "Expired")
		self.assertNotIn(vendor, [row["name"] for row in vendors.selectable()])

	def test_warns_at_60_30_7_days_once(self):
		r02 = make_user("waste-hand-r02@example.com", ["TC R02"])
		vendor = make_waste_vendor([self.waste], license_valid_to=add_days(today(), 30))
		vendors.run_daily()
		vendors.run_daily()
		self.assertEqual(
			frappe.db.count(
				"Notification Delivery",
				{
					"event_code": "WASTE_VENDOR_EXPIRING",
					"ref_name": vendor,
					"recipient": r02,
					"channel": "In App",
				},
			),
			1,
		)
		self.assertEqual(vendors.expiring_on(today(), vendor), [("license", 30)])

	def test_contract_rate_wins_over_the_type_rate(self):
		waste = make_waste_type(rates=[{"effective_from": add_days(today(), -1), "rate_per_kg": 500}]).name
		vendor = make_waste_vendor([waste], rate=1000)
		self.assertEqual(vendors.rate_for(vendor, waste, today()), 1000)

	def test_type_rate_applies_without_contract_rate(self):
		waste = make_waste_type(rates=[{"effective_from": add_days(today(), -1), "rate_per_kg": 700}]).name
		vendor = make_waste_vendor([waste], rate=0)
		self.assertEqual(vendors.rate_for(vendor, waste, today()), 700)


class TestDraft(HandoverCase):
	@bru("BRU-WST-003")
	def test_unlicensed_type_cannot_be_added(self):
		other = make_waste_type().name
		location = make_waste_location([other])
		doc = collection.record(
			self.station,
			self.employee,
			CARD,
			[{"waste_type": other, "qty": 1, "weight_kg": 1, "weight_source": "Scale"}],
		)
		bag = frappe.get_all("Waste Container", filters={"collection": doc.name}, pluck="name")[0]
		storage.store(bag, location)
		draft = self.draft()
		block = self.assert_blocked("WASTE_VENDOR_NOT_PERMITTED", handover.add, draft.name, bag)
		self.assertIn(other, block.reason)

	def test_expired_vendor_cannot_be_chosen(self):
		vendor = make_waste_vendor([self.waste], license_valid_to=add_days(today(), 1))
		frappe.db.set_value("Waste Treatment Vendor", vendor, "license_valid_to", add_days(today(), -1))
		self.assert_blocked(
			"WASTE_VENDOR_NOT_PERMITTED", handover.create, self.station, self.employee, vendor
		)

	def test_only_stored_bags_can_be_added_once(self):
		[bag] = self.bags()
		doc = self.draft(bag)
		self.assert_blocked("WASTE_BAG_ALREADY_ON_HANDOVER", handover.add, doc.name, bag)
		other = self.draft()
		self.assert_blocked("WASTE_BAG_ALREADY_ON_HANDOVER", handover.add, other.name, bag)
		self.assert_blocked("WASTE_BAG_NOT_STORED", handover.add, other.name, "CT-000000-00000")

	def test_lines_total_the_collected_weight(self):
		bags = self.bags(qty=2, weight=3)
		doc = self.draft(*bags)
		self.assertEqual([(row.qty, flt(row.collected_kg)) for row in doc.lines], [(2, 3)])
		handover.remove(doc.name, bags[0])
		doc.reload()
		self.assertEqual([row.qty for row in doc.lines], [1])

	@bru("BRU-WST-002")
	def test_fifo_lists_overdue_then_oldest_first(self):
		bags = self.bags(qty=3, weight=3)
		frappe.db.set_value("Waste Container", bags[2], "overdue_at", frappe.utils.now_datetime())
		frappe.db.set_value(
			"Waste Container", bags[1], "collected_at", add_to_date(frappe.utils.now_datetime(), hours=-5)
		)
		self.assertEqual(
			[row["name"] for row in handover.fifo(self.waste) if row["name"] in bags][:3],
			[bags[2], bags[1], bags[0]],
		)

	def test_add_type_takes_the_stock_of_the_type(self):
		bags = self.bags(qty=2, weight=2)
		doc = handover.create(self.station, self.employee, self.vendor)
		handover.add_type(doc.name, self.waste)
		doc.reload()
		self.assertEqual(
			sorted(row.container for row in doc.containers if row.container in bags), sorted(bags)
		)


class TestSubmit(HandoverCase):
	def test_posts_bags_as_handed_over(self):
		[bag] = self.bags()
		doc = self.post(bag)
		self.assertEqual(doc.docstatus, 1)
		self.assertRegex(doc.name, r"^BG-\d{4}-\d{5}$")
		row = frappe.db.get_value("Waste Container", bag, ["status", "handover"], as_dict=True)
		self.assertEqual((row.status, row.handover), ("Handed Over", doc.name))

	def test_handed_over_bag_leaves_the_stock(self):
		[bag] = self.bags()
		self.post(bag)
		self.assertNotIn(bag, [row["name"] for row in storage.stock()["containers"]])

	@bru("BRU-WST-003")
	def test_license_lapsed_after_drafting_blocks_posting(self):
		[bag] = self.bags()
		doc = self.draft(bag)
		self.fill(doc)
		frappe.db.set_value("Waste Treatment Vendor", self.vendor, "license_valid_to", add_days(today(), -1))
		block = self.assert_blocked("WASTE_VENDOR_NOT_PERMITTED", handover.submit, doc.name)
		self.assertIn(self.waste, block.reason)

	def test_manual_weight_needs_confirmation(self):
		[bag] = self.bags()
		doc = self.draft(bag)
		self.assert_blocked(
			"WASTE_WEIGHT_UNCONFIRMED",
			self.fill,
			doc,
			weights=[{"waste_type": self.waste, "handover_kg": 1, "weight_source": "Manual"}],
		)

	def test_missing_weight_blocks_posting(self):
		[bag] = self.bags()
		doc = self.draft(bag)
		self.assert_blocked("WASTE_WEIGHT_MISSING", handover.submit, doc.name)

	@bru("BRU-WST-004")
	def test_difference_above_threshold_needs_reason_and_r02(self):
		[bag] = self.bags(weight=10)
		doc = self.draft(bag)
		self.fill(doc, kg=9)
		self.assert_blocked("WASTE_VARIANCE_REASON", handover.submit, doc.name)
		self.fill(doc, kg=9, variance_reason="Rò rỉ")
		self.assert_blocked("WASTE_VARIANCE_APPROVAL", handover.submit, doc.name)
		posted = handover.submit(doc.name, approver=self.employee)
		self.assertEqual(posted.variance_approved_by, self.employee)
		self.assertEqual(flt(posted.lines[0].difference_percent), 10)
		self.assertTrue(
			frappe.db.exists(
				"Incident CAPA",
				{
					"source_doctype": "Waste Handover",
					"source_name": doc.name,
					"incident_type": "Waste Weight Variance",
				},
			)
		)

	@bru("BRU-WST-004")
	def test_difference_within_threshold_passes_and_is_configurable(self):
		[bag] = self.bags(weight=100)
		doc = self.draft(bag)
		self.fill(doc, kg=96)
		self.assertEqual(handover.submit(doc.name).docstatus, 1)
		frappe.db.set_single_value("TraceCore Settings", "waste_variance_percent", 1)
		[bag] = self.bags(weight=100)
		doc = self.draft(bag)
		self.fill(doc, kg=96)
		self.assert_blocked("WASTE_VARIANCE_REASON", handover.submit, doc.name)

	def test_hazardous_waste_needs_the_document(self):
		[bag] = self.bags()
		doc = self.draft(bag)
		self.fill(doc, hazard_document_no="")
		block = self.assert_blocked("WASTE_DOCUMENT_REQUIRED", handover.submit, doc.name)
		self.assertTrue(block.reason)

	def test_general_waste_needs_no_document(self):
		[bag] = self.bags(waste=self.general)
		doc = self.draft(bag)
		self.fill(doc, hazard_document_no="", transporter="", contract_no="", hazard_document_scan="")
		self.assertEqual(handover.submit(doc.name).docstatus, 1)

	def test_document_can_come_later_and_is_reminded_after_7_days(self):
		[bag] = self.bags()
		doc = self.draft(bag)
		self.fill(doc, hazard_document_no="", hazard_document_scan="", document_pending=1)
		posted = handover.submit(doc.name)
		self.assertEqual(posted.document_pending, 1)
		frappe.db.set_value(
			"Waste Handover", posted.name, "handover_at", add_to_date(frappe.utils.now_datetime(), days=-8)
		)
		self.assertEqual(vendors.remind_pending_documents(), [posted.name])
		self.assertEqual(vendors.remind_pending_documents(), [])
		done = handover.attach_document(posted.name, "CTNH-9", "/files/x.pdf", "Xe", "HD")
		self.assertEqual((done.document_pending, done.hazard_document_no), (0, "CTNH-9"))

	def test_signatures_are_required(self):
		[bag] = self.bags()
		doc = self.draft(bag)
		self.fill(doc, vendor_signature="", vendor_signer="")
		self.assert_blocked("WASTE_SIGNATURE_REQUIRED", handover.submit, doc.name)
		frappe.db.set_value("Waste Handover", doc.name, "minutes_photo", "/files/minutes.jpg")
		self.assertEqual(handover.submit(doc.name).docstatus, 1)

	def test_skipping_older_bags_needs_a_reason(self):
		bags = self.bags(qty=2, weight=2)
		frappe.db.set_value(
			"Waste Container", bags[0], "collected_at", add_to_date(frappe.utils.now_datetime(), hours=-5)
		)
		doc = self.draft(bags[1])
		self.assertEqual(handover.view(doc)["fifo_skipped"][0], bags[0])
		self.fill(doc)
		self.assert_blocked("WASTE_FIFO_REASON", handover.submit, doc.name)
		self.fill(doc, fifo_reason="Xe đầy")
		self.assertEqual(handover.submit(doc.name).docstatus, 1)

	def test_empty_handover_is_refused(self):
		doc = self.draft()
		self.assert_blocked("WASTE_HANDOVER_EMPTY", handover.submit, doc.name)

	def test_cancel_returns_bags_to_the_store_and_cancels_the_cost(self):
		[bag] = self.bags()
		doc = self.post(bag)
		entry = frappe.db.get_value("Waste Handover", doc.name, "cost_entry")
		doc.reload()
		doc.flags.ignore_permissions = True
		doc.cancel()
		row = frappe.db.get_value("Waste Container", bag, ["status", "handover"], as_dict=True)
		self.assertEqual((row.status, row.handover), ("Stored", None))
		self.assertEqual(frappe.db.get_value("Cost Entry", entry, "docstatus"), 2)


class TestCost(HandoverCase):
	def test_cost_is_kg_times_contract_rate_and_split_by_department_kg(self):
		first = self.bags(weight=3, card=CARD)
		second = self.bags(weight=1, card=CARD_2)
		doc = self.post(*first, *second)
		self.assertEqual(flt(doc.total_cost), 4000)
		entry = frappe.get_doc("Cost Entry", doc.cost_entry)
		self.assertEqual((entry.docstatus, entry.category, flt(entry.amount)), (1, "Outsourcing Cost", 4000))
		self.assertEqual(
			{row.target: flt(row.percent) for row in entry.allocations},
			{self.department: 75, self.department_2: 25},
		)
		self.assertEqual({row.target_type for row in entry.allocations}, {"Department"})

	def test_changing_rate_later_keeps_the_posted_cost(self):
		[bag] = self.bags(weight=2)
		doc = self.post(bag)
		vendor = frappe.get_doc("Waste Treatment Vendor", self.vendor)
		for row in vendor.contracts:
			row.rate_per_kg = 9000
		vendor.flags.ignore_permissions = True
		vendor.save()
		self.assertEqual(flt(frappe.db.get_value("Waste Handover", doc.name, "total_cost")), 2000)

	def test_closed_cost_period_does_not_block_the_handover(self):
		frappe.db.set_single_value("Cost Settings", "locked_until", today())
		self.addCleanup(frappe.db.set_single_value, "Cost Settings", "locked_until", None)
		[bag] = self.bags()
		doc = self.post(bag)
		self.assertEqual(doc.docstatus, 1)
		self.assertFalse(doc.cost_entry)
