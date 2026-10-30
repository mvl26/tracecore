from tracecore_agent.jobqueue import MAX_ATTEMPTS, PrintQueue


def test_queue_fifo(tmp_path):
	queue = PrintQueue(tmp_path / "q.sqlite3")
	first = queue.enqueue("^XA1^XZ")
	second = queue.enqueue("^XA2^XZ", preview_png=b"png", print_job="7")
	assert queue.depth() == 2
	assert queue.claim_next().id == first
	job = queue.claim_next()
	assert (job.id, job.preview_png, job.print_job) == (second, b"png", "7")
	assert queue.claim_next() is None


def test_queue_retry_then_failed(tmp_path):
	queue = PrintQueue(tmp_path / "q.sqlite3")
	job_id = queue.enqueue("^XA^XZ")
	statuses = []
	for _ in range(MAX_ATTEMPTS):
		job = queue.claim_next()
		assert job.id == job_id
		statuses.append(queue.mark_failed(job_id, "timeout"))
	assert statuses == ["pending"] * (MAX_ATTEMPTS - 1) + ["failed"]
	assert queue.claim_next() is None
	assert queue.get(job_id).attempts == MAX_ATTEMPTS


def test_queue_mark_done(tmp_path):
	queue = PrintQueue(tmp_path / "q.sqlite3")
	job_id = queue.enqueue("^XA^XZ")
	queue.claim_next()
	queue.mark_done(job_id, "/tmp/x.zpl")
	job = queue.get(job_id)
	assert (job.status, job.output_ref) == ("done", "/tmp/x.zpl")
	assert queue.depth() == 0


def test_queue_survives_restart(tmp_path):
	path = tmp_path / "q.sqlite3"
	job_id = PrintQueue(path).enqueue("^XA^XZ")
	assert PrintQueue(path).claim_next().id == job_id


def test_queue_adds_printer_column_to_old_db(tmp_path):
	import sqlite3

	path = tmp_path / "old.sqlite3"
	db = sqlite3.connect(path)
	db.execute(
		"create table jobs (id text primary key, created real not null, zpl text not null, "
		"preview_png blob, print_job text, status text not null default 'pending', "
		"attempts integer not null default 0, output_ref text, error text)"
	)
	db.execute("insert into jobs (id, created, zpl) values ('old', 1.0, '^XA^XZ')")
	db.commit()
	db.close()
	queue = PrintQueue(path)
	assert queue.get("old").printer is None
	new_id = queue.enqueue("^XA^XZ", printer="PRN-001")
	assert queue.get(new_id).printer == "PRN-001"
	assert queue.claim_next().id == "old"
