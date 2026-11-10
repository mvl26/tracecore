"""Cluster Alert (FEAT-069, A-150). Luật ở ``microbiology.clusters``."""

from frappe.model.document import Document

from tracecore.microbiology import clusters


class ClusterAlert(Document):
	def validate(self):
		clusters.validate_alert(self)

	def on_trash(self):
		clusters.on_trash(self)
