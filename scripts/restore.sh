#!/usr/bin/env bash
# Khôi phục site TraceCore từ backup bench + replay binlog tới thời điểm cần (ADR-011, NFR-BACKUP-01/02).
# CHỈ VIẾT SẴN — diễn tập hằng quý trên staging; trong skeleton chỉ dùng --dry-run.
#
#   scripts/restore.sh --site SITE --db BACKUP.sql.gz [--public FILES.tar] [--private FILES.tar]
#                      [--binlog-dir DIR --from "YYYY-MM-DD HH:MM:SS" --until "YYYY-MM-DD HH:MM:SS"] [--dry-run]
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=lib.sh
. "$HERE/scripts/lib.sh"

SITE="" DB="" PUBLIC="" PRIVATE="" BINLOG_DIR="" FROM="" UNTIL=""
while [ $# -gt 0 ]; do
	case "$1" in
	--site) SITE=$2 && shift ;;
	--db) DB=$2 && shift ;;
	--public) PUBLIC=$2 && shift ;;
	--private) PRIVATE=$2 && shift ;;
	--binlog-dir) BINLOG_DIR=$2 && shift ;;
	--from) FROM=$2 && shift ;;
	--until) UNTIL=$2 && shift ;;
	--dry-run) DRY_RUN=1 ;;
	*)
		echo "unknown option $1" >&2
		exit 2
		;;
	esac
	shift
done
: "${SITE:?--site required}" "${DB:?--db required}"
BENCH_DIR=${BENCH_DIR:-$HOME/tracecore-bench}
[ "$DRY_RUN" = "1" ] || cd "$BENCH_DIR"

log "1/3 bật chế độ bảo trì"
run bench --site "$SITE" set-maintenance-mode on

log "2/3 restore dump + file"
args=(bench --site "$SITE" restore "$DB")
[ -n "$PUBLIC" ] && args+=(--with-public-files "$PUBLIC")
[ -n "$PRIVATE" ] && args+=(--with-private-files "$PRIVATE")
run "${args[@]}"

if [ -n "$BINLOG_DIR" ]; then
	: "${FROM:?--from required with --binlog-dir}" "${UNTIL:?--until required with --binlog-dir}"
	log "3/3 replay binlog $FROM -> $UNTIL (RPO <= 15 phút)"
	db_name=$([ "$DRY_RUN" = "1" ] && echo "<db_name>" || bench --site "$SITE" show-config --format json | python3 -c "import json,sys; print(json.load(sys.stdin)['$SITE']['db_name'])")
	run bash -c "mysqlbinlog --start-datetime='$FROM' --stop-datetime='$UNTIL' '$BINLOG_DIR'/mariadb-bin.[0-9]* | mariadb -u root -p '$db_name'"
else
	log "3/3 bỏ qua binlog (không có --binlog-dir)"
fi

run bench --site "$SITE" migrate
run bench --site "$SITE" set-maintenance-mode off
log "done - kiểm tra: bench --site $SITE execute tracecore.v1.ping, đối chiếu số Audit Log cuối"
