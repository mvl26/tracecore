"""IC Procedure Document — sổ văn bản nội bộ KSNK (FEAT-058; FR-M11-07; BRU-ICP-005). Logic ở ``procedure_documents``."""

from frappe.model.document import Document

from tracecore.infection_program import procedure_documents


class ICProcedureDocument(Document):
	def validate(self):
		procedure_documents.validate(self)

	def on_update(self):
		procedure_documents.on_update(self)
