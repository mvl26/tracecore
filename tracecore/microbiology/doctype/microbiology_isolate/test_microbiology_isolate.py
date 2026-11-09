"""Microbiology Isolate: mã BN mã hóa/che, gắn nhãn đa kháng, chủng đầu tiên, thông báo, tiền sử
(FEAT-067 AC-5, AC-7..AC-11, AC-13; FR-M14-03..05; BRU-MDR-001, BRU-MDR-002, BRU-HAI-005; NFR-PRIV-01; A-136)."""

import json
from unittest.mock import patch

import frappe

from tracecore.core import notification, patient_code
from tracecore.core.errors import BlockedError
from tracecore.microbiology import isolates
from tracecore.microbiology.tests.factories import isolate_values, make_organism, make_rule, new_isolate
from tracecore.tests.factories import make_department, make_employee, make_user
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

PATIENT = "BN0001234"


class IsolateCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_organism()
		make_organism("eco", "Escherichia coli", "Enterobacterales")
		make_organism("sau", "Staphylococcus aureus", "Staphylococcus")
		notification.ensure_default_rules()
		# quy tắc của site test (fixtures, bản khác) không được làm lệch kết quả
		frappe.db.delete("MDRO Rule", {"rule_code": ["not like", "T-%"]})


class TestIsolatePrivacy(IsolateCase):
	def test_permission_matrix(self):
		for doctype in ("Microbiology Isolate", "Organism"):
			assert_permission_matrix(self, doctype)

	@bru("BRU-HAI-005")
	def test_patient_code_is_encrypted_hashed_and_masked(self):
		doc = new_isolate(patient=" bn0001234 ")
		row = frappe.db.get_value(
			"Microbiology Isolate",
			doc.name,
			["patient_code", "patient_code_masked", "patient_code_hash"],
			as_dict=True,
		)
		self.assertNotIn(PATIENT, frappe.as_json(row))
		self.assertEqual(row.patient_code_masked, "***1234")
		self.assertEqual(row.patient_code_hash, patient_code.hash_of(PATIENT))
		self.assertEqual(doc.get_password("patient_code"), PATIENT)
		logs = frappe.get_all("Audit Log", filters={"ref_name": doc.name}, fields=["old_value", "new_value"])
		self.assertTrue(logs)
		self.assertNotIn(PATIENT, frappe.as_json(logs))

	@bru("BRU-HAI-005")
	def test_no_patient_name_field(self):
		for doctype in ("Microbiology Isolate", "Isolate Susceptibility", "Organism", "MDRO Rule"):
			names = {field.fieldname for field in frappe.get_meta(doctype).fields}
			self.assertFalse(names & {"patient_name", "full_name", "first_name", "last_name"}, doctype)

	def test_reveal_needs_r01_or_r11_and_a_reason(self):
		doc = new_isolate()
		with self.assertRaises(BlockedError):
			patient_code.reveal("Microbiology Isolate", doc.name, " ")
		self.assertEqual(patient_code.reveal("Microbiology Isolate", doc.name, "Đối chiếu bệnh án"), PATIENT)
		log = frappe.get_all(
			"Audit Log",
			filters={"action": "View Patient Code", "ref_name": doc.name},
			fields=["reason", "new_value"],
		)
		self.assertEqual(len(log), 1)
		self.assertNotIn(PATIENT, frappe.as_json(log))
		frappe.set_user(make_user("micro-r13@example.com", ["TC R13"]))
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			patient_code.reveal("Microbiology Isolate", doc.name, "Xem")

	def test_r13_cannot_read_isolates(self):
		new_isolate()
		frappe.set_user(make_user("micro-r13@example.com", ["TC R13"]))
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertFalse(frappe.has_permission("Microbiology Isolate", "read"))

	def test_isolate_cannot_be_created_or_edited_outside_the_service(self):
		values = isolate_values(lab="L-DESK")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "Microbiology Isolate", **values}).insert(ignore_permissions=True)
		doc = new_isolate(lab="L-EDIT")
		doc.reload()
		doc.specimen_type = "Urine"
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_same_sample_and_organism_is_rejected(self):
		new_isolate(lab="L-DUP")
		with self.assertRaises(frappe.ValidationError):
			new_isolate(lab="L-DUP")
		self.assertTrue(new_isolate(lab="L-DUP", organism="eco").name)


class TestMdroLabels(IsolateCase):
	@bru("BRU-MDR-001")
	def test_only_approved_rules_label_new_isolates(self):
		make_rule("T-DRAFT", label="DRAFTLBL", submit=False)
		make_rule("T-CRE", label="CRE")
		doc = new_isolate(results=(("MEM", "R"), ("CIP", "S")))
		self.assertEqual((doc.is_mdro, doc.mdro_flags), (1, "CRE"))
		self.assertIn("MDR-T-CRE-V1", doc.mdro_rule_versions)
		clean = new_isolate(lab="L-002", results=(("MEM", "S"),))
		self.assertEqual((clean.is_mdro, clean.mdro_flags), (0, None))

	@bru("BRU-MDR-001")
	def test_new_rule_version_never_relabels_recorded_isolates(self):
		rule = make_rule("T-CRE", label="CRE")
		doc = new_isolate(results=(("MEM", "R"),))
		revised = frappe.copy_doc(rule)
		for row in [revised, *revised.get_all_children()]:
			row.docstatus = 0
		revised.label = "CRE2"
		revised.insert(ignore_permissions=True).submit()
		self.assertEqual(frappe.db.get_value("Microbiology Isolate", doc.name, "mdro_flags"), "CRE")
		later = new_isolate(lab="L-003", results=(("MEM", "R"),))
		self.assertEqual(later.mdro_flags, "CRE2")

	@bru("BRU-MDR-002")
	def test_two_e_coli_in_the_same_month_mark_one_first_isolate(self):
		first = new_isolate(lab="L-10", organism="eco", collected_on="2026-08-03")
		second = new_isolate(lab="L-11", organism="eco", collected_on="2026-08-20")
		other_species = new_isolate(lab="L-12", organism="kpn", collected_on="2026-08-21")
		flags = dict(
			frappe.get_all("Microbiology Isolate", fields=["name", "is_first_isolate"], as_list=True)
		)
		self.assertEqual((flags[first.name], flags[second.name], flags[other_species.name]), (1, 0, 1))
		self.assertEqual(first.period_key, "2026-Q3")

	@bru("BRU-MDR-002")
	def test_late_earlier_sample_takes_the_first_isolate_flag(self):
		later = new_isolate(lab="L-20", organism="eco", collected_on="2026-09-15")
		earlier = new_isolate(lab="L-21", organism="eco", collected_on="2026-07-02")
		self.assertEqual(frappe.db.get_value("Microbiology Isolate", later.name, "is_first_isolate"), 0)
		self.assertEqual(frappe.db.get_value("Microbiology Isolate", earlier.name, "is_first_isolate"), 1)
		next_quarter = new_isolate(lab="L-22", organism="eco", collected_on="2026-10-01")
		self.assertEqual(
			frappe.db.get_value("Microbiology Isolate", next_quarter.name, "is_first_isolate"), 1
		)


class TestMdroAlerts(IsolateCase):
	def test_new_mdro_isolate_alerts_r11_network_r08_and_rule_roles(self):
		department = make_department("Khoa Hồi sức vi sinh")
		r11 = make_user("micro-r11@example.com", ["TC R11"])
		r08 = make_user("micro-r08@example.com", ["TC R08"])
		frappe.get_doc(
			{"doctype": "User Permission", "user": r08, "allow": "Department", "for_value": department}
		).insert(ignore_permissions=True)
		other_r08 = make_user("micro-r08-other@example.com", ["TC R08"])
		member_user = make_user("micro-r12@example.com", ["TC R12"])
		employee = make_employee(department=department, user_id=member_user)
		frappe.get_doc(
			{
				"doctype": "IC Network Member",
				"employee": employee.name,
				"department": department,
				"member_type": "Nurse",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		pharmacist = make_user("micro-pharm@example.com", ["TC R09"])
		make_rule("T-CRE", label="CRE", alert_roles="TC R09")
		with patch.object(isolates.extension, "run", wraps=isolates.extension.run) as hook:
			doc = new_isolate(department=department, results=(("MEM", "R"),))
		hook.assert_any_call(isolates.MDRO_HOOK, doc)
		rows = frappe.get_all(
			"Notification Delivery",
			filters={"event_code": isolates.MDRO_EVENT, "ref_name": doc.name, "channel": "In App"},
			fields=["recipient", "urgency", "subject", "message"],
		)
		recipients = {row.recipient for row in rows}
		self.assertTrue({r11, r08, member_user, pharmacist} <= recipients)
		self.assertNotIn(other_r08, recipients)
		self.assertEqual({row.urgency for row in rows}, {"Urgent"})
		self.assertNotIn(PATIENT, json.dumps(rows, default=str))
		self.assertIn("***1234", rows[0].message)

	def test_non_mdro_isolate_sends_nothing(self):
		make_rule("T-CRE", label="CRE")
		doc = new_isolate(results=(("MEM", "S"),))
		self.assertFalse(
			frappe.db.exists(
				"Notification Delivery", {"event_code": isolates.MDRO_EVENT, "ref_name": doc.name}
			)
		)

	def test_history_label_when_patient_had_an_mdro_before(self):
		make_rule(
			"T-MRSA", label="MRSA", organisms=({"organism": "sau"},), criteria=(("OXA", "Penicillins"),)
		)
		old = new_isolate(lab="L-30", organism="sau", results=(("OXA", "R"),), collected_on="2026-03-01")
		new = new_isolate(lab="L-31", organism="kpn", results=(("MEM", "S"),), collected_on="2026-08-01")
		stranger = new_isolate(lab="L-32", organism="kpn", patient="BN9999", results=(("MEM", "S"),))
		history = isolates.mdro_history(
			[
				{"name": n.name, "patient_code_hash": n.patient_code_hash, "collected_on": n.collected_on}
				for n in (old, new, stranger)
			]
		)
		self.assertEqual(history[new.name], ["MRSA"])
		self.assertEqual(history[old.name], [])
		self.assertEqual(history[stranger.name], [])
