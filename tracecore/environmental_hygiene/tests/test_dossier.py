"""Phần "giám sát môi trường" của gói hồ sơ KSNK (FEAT-074; FR-M9-30; A-152)."""

import frappe

from tracecore.core import dossier as core_dossier
from tracecore.environmental_hygiene import dossier
from tracecore.tests.utils import IsolatedTestCase


def sample(sampled_on, docstatus=1, result="Pass"):
	doc = frappe.get_doc(
		{
			"doctype": "Environmental Sample",
			"sampled_on": sampled_on,
			"sample_type": "Surface",
			"method": "Culture",
			"result": result,
			"docstatus": docstatus,
		}
	)
	doc.db_insert()
	return doc


class TestEnvironmentDossier(IsolatedTestCase):
	def test_submitted_samples_in_range(self):
		inside = sample("2026-02-28 16:00:00", result="Fail")
		sample("2026-02-10 08:00:00", docstatus=0)
		sample("2026-03-01 08:00:00")
		rows = dossier.sample_rows(core_dossier.context("2026-01", "2026-02"))
		self.assertEqual([row.name for row in rows], [inside.name])
		self.assertEqual(rows[0].result, "Fail")
		self.assertTrue(core_dossier.check_section(dossier.register()[0]))
