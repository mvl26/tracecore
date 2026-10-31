"""Kho lưu giữ tạm chất thải (FEAT-048, UC-35, FR-M10-03, .1-.4, BRU-WST-001, BRU-WST-002, BRU-ID-006, A-61)."""

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from tracecore.core import notification
from tracecore.core.errors import BlockedError
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_user,
	make_waste_location,
	make_waste_station,
	make_waste_type,
	make_waste_zone,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.waste import collection, storage

CARD = "WASTE-STORE-CARD"


class StorageCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		self.station = make_waste_station()
		self.department = make_department("Khoa Kho Waste")
		self.giver = make_employee(card=CARD, department=self.department, first_name="Giao").name
		self.collector = make_employee(first_name="Thu gom").name
		self.waste = make_waste_type(max_storage_cold_hours=168, storage_override_reason="Test").name
		self.location = make_waste_location([self.waste], default=True)
		self.r02 = make_user("waste-store-r02@example.com", ["TC R02"])

	def collect(self, qty=1, waste=None, **line):
		doc = collection.record(
			self.station,
			self.collector,
			CARD,
			[
				{
					"waste_type": waste or self.waste,
					"qty": qty,
					"weight_kg": qty,
					"weight_source": "Scale",
					**line,
				}
			],
		)
		return doc, frappe.get_all("Waste Container", filters={"collection": doc.name}, pluck="name")

	def age(self, container, hours):
		"""Lùi giờ thu gom `hours` giờ, giữ nguyên thời lượng lưu."""
		row = frappe.db.get_value("Waste Container", container, ["collected_at", "storage_due"], as_dict=True)
		frappe.db.set_value(
			"Waste Container",
			container,
			{
				"collected_at": add_to_date(row.collected_at, hours=-hours),
				"storage_due": add_to_date(row.storage_due, hours=-hours),
			},
		)

	def assert_blocked(self, code, fn, *args):
		with self.assertRaises(BlockedError) as ctx:
			fn(*args)
		self.assertEqual(ctx.exception.block.code, code)
		return ctx.exception.block


class TestLocation(StorageCase):
	@bru("BRU-ID-006")
	def test_location_gets_a_registered_ke_code(self):
		self.assertRegex(self.location, r"^KE-\d{4,}$")
		self.assertEqual(frappe.db.get_value("Code Registry", self.location, "prefix"), "KE")

	def test_location_needs_a_waste_type(self):
		with self.assertRaises(frappe.ValidationError):
			make_waste_location([])

	def test_location_must_be_in_a_waste_zone(self):
		with self.assertRaises(frappe.ValidationError):
			make_waste_location([self.waste], zone="TR-004")

	def test_cold_room_needs_a_zone(self):
		with self.assertRaises(frappe.ValidationError):
			make_waste_location([self.waste], is_cold=1, zone=None)

	def test_one_default_location_per_type(self):
		with self.assertRaises(frappe.ValidationError):
			make_waste_location([self.waste], default=True)


class TestStore(StorageCase):
	def test_store_moves_bag_into_the_location(self):
		_doc, [bag] = self.collect()
		storage.store(bag, self.location)
		row = frappe.db.get_value(
			"Waste Container", bag, ["status", "storage_location", "stored_at", "cold_storage"], as_dict=True
		)
		self.assertEqual((row.status, row.storage_location, row.cold_storage), ("Stored", self.location, 0))
		self.assertTrue(row.stored_at)

	@bru("BRU-WST-002")
	def test_storage_time_runs_from_the_collection(self):
		_doc, [bag] = self.collect()
		self.age(bag, 10)
		storage.store(bag, self.location)
		row = frappe.db.get_value("Waste Container", bag, ["collected_at", "storage_due"], as_dict=True)
		self.assertEqual(get_datetime(row.storage_due), add_to_date(row.collected_at, hours=48))

	@bru("BRU-WST-001")
	def test_wrong_location_is_refused_and_names_the_right_one(self):
		other = make_waste_type(waste_group="General").name
		wrong = make_waste_location([other])
		_doc, [bag] = self.collect()
		block = self.assert_blocked("WASTE_WRONG_LOCATION", storage.store, bag, wrong)
		self.assertIn(self.location, block.reason)
		self.assertEqual(frappe.db.get_value("Waste Container", bag, "status"), "Collected")

	def test_unknown_bag_is_refused(self):
		self.assert_blocked("WASTE_CONTAINER_UNKNOWN", storage.store, "CT-000000-00000", self.location)

	def test_held_bag_is_refused(self):
		_doc, [bag] = self.collect(misclassified=1, misclass_note="Mixed")
		self.assert_blocked("WASTE_NOT_STORABLE", storage.store, bag, self.location)

	def test_inactive_or_sterile_location_is_refused(self):
		frappe.db.set_value("Waste Storage Location", self.location, "is_active", 0)
		_doc, [bag] = self.collect()
		self.assert_blocked("WASTE_LOCATION_INVALID", storage.store, bag, self.location)
		self.assert_blocked("WASTE_LOCATION_INVALID", storage.store, bag, "KE-0000")

	def test_move_to_cold_room_extends_and_back_shortens_the_due_time(self):
		cold = make_waste_location([self.waste], is_cold=1, zone=make_waste_zone())
		_doc, [bag] = self.collect()
		storage.store(bag, self.location)
		storage.store(bag, cold)
		row = frappe.db.get_value(
			"Waste Container", bag, ["collected_at", "storage_due", "cold_storage"], as_dict=True
		)
		self.assertEqual(row.cold_storage, 1)
		self.assertEqual(get_datetime(row.storage_due), add_to_date(row.collected_at, hours=168))
		storage.store(bag, self.location)
		row = frappe.db.get_value(
			"Waste Container", bag, ["collected_at", "storage_due", "cold_storage"], as_dict=True
		)
		self.assertEqual(row.cold_storage, 0)
		self.assertEqual(get_datetime(row.storage_due), add_to_date(row.collected_at, hours=48))

	def test_type_without_cold_time_keeps_the_normal_time_in_a_cold_room(self):
		waste = make_waste_type().name
		cold = make_waste_location([waste], is_cold=1, zone=make_waste_zone())
		_doc, [bag] = self.collect(waste=waste)
		storage.store(bag, cold)
		self.assertEqual(frappe.db.get_value("Waste Container", bag, "cold_storage"), 0)

	def test_whole_collection_goes_to_default_locations(self):
		doc, bags = self.collect(qty=2)
		result = storage.store_collection(doc.name)
		self.assertEqual(result["stored"], 2)
		for bag in bags:
			self.assertEqual(frappe.db.get_value("Waste Container", bag, "storage_location"), self.location)

	def test_collection_without_default_location_stores_nothing(self):
		waste = make_waste_type().name
		doc = collection.record(
			self.station,
			self.collector,
			CARD,
			[
				{"waste_type": self.waste, "qty": 1, "weight_kg": 1, "weight_source": "Scale"},
				{"waste_type": waste, "qty": 1, "weight_kg": 1, "weight_source": "Scale"},
			],
		)
		block = self.assert_blocked("WASTE_NO_DEFAULT_LOCATION", storage.store_collection, doc.name)
		self.assertIn(waste, block.reason)
		self.assertFalse(frappe.db.exists("Waste Container", {"collection": doc.name, "status": "Stored"}))

	def test_collection_with_nothing_left_is_refused(self):
		doc, _bags = self.collect()
		storage.store_collection(doc.name)
		self.assert_blocked("WASTE_NOTHING_TO_STORE", storage.store_collection, doc.name)
		self.assert_blocked("WASTE_NOTHING_TO_STORE", storage.store_collection, "TG-NOPE")


class TestChecks(StorageCase):
	def deliveries(self, event):
		return frappe.db.count("Notification Delivery", {"event_code": event, "recipient": self.r02})

	@bru("BRU-WST-002")
	def test_warns_once_at_80_percent(self):
		_doc, [bag] = self.collect()
		storage.store(bag, self.location)
		self.age(bag, 37)
		storage.run_checks()
		self.assertEqual(self.deliveries("WASTE_STORAGE_DUE"), 0)
		self.age(bag, 2)
		storage.run_checks()
		storage.run_checks()
		self.assertEqual(self.deliveries("WASTE_STORAGE_DUE"), 1)

	def test_warn_percent_is_configurable(self):
		frappe.db.set_single_value("TraceCore Settings", "waste_warn_percent", 50)
		_doc, [bag] = self.collect()
		self.age(bag, 25)
		storage.run_checks()
		self.assertEqual(self.deliveries("WASTE_STORAGE_DUE"), 1)

	@bru("BRU-WST-002")
	def test_overdue_alerts_red_and_creates_one_nc(self):
		_doc, [bag] = self.collect()
		storage.store(bag, self.location)
		self.age(bag, 49)
		storage.run_checks()
		storage.run_checks()
		self.assertEqual(self.deliveries("WASTE_STORAGE_OVERDUE"), 1)
		nc = frappe.get_all(
			"Incident CAPA",
			filters={"source_doctype": "Waste Container", "source_name": bag},
			fields=["incident_type", "department", "is_auto"],
		)
		self.assertEqual(
			[(row.incident_type, row.department, row.is_auto) for row in nc],
			[("Waste Storage Overdue", self.department, 1)],
		)

	def test_handed_over_or_cancelled_bags_are_not_checked(self):
		doc, [bag] = self.collect()
		self.age(bag, 49)
		doc.cancel()
		storage.run_checks()
		self.assertEqual(self.deliveries("WASTE_STORAGE_OVERDUE"), 0)

	def test_moving_back_in_time_clears_the_alert_marks(self):
		cold = make_waste_location([self.waste], is_cold=1, zone=make_waste_zone())
		_doc, [bag] = self.collect()
		self.age(bag, 49)
		storage.run_checks()
		storage.store(bag, cold)
		row = frappe.db.get_value("Waste Container", bag, ["due_warned_at", "overdue_at"], as_dict=True)
		self.assertEqual((row.due_warned_at, row.overdue_at), (None, None))


class TestColdRoom(StorageCase):
	def setUp(self):
		super().setUp()
		self.zone = make_waste_zone(monitored=True)
		self.cold = make_waste_location([self.waste], is_cold=1, zone=self.zone)

	def reading(self, temperature, hours_ago=0):
		return (
			frappe.get_doc(
				{
					"doctype": "Environment Log",
					"zone": self.zone,
					"temperature": temperature,
					"measured_at": add_to_date(now_datetime(), hours=-hours_ago),
				}
			)
			.insert(ignore_permissions=True)
			.submit()
		)

	def stored_bag(self):
		_doc, [bag] = self.collect()
		storage.store(bag, self.cold)
		return bag

	def test_record_temperature_writes_a_manual_log(self):
		doc = storage.record_temperature(self.cold, "6,5")
		self.assertEqual(
			(doc.zone, doc.temperature, doc.source, doc.docstatus), (self.zone, "6.5", "Manual", 1)
		)

	def test_temperature_must_be_a_number(self):
		self.assert_blocked("WASTE_TEMPERATURE_INVALID", storage.record_temperature, self.cold, "abc")
		self.assert_blocked("WASTE_TEMPERATURE_INVALID", storage.record_temperature, self.cold, "")

	def test_temperature_is_for_a_cold_room(self):
		self.assert_blocked("WASTE_NOT_COLD_ROOM", storage.record_temperature, self.location, "6")

	@bru("BRU-WST-002")
	def test_two_hours_above_8_degrees_restores_the_normal_time(self):
		bag = self.stored_bag()
		self.reading(9, hours_ago=3)
		self.reading(9.5, hours_ago=1)
		storage.run_checks()
		row = frappe.db.get_value(
			"Waste Container",
			bag,
			["collected_at", "storage_due", "cold_storage", "cold_voided"],
			as_dict=True,
		)
		self.assertEqual((row.cold_storage, row.cold_voided), (0, 1))
		self.assertEqual(get_datetime(row.storage_due), add_to_date(row.collected_at, hours=48))
		storage.run_checks()
		self.assertEqual(
			frappe.db.count(
				"Notification Delivery", {"event_code": "WASTE_COLD_BREACH", "recipient": self.r02}
			),
			1,
		)

	def test_short_breach_changes_nothing(self):
		bag = self.stored_bag()
		self.reading(9, hours_ago=1)
		storage.run_checks()
		self.assertEqual(frappe.db.get_value("Waste Container", bag, "cold_storage"), 1)

	def test_reading_back_in_range_ends_the_breach(self):
		bag = self.stored_bag()
		self.reading(9, hours_ago=5)
		self.reading(5, hours_ago=4)
		self.reading(9, hours_ago=1)
		storage.run_checks()
		self.assertEqual(frappe.db.get_value("Waste Container", bag, "cold_storage"), 1)

	def test_breach_limits_are_configurable(self):
		frappe.db.set_single_value("TraceCore Settings", "waste_cold_limit_c", 10)
		frappe.db.set_single_value("TraceCore Settings", "waste_cold_breach_hours", 4)
		bag = self.stored_bag()
		self.reading(9, hours_ago=5)
		storage.run_checks()
		self.assertEqual(frappe.db.get_value("Waste Container", bag, "cold_storage"), 1)
		self.reading(11, hours_ago=5)
		storage.run_checks()
		self.assertEqual(frappe.db.get_value("Waste Container", bag, "cold_storage"), 0)

	def test_room_in_breach_takes_new_bags_at_the_normal_time_until_it_recovers(self):
		self.reading(9, hours_ago=3)
		storage.run_checks()
		self.assertEqual(frappe.db.get_value("Waste Container", self.stored_bag(), "cold_storage"), 0)
		self.reading(5)
		storage.run_checks()
		self.assertIsNone(frappe.db.get_value("Waste Storage Location", self.cold, "cold_breach_since"))
		self.assertEqual(frappe.db.get_value("Waste Container", self.stored_bag(), "cold_storage"), 1)


class TestStock(StorageCase):
	def test_stock_groups_by_type_and_location_with_remaining_time(self):
		_doc, bags = self.collect(qty=2)
		storage.store(bags[0], self.location)
		self.age(bags[0], 47)
		result = storage.stock()
		row = next(row for row in result["summary"] if row["location"] == self.location)
		self.assertEqual((row["waste_type"], row["bags"], row["state"]), (self.waste, 1, "Due Soon"))
		self.assertLessEqual(row["remaining_minutes"], 60)
		waiting = next(row for row in result["summary"] if not row["location"])
		self.assertEqual(waiting["bags"], 1)

	def test_stock_lists_most_urgent_first_and_marks_overdue(self):
		_doc, bags = self.collect(qty=2)
		self.age(bags[1], 49)
		rows = storage.stock()["containers"]
		rows = [row for row in rows if row["name"] in bags]
		self.assertEqual([row["name"] for row in rows], [bags[1], bags[0]])
		self.assertEqual(rows[0]["state"], "Overdue")
		self.assertEqual(rows[1]["state"], "OK")

	def test_stock_shows_the_last_temperature_of_cold_rooms(self):
		cold = make_waste_location([self.waste], is_cold=1, zone=make_waste_zone(monitored=True))
		storage.record_temperature(cold, "4")
		room = next(row for row in storage.stock()["cold_rooms"] if row["location"] == cold)
		self.assertEqual(room["temperature"], "4")


class TestThresholds(StorageCase):
	def test_defaults_apply_when_unset(self):
		self.assertEqual(
			storage.thresholds(),
			{"warn_percent": 80, "cold_limit_c": 8, "breach_hours": 2, "variance_percent": 5},
		)

	def test_set_thresholds_validates_and_saves(self):
		storage.set_thresholds(70, 7.5, 3)
		self.assertEqual(
			storage.thresholds(),
			{"warn_percent": 70, "cold_limit_c": 7.5, "breach_hours": 3, "variance_percent": 5},
		)
		for values in ((0, 8, 2), (100, 8, 2), (80, 8, 0), ("x", 8, 2)):
			self.assert_blocked("WASTE_THRESHOLD_INVALID", storage.set_thresholds, *values)
