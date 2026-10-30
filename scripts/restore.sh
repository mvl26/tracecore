#!/usr/bin/env bash
# Khôi phục site TraceCore từ dump + file, rồi replay binlog tới thời điểm cần (ADR-011, NFR-BACKUP-01/02).
# CHỈ VIẾT SẴN — diễn tập hằng quý trên staging; trong skeleton chỉ dùng --dry-run.
#
#   scripts/restore.sh --site SITE --db DUMP.sql.gz [--public FILES.tar] [--private FILES.tar]
#                      [--binlog-dir DIR --until "YYYY-MM-DD HH:MM:SS"] [--dry-run]
#
# Replay binlog chỉ đúng khi biết tọa độ binlog tại thời điểm snapshot của dump: dump phải tạo bằng
#   mariadb-dump --single-transaction --master-data=2 ...
# (header có "-- CHANGE MASTER TO MASTER_LOG_FILE='…', MASTER_LOG_POS=…"). `bench backup` KHÔNG ghi tọa độ;
# initial-deployment phải thêm bước dump có tọa độ để đạt RPO <= 15 phút. Không có tọa độ → script từ chối
# replay (đoán theo giờ sẽ áp trùng dòng đã có trong dump).
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=lib.sh
. "$HERE/scripts/lib.sh"

SITE="" DB="" PUBLIC="" PRIVATE="" BINLOG_DIR="" UNTIL=""
while [ $# -gt 0 ]; do
	case "$1" in
	--site) SITE=$2 && shift ;;
	--db) DB=$2 && shift ;;
	--public) PUBLIC=$2 && shift ;;
	--private) PRIVATE=$2 && shift ;;
	--binlog-dir) BINLOG_DIR=$2 && shift ;;
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

# Kiểm tra toàn bộ điều kiện TRƯỚC khi đụng vào site
START_FILE="" START_POS=""
if [ -n "$BINLOG_DIR" ]; then
	: "${UNTIL:?--until required with --binlog-dir}"
	coords=$(zcat -f -- "$DB" 2>/dev/null | head -n 60 |
		sed -n "s/^-- CHANGE MASTER TO MASTER_LOG_FILE='\([^']*\)', MASTER_LOG_POS=\([0-9]*\);.*/\1 \2/p" | head -n 1)
	if [ -z "$coords" ]; then
		echo "dump $DB has no binlog coordinates (needs mariadb-dump --master-data=2); refusing binlog replay" >&2
		exit 3
	fi
	read -r START_FILE START_POS <<<"$coords"
fi

[ "$DRY_RUN" = "1" ] || cd "$BENCH_DIR"

log "1/3 bật chế độ bảo trì"
run bench --site "$SITE" set-maintenance-mode on

log "2/3 restore dump + file"
args=(bench --site "$SITE" restore "$DB")
[ -n "$PUBLIC" ] && args+=(--with-public-files "$PUBLIC")
[ -n "$PRIVATE" ] && args+=(--with-private-files "$PRIVATE")
run "${args[@]}"

if [ -n "$BINLOG_DIR" ]; then
	log "3/3 replay binlog từ $START_FILE:$START_POS tới $UNTIL, chỉ database của site"
	if [ "$DRY_RUN" = "1" ]; then
		db_name="<db_name>"
	else
		db_name=$(bench --site "$SITE" show-config --format json |
			python3 -c "import json,sys; print(json.load(sys.stdin)['$SITE']['db_name'])")
	fi
	# --start-position áp cho file đầu tiên; các file sau đọc từ đầu
	run bash -c "cd '$BINLOG_DIR' && files=\$(ls mariadb-bin.[0-9]* | sort | awk -v s='$START_FILE' '\$0 >= s') &&
		mysqlbinlog --database='$db_name' --start-position=$START_POS --stop-datetime='$UNTIL' \$files |
		mariadb -u root -p '$db_name'"
else
	log "3/3 bỏ qua binlog (không có --binlog-dir)"
fi

run bench --site "$SITE" migrate
run bench --site "$SITE" set-maintenance-mode off
log "done - kiểm tra: bench --site $SITE execute tracecore.v1.ping, đối chiếu số Audit Log cuối"
