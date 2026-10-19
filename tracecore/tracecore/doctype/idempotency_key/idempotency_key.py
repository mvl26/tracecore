"""Idempotency Key: bản ghi khóa idempotent của RPC (ghi bởi tracecore.core.idempotency)."""

from frappe.model.document import Document


class IdempotencyKey(Document):
	pass
