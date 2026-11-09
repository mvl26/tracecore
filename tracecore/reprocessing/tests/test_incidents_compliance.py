"""NC loại Compliance từ phiếu giám sát M12 qua hook ``tracecore_compliance_nc`` (FEAT-060; FR-M12-09, A-132 c)."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.reprocessing import incidents
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase


class TestComplianceIncident(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.department = factories.make_department("Compliance NC Ward")
		session = self._session()
		self.ctx = {
			"session": session,
			"department": self.department,
			"description": f"Audit {session}: critical item PNC-04 failed.",
		}

	def _session(self):
		"""Phiếu nguồn dựng qua API theo tên DocType (M2 không import M12)."""
		template = frappe.get_doc(
			{
				"doctype": "Audit Template",
				"template_code": "T-M2-NC",
				"title": "M2 NC source",
				"audit_type": "Standard Precautions - PPE",
				"scoring_method": "Weighted Score",
				"items": [
					{
						"item_code": "PNC-04",
						"question": "No recapping",
						"answer_type": "Pass/Fail",
						"weight": 1,
						"is_critical": 1,
					}
				],
			}
		).insert(ignore_permissions=True)
		template.submit()
		observer = factories.make_employee(first_name="M2 NC Observer").name
		return (
			frappe.get_doc(
				{
					"doctype": "Audit Session",
					"audit_template": template.name,
					"department": self.department,
					"observer": observer,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_hook_creates_compliance_incident_once(self):
		name = incidents.on_compliance_nc(self.ctx)
		doc = frappe.get_doc("Incident CAPA", name)
		self.assertEqual(
			(
				doc.incident_type,
				doc.incident_category,
				doc.source_doctype,
				doc.source_name,
				doc.department,
				doc.is_auto,
			),
			(
				"Compliance Nonconformity",
				"Compliance",
				"Audit Session",
				self.ctx["session"],
				self.department,
				1,
			),
		)
		self.assertEqual(incidents.on_compliance_nc(self.ctx), name)

	def test_close_needs_verification_result(self):
		"""FR-M12-09.2 / FR-M2-22: đóng NC Compliance phải có kết quả xác minh."""
		name = incidents.on_compliance_nc(self.ctx)
		frappe.db.set_value("Incident CAPA", name, "status", "Verification")
		with self.assertRaises(BlockedError) as caught:
			incidents.close(name, " ")
		self.assertEqual(caught.exception.block.code, "VERIFICATION_REQUIRED")
		incidents.close(name, "Re-audit passed")
		self.assertEqual(frappe.db.get_value("Incident CAPA", name, "status"), "Closed")
