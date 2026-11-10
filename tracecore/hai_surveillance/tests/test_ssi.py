"""Giám sát NKVM: nhóm phẫu thuật, NNIS, cửa sổ, lịch theo dõi sau ra viện, kết cục, kháng sinh dự phòng (FEAT-064;
FR-M13-07, 07.1, 07.2, 08, 08.1, 09, 09.1, 09.2; BRU-HAI-003, BRU-HAI-004, BRU-HAI-005, BRU-RPT-003; UC-49 A2, E1, E2,
E4; A-147 Q2, Q3, a-h, l)."""

import json
import pathlib

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core.errors import BlockedError
from tracecore.hai_surveillance import periods, ssi, ssi_seed
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.hai_surveillance.tests import ssi_fixtures as s
from tracecore.tests.utils import IsolatedTestCase, bru

DOCTYPE_DIR = pathlib.Path(frappe.get_app_path("tracecore", "hai_surveillance", "doctype"))


class SSITestBase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = f.make_ward("KSNK SSI CTCH")
		self.group = s.make_group(
			"T-HPRO", t=120, implant=1, followups=((7, "Phone"), (30, "Phone"), (90, "Revisit"))
		)
		self.plain = s.make_group(
			"T-APPY", name="Cắt ruột thừa test", t=60, implant=0, followups=((7, "Phone"),)
		)
		self.r11 = f.factories.make_user("ssi-r11@test.local", [h.R11])
		self.r01 = f.factories.make_user("ssi-r01@test.local", [h.R01])
		s.set_threshold(60)

	def block(self, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		return caught.exception.block


class TestGroups(SSITestBase):
	@bru("BRU-HAI-004")
	def test_implant_group_window_is_90_days(self):
		with self.assertRaises(frappe.ValidationError):
			s.make_group("T-KPRO", implant=1, days=30)

	def test_followup_day_outside_window_blocked(self):
		with self.assertRaises(frappe.ValidationError):
			s.make_group("T-CHOL", implant=0, followups=((45, "Phone"),))
		with self.assertRaises(frappe.ValidationError):
			s.make_group("T-CHOL", implant=0, followups=((0, "Phone"),))

	def test_seed_inserts_missing_groups_unmonitored_and_keeps_edits(self):
		for code in ssi_seed.CODES:
			if frappe.db.exists(s.GROUP, code):
				frappe.delete_doc(s.GROUP, code, force=True, ignore_permissions=True)
		created = ssi_seed.ensure_seed()
		self.assertEqual(set(created), set(ssi_seed.CODES))
		self.assertFalse(any(frappe.db.get_value(s.GROUP, code, "is_monitored") for code in created))
		frappe.db.set_value(s.GROUP, "HPRO", "t_time_minutes", 150)
		self.assertEqual(ssi_seed.ensure_seed(), [])  # NFR-MAINT-04: chạy lại không ghi đè
		self.assertEqual(frappe.db.get_value(s.GROUP, "HPRO", "t_time_minutes"), 150)


class TestRegistration(SSITestBase):
	@bru("BRU-HAI-003")
	def test_nnis_example_of_srs(self):
		doc = s.make_ssi(self.ward, self.group.name)  # ASA 3, Sạch, 150 phút, T 120 → 2 (FR-M13-07.1)
		self.assertEqual(doc.nnis_index, "2")
		self.assertEqual(doc.t_time_applied, 120)
		self.assertEqual(doc.reporting_period, "2026-10")
		self.assertTrue(doc.data_complete)

	@bru("BRU-HAI-003")
	def test_nnis_components(self):
		self.assertEqual(ssi.nnis(2, "Clean", 60, 120)[0], 0)
		self.assertEqual(ssi.nnis(3, "Dirty", 121, 120)[0], 3)
		self.assertEqual(ssi.nnis(1, "Contaminated", 120, 120)[0], 1)
		self.assertEqual(ssi.nnis(1, "Clean-Contaminated", 120, 120)[0], 0)
		self.assertIsNone(ssi.nnis(1, "Clean", 120, None)[0])

	@bru("BRU-HAI-004")
	def test_window_90_with_implant_30_without(self):
		implant = s.make_ssi(self.ward, self.group.name)
		self.assertEqual((implant.window_days, str(implant.window_end)), (90, "2027-01-26"))
		plain = s.make_ssi(self.ward, self.plain.name, code="BN-0000000001")
		self.assertEqual((plain.window_days, str(plain.window_end)), (30, "2026-11-27"))
		case_implant = s.make_ssi(self.ward, self.plain.name, code="BN-0000000002", has_implant=1)
		self.assertEqual(case_implant.window_days, 90)  # ca có cấy ghép dù nhóm không (A-147 d)

	def test_minutes_must_be_whole_number(self):
		block = self.block(
			s.make_ssi, self.ward, self.group.name, prophylaxis_minutes_before_incision="nửa giờ"
		)
		self.assertEqual(block.code, "SSI_VALUE_INVALID")
		self.assertEqual(
			s.make_ssi(
				self.ward, self.group.name, prophylaxis_minutes_before_incision="0"
			).prophylaxis_timing,
			ssi.ON_TIME,
		)
		self.assertEqual(
			s.make_ssi(
				self.ward, self.group.name, code="BN-0000000009", prophylaxis_minutes_before_incision=None
			).prophylaxis_timing,
			ssi.NOT_ASSESSED,
		)

	def test_invalid_asa_or_duration_blocked(self):
		self.assertEqual(
			self.block(s.make_ssi, self.ward, self.group.name, asa_score=6).code, "SSI_VALUE_INVALID"
		)
		self.assertEqual(
			self.block(s.make_ssi, self.ward, self.group.name, duration_min=0).code, "SSI_VALUE_INVALID"
		)

	def test_manual_entry_requires_asa_wound_duration(self):
		block = self.block(s.make_ssi, self.ward, self.group.name, asa_score=None)
		self.assertEqual(block.code, "SSI_VALUE_INVALID")

	def test_future_surgery_or_discharge_before_surgery_blocked(self):
		self.assertEqual(
			self.block(s.make_ssi, self.ward, self.group.name, surgery=add_days(today(), 1)).code,
			"SSI_DATE_INVALID",
		)
		self.assertEqual(
			self.block(s.make_ssi, self.ward, self.group.name, discharge_date="2026-10-20").code,
			"SSI_DATE_INVALID",
		)

	def test_unmonitored_group_blocked(self):
		draft = s.make_group("T-CSEC", t=60, monitored=0)
		self.assertEqual(self.block(s.make_ssi, self.ward, draft.name).code, "SSI_GROUP_NOT_MONITORED")

	def test_group_without_t_skips_nnis_and_warns_r01_once(self):
		group = s.make_group("T-COLO", t=None)
		first = s.make_ssi(self.ward, group.name)
		s.make_ssi(self.ward, group.name, code="BN-0000000003")
		self.assertEqual(first.nnis_index, "")
		self.assertTrue(first.nnis_note)
		sent = frappe.get_all(
			"Notification Delivery",
			filters={"event_code": ssi.T_MISSING_EVENT, "ref_name": group.name, "recipient": self.r01},
		)
		self.assertEqual(len(sent), 1)  # UC-49 E4: một lần mỗi nhóm

	@bru("BRU-HAI-005")
	def test_patient_code_masked_and_no_name_field(self):
		doc = s.make_ssi(self.ward, self.group.name)
		self.assertEqual(doc.patient_code_masked, "***6612")
		self.assertNotEqual(frappe.db.get_value(s.SSI, doc.name, "patient_code"), "BN-0000006612")
		meta = json.loads(
			(DOCTYPE_DIR / "surgical_surveillance" / "surgical_surveillance.json").read_text("utf-8")
		)
		names = {field["fieldname"] for field in meta["fields"]}
		self.assertFalse(names & {"patient_name", "full_name", "ho_ten", "first_name", "last_name"})

	def test_never_deleted(self):
		doc = s.make_ssi(self.ward, self.group.name)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(s.SSI, doc.name, ignore_permissions=True)

	def test_locked_period_blocks_registration_fields_not_followups(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-10-01")
		frappe.set_user(self.r01)
		periods.lock("2026-10")
		frappe.set_user("Administrator")
		doc.reload()
		doc.asa_score = 1
		self.assertEqual(self.block(doc.save).code, "HAI_PERIOD_LOCKED")
		doc.reload()
		doc.discharge_date = getdate("2026-10-05")
		doc.save()  # A-147 g: ra viện, theo dõi vẫn ghi được
		self.assertTrue(doc.followups)


class TestFollowups(SSITestBase):
	def test_schedule_after_discharge_with_final_on_window_end(self):
		doc = s.make_ssi(self.ward, self.group.name, discharge_date="2026-11-02")
		rows = [(str(r.due_date), r.method, r.is_final) for r in doc.followups]
		self.assertEqual(
			rows, [("2026-11-04", "Phone", 0), ("2026-11-27", "Phone", 0), ("2027-01-26", "Revisit", 1)]
		)

	def test_offsets_before_discharge_skipped_and_default_final(self):
		group = s.make_group("T-CHOL", t=120, followups=())
		doc = s.make_ssi(self.ward, group.name, discharge_date="2026-11-02")
		self.assertEqual(
			[(str(r.due_date), r.method, r.is_final) for r in doc.followups], [("2026-11-27", "Phone", 1)]
		)

	def test_no_schedule_without_discharge_or_after_window(self):
		self.assertEqual(s.make_ssi(self.ward, self.plain.name).followups, [])
		late = s.make_ssi(self.ward, self.plain.name, code="BN-0000000004", discharge_date="2026-12-05")
		self.assertEqual(late.followups, [])  # A2: theo dõi nội trú

	def test_record_followup(self):
		doc = s.make_ssi(self.ward, self.plain.name, discharge_date="2026-10-30")
		frappe.set_user(self.r11)
		doc = ssi.record_followup(doc.name, doc.followups[0].name, "2026-11-04", "Negative", "Gọi được")
		row = doc.followups[0]
		self.assertEqual((str(row.done_on), row.result, row.done_by), ("2026-11-04", "Negative", self.r11))

	def test_record_followup_needs_result_and_valid_date(self):
		doc = s.make_ssi(self.ward, self.plain.name, discharge_date="2026-10-30")
		row = doc.followups[0].name
		self.assertEqual(
			self.block(ssi.record_followup, doc.name, row, "2026-11-04", "").code, "SSI_VALUE_INVALID"
		)
		self.assertEqual(
			self.block(ssi.record_followup, doc.name, row, add_days(today(), 2), "Negative").code,
			"SSI_DATE_INVALID",
		)

	@bru("BRU-HAI-004")
	def test_window_over_all_negative_is_no_ssi(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-08-01", discharge_date="2026-08-03")
		for row in doc.followups:
			doc = ssi.record_followup(doc.name, row.name, row.due_date, "Negative")
		self.assertEqual(doc.outcome, ssi.NO_SSI)

	@bru("BRU-HAI-004")
	def test_missed_last_followup_is_lost(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-08-01", discharge_date="2026-08-03")
		doc = ssi.record_followup(doc.name, doc.followups[0].name, "2026-08-08", "Negative")
		self.assertEqual(doc.outcome, ssi.LOST)  # FR-M13-08.1
		unreachable = s.make_ssi(
			self.ward,
			self.plain.name,
			code="BN-0000000005",
			surgery="2026-08-01",
			discharge_date="2026-08-03",
		)
		for row in unreachable.followups:
			unreachable = ssi.record_followup(unreachable.name, row.name, row.due_date, "Unreachable")
		self.assertEqual(unreachable.outcome, ssi.LOST)

	def test_window_open_stays_under_surveillance(self):
		doc = s.make_ssi(self.ward, self.group.name, discharge_date="2026-11-02")
		doc = ssi.record_followup(doc.name, doc.followups[0].name, "2026-11-04", "Negative")
		self.assertEqual(doc.outcome, ssi.UNDER)

	def test_daily_job_closes_expired_windows(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-08-01", discharge_date="2026-08-03")
		frappe.db.set_value(s.SSI, doc.name, "outcome", ssi.UNDER)
		ssi.run_daily()
		self.assertEqual(frappe.db.get_value(s.SSI, doc.name, "outcome"), ssi.LOST)

	def test_close_inpatient_case_manually(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-08-01", discharge_date="2026-09-15")
		frappe.set_user(self.r11)
		self.assertEqual(ssi.close(doc.name, ssi.NO_SSI).outcome, ssi.NO_SSI)
		self.assertEqual(self.block(ssi.close, doc.name, ssi.SSI).code, "SSI_VALUE_INVALID")

	def test_close_blocked_while_window_open(self):
		doc = s.make_ssi(self.ward, self.group.name)
		self.assertEqual(self.block(ssi.close, doc.name, ssi.NO_SSI).code, "SSI_WINDOW_OPEN")

	def test_followups_due_and_reminder_once_a_day(self):
		doc = s.make_ssi(
			self.ward, self.plain.name, surgery=add_days(today(), -10), discharge_date=add_days(today(), -8)
		)
		due = ssi.due_followups(add_days(today(), 30))
		self.assertIn(doc.name, {row["name"] for row in due})
		frappe.db.sql(
			"update `tabSSI Follow-up` set due_date=%s where parent=%s", (getdate(today()), doc.name)
		)
		ssi.remind(f"{today()} 11:00:00")
		ssi.remind(f"{today()} 11:30:00")
		sent = frappe.get_all(
			"Notification Delivery",
			filters={"event_code": ssi.DUE_EVENT, "recipient": self.r11},
			pluck="message",
		)
		self.assertEqual(len(sent), 1)
		self.assertIn("***6612", sent[0])
		self.assertNotIn("BN-0000006612", sent[0])
		self.assertGreaterEqual(ssi.badges(self.r11).get("nkvm"), 1)
		self.assertEqual(ssi.badges(f.factories.make_user("ssi-r13@test.local", [h.R13])), {})


class TestCaseLink(SSITestBase):
	def setUp(self):
		super().setUp()
		h.clear_definitions("TSSI")
		h.make_definition("TSSI", device=None, hours=0, days=0, site="Superficial Incisional SSI")

	def test_create_case_from_followup_then_confirm_sets_ssi(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-10-20", discharge_date="2026-10-22")
		frappe.set_user(self.r11)
		case = ssi.create_case(doc.name, "TSSI", "2026-10-27")
		self.assertEqual((case.surgical_surveillance, case.status), (doc.name, "Suspected"))
		self.assertEqual(case.patient_code_hash, doc.patient_code_hash)
		self.assertEqual(frappe.db.get_value(s.SSI, doc.name, "hai_case"), case.name)
		from tracecore.hai_surveillance import cases

		cases.decide(case.name, "Confirmed")
		self.assertEqual(frappe.db.get_value(s.SSI, doc.name, "outcome"), ssi.SSI)

	def test_excluded_case_recomputes_outcome(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-10-20", discharge_date="2026-10-22")
		frappe.set_user(self.r11)
		case = ssi.create_case(doc.name, "TSSI", "2026-10-27")
		from tracecore.hai_surveillance import cases

		cases.decide(case.name, "Excluded", reason="Không đủ tiêu chí")
		self.assertEqual(frappe.db.get_value(s.SSI, doc.name, "outcome"), ssi.UNDER)

	def test_case_of_other_patient_rejected(self):
		doc = s.make_ssi(self.ward, self.plain.name, surgery="2026-10-20")
		block = self.block(
			h.make_case,
			self.ward,
			def_code="TSSI",
			onset="2026-10-27",
			admitted="2026-10-20 08:00:00",
			code="BN-0000009999",
			surgical_surveillance=doc.name,
		)
		self.assertEqual(block.code, "HAI_CASE_SURGERY_INVALID")


class TestProphylaxis(SSITestBase):
	def test_timing_rules(self):
		self.assertEqual(ssi.prophylaxis_timing(1, 45, 60), ssi.ON_TIME)
		self.assertEqual(ssi.prophylaxis_timing(1, 0, 60), ssi.ON_TIME)
		self.assertEqual(ssi.prophylaxis_timing(1, -10, 60), ssi.LATE)
		self.assertEqual(ssi.prophylaxis_timing(1, 90, 60), ssi.TOO_EARLY)
		self.assertEqual(ssi.prophylaxis_timing(1, 45, None), ssi.NOT_ASSESSED)
		self.assertEqual(ssi.prophylaxis_timing(1, None, 60), ssi.NOT_ASSESSED)
		self.assertEqual(ssi.prophylaxis_timing(0, None, 60), ssi.NOT_GIVEN)

	def test_snapshot_on_save(self):
		doc = s.make_ssi(self.ward, self.group.name)
		self.assertEqual((doc.prophylaxis_timing, doc.prophylaxis_max_applied), (ssi.ON_TIME, 60))

	@bru("BRU-RPT-003")
	def test_threshold_change_recalculates_open_periods_only(self):
		closed = s.make_ssi(self.ward, self.plain.name, surgery="2026-09-10")
		opened = s.make_ssi(self.ward, self.plain.name, surgery="2026-10-10", code="BN-0000000006")
		frappe.set_user(self.r01)
		periods.lock("2026-09")
		frappe.set_user("Administrator")
		s.set_threshold(30)
		ssi.recalculate_prophylaxis()
		self.assertEqual(
			frappe.db.get_value(s.SSI, closed.name, "prophylaxis_timing"), ssi.ON_TIME
		)  # FR-M13-09.2
		self.assertEqual(
			frappe.db.get_value(s.SSI, opened.name, ["prophylaxis_timing", "prophylaxis_max_applied"]),
			(ssi.TOO_EARLY, 30),
		)

	def test_settings_hook_registered(self):
		events = frappe.get_hooks("doc_events")["IC Program Settings"]["on_update"]
		self.assertIn("tracecore.hai_surveillance.ssi.on_settings_update", events)
