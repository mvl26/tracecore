"""Hàng đợi in cục bộ trên SQLite: không mất lệnh in khi máy in/mạng lỗi, thử lại tối đa 3 lần."""

import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

MAX_ATTEMPTS = 3

_SCHEMA = """
create table if not exists jobs (
	id text primary key,
	created real not null,
	zpl text not null,
	preview_png blob,
	print_job text,
	status text not null default 'pending',
	attempts integer not null default 0,
	output_ref text,
	error text
)
"""


@dataclass
class Job:
	id: str
	zpl: str
	preview_png: bytes | None
	print_job: str | None
	status: str
	attempts: int
	output_ref: str | None
	error: str | None


class PrintQueue:
	def __init__(self, db_path):
		self.db_path = str(db_path)
		os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
		self._lock = threading.Lock()
		with self._connect() as db:
			db.execute(_SCHEMA)
			# lệnh đang in dở khi agent dừng đột ngột → trả về hàng đợi
			db.execute("update jobs set status = 'pending' where status = 'printing'")

	def _connect(self):
		return sqlite3.connect(self.db_path, timeout=10)

	def enqueue(self, zpl, preview_png=None, print_job=None):
		job_id = str(uuid.uuid4())
		with self._lock, self._connect() as db:
			db.execute(
				"insert into jobs (id, created, zpl, preview_png, print_job) values (?, ?, ?, ?, ?)",
				(job_id, time.time(), zpl, preview_png, print_job),
			)
		return job_id

	def claim_next(self):
		with self._lock, self._connect() as db:
			row = db.execute(
				"select id from jobs where status = 'pending' order by created, rowid limit 1"
			).fetchone()
			if not row:
				return None
			db.execute("update jobs set status = 'printing' where id = ?", row)
		return self.get(row[0])

	def mark_done(self, job_id, output_ref):
		with self._lock, self._connect() as db:
			db.execute(
				"update jobs set status = 'done', output_ref = ?, error = null where id = ?",
				(output_ref, job_id),
			)

	def mark_failed(self, job_id, error):
		"""Tăng số lần thử; đủ MAX_ATTEMPTS → ``failed``, chưa đủ → ``pending``. Trả trạng thái mới."""
		with self._lock, self._connect() as db:
			(attempts,) = db.execute("select attempts from jobs where id = ?", (job_id,)).fetchone()
			attempts += 1
			status = "failed" if attempts >= MAX_ATTEMPTS else "pending"
			db.execute(
				"update jobs set status = ?, attempts = ?, error = ? where id = ?",
				(status, attempts, str(error), job_id),
			)
		return status

	def get(self, job_id):
		with self._connect() as db:
			row = db.execute(
				"select id, zpl, preview_png, print_job, status, attempts, output_ref, error from jobs where id = ?",
				(job_id,),
			).fetchone()
		return Job(*row) if row else None

	def depth(self):
		with self._connect() as db:
			return db.execute("select count(*) from jobs where status in ('pending', 'printing')").fetchone()[
				0
			]
