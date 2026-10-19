#!/usr/bin/env bash
# Cài production on-prem TraceCore trên VM Ubuntu 22.04 (ADR-011, NFR-PORT-01 <= 4 giờ). Idempotent.
# CHỈ VIẾT SẴN — chạy thật ở bước initial-deployment; trong skeleton chỉ dùng --dry-run để review.
#
#   scripts/install_prod.sh --env /etc/tracecore/prod.env [--dry-run]
#
# File env (ngoài repo, quyền 600 — mẫu deploy/staging.env.example):
#   SITE_NAME, TRACECORE_REF (tag release), BENCH_DIR, FRAPPE_USER,
#   DB_ROOT_PASSWORD, ADMIN_PASSWORD, TC_GS1_COMPANY_PREFIX, BACKUP_DIR
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=../deploy/pins.env
. "$HERE/deploy/pins.env"
# shellcheck source=lib.sh
. "$HERE/scripts/lib.sh"

ENV_FILE=""
while [ $# -gt 0 ]; do
	case "$1" in
	--dry-run) DRY_RUN=1 ;;
	--env)
		ENV_FILE=$2
		shift
		;;
	*)
		echo "usage: $0 --env FILE [--dry-run]" >&2
		exit 2
		;;
	esac
	shift
done

if [ -n "$ENV_FILE" ]; then
	# shellcheck disable=SC1090
	. "$ENV_FILE"
elif [ "$DRY_RUN" != "1" ]; then
	echo "--env FILE is required (except with --dry-run)" >&2
	exit 2
fi
if [ "$DRY_RUN" = "1" ]; then
	SITE_NAME=${SITE_NAME:-tracecore.example.internal}
	TRACECORE_REF=${TRACECORE_REF:-v0.1.0}
	DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD:-__DB_ROOT_PASSWORD__}
	ADMIN_PASSWORD=${ADMIN_PASSWORD:-__ADMIN_PASSWORD__}
	TC_GS1_COMPANY_PREFIX=${TC_GS1_COMPANY_PREFIX:-9520000}
fi
: "${SITE_NAME:?}" "${TRACECORE_REF:?}" "${DB_ROOT_PASSWORD:?}" "${ADMIN_PASSWORD:?}" "${TC_GS1_COMPANY_PREFIX:?}"
FRAPPE_USER=${FRAPPE_USER:-frappe}
BENCH_DIR=${BENCH_DIR:-/home/$FRAPPE_USER/tracecore-bench}
BACKUP_DIR=${BACKUP_DIR:-/backup/tracecore}

log "1/8 kiểm tra hệ điều hành"
if [ "$DRY_RUN" != "1" ]; then
	grep -q 'VERSION_ID="22.04"' /etc/os-release || {
		echo "Ubuntu 22.04 required" >&2
		exit 1
	}
	[ "$(id -un)" = "$FRAPPE_USER" ] || {
		echo "run as $FRAPPE_USER (sudo-capable), not root" >&2
		exit 1
	}
fi

log "2/8 gói hệ thống (MariaDB $MARIADB_VERSION, Redis, nginx, supervisor, libdmtx)"
for pkg in git curl mariadb-server mariadb-client redis-server nginx supervisor libdmtx0b \
	python3.11 python3.11-venv python3.11-dev build-essential xvfb libfontconfig cron; do
	unless "dpkg -s $pkg" sudo apt-get install -y "$pkg"
done
unless "command -v node" sudo bash -c "curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | bash - && apt-get install -y nodejs"
unless "command -v yarn" sudo npm install -g yarn
unless "command -v bench" pip3 install --user "frappe-bench==$BENCH_VERSION"

log "3/8 MariaDB utf8mb4 + binlog ROW (RPO 15 phút, NFR-BACKUP-01)"
unless "test -f /etc/mysql/mariadb.conf.d/90-tracecore.cnf" sudo cp "$HERE/deploy/mariadb/90-tracecore.cnf" /etc/mysql/mariadb.conf.d/
run sudo systemctl restart mariadb

log "4/8 bench + apps theo pin"
unless "test -d '$BENCH_DIR/apps/frappe'" \
	bench init --frappe-branch "$FRAPPE_REF" --python python3.11 "$BENCH_DIR"
[ "$DRY_RUN" = "1" ] || cd "$BENCH_DIR"
unless "test -d apps/erpnext" bench get-app --branch "$ERPNEXT_REF" "$ERPNEXT_REPO"
unless "test -d apps/hrms" bench get-app --branch "$HRMS_REF" "$HRMS_REPO"
unless "test -d apps/tracecore" bench get-app --branch "$TRACECORE_REF" "$TRACECORE_REPO"
verify_pin frappe "$FRAPPE_SHA"
verify_pin erpnext "$ERPNEXT_SHA"
verify_pin hrms "$HRMS_SHA"

log "5/8 site $SITE_NAME"
unless "test -d 'sites/$SITE_NAME'" \
	bench new-site "$SITE_NAME" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$ADMIN_PASSWORD"
for app in erpnext hrms tracecore; do
	unless "bench --site '$SITE_NAME' list-apps | grep -q '^$app'" bench --site "$SITE_NAME" install-app "$app"
done
run bench --site "$SITE_NAME" set-config tc_gs1_company_prefix "$TC_GS1_COMPANY_PREFIX"
unless "bench --site '$SITE_NAME' show-config | grep -q tc_patient_key" \
	bash -c "bench --site '$SITE_NAME' set-config tc_patient_key \"\$(openssl rand -base64 32)\""
run bench --site "$SITE_NAME" enable-scheduler
run bench use "$SITE_NAME"

log "6/8 build + production (nginx + supervisor)"
run bench build --production
run sudo bench setup production "$FRAPPE_USER" --yes
run bench setup nginx --yes
run sudo systemctl reload nginx

log "7/8 sao lưu hằng ngày 02:00 (bench backup --with-files) vào $BACKUP_DIR"
run sudo mkdir -p "$BACKUP_DIR"
run sudo chown "$FRAPPE_USER" "$BACKUP_DIR"
CRON_LINE="0 2 * * * cd $BENCH_DIR && bench --site $SITE_NAME backup --with-files --backup-path $BACKUP_DIR >> $BENCH_DIR/logs/backup.log 2>&1"
unless "crontab -l | grep -qF 'backup --with-files --backup-path $BACKUP_DIR'" \
	bash -c "(crontab -l 2>/dev/null; echo '$CRON_LINE') | crontab -"

log "8/8 kiểm tra"
run bench --site "$SITE_NAME" execute tracecore.v1.ping
log "done - còn lại theo checklist initial-deployment: TLS nội bộ, restic offsite, Prometheus, agent trạm"
