"""Cluster Alert Rule (FEAT-069, A-150). Luật ở ``microbiology.clusters``."""

from frappe.model.document import Document

from tracecore.microbiology import clusters


class ClusterAlertRule(Document):
	def validate(self):
		clusters.validate_rule(self)
