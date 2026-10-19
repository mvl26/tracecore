# Hàm dùng chung cho scripts/install_*.sh và restore.sh (source, không chạy trực tiếp).
# DRY_RUN=1 → chỉ in lệnh. Mật khẩu trong lệnh được che bằng *** khi in.

DRY_RUN=${DRY_RUN:-0}

log() { printf '==> %s\n' "$*"; }

mask() {
	local line=$1 secret
	for secret in "${DB_ROOT_PASSWORD:-}" "${ADMIN_PASSWORD:-}"; do
		[ -n "$secret" ] && line=${line//"$secret"/***}
	done
	printf '%s\n' "$line"
}

run() {
	mask "+ $(printf '%q ' "$@")"
	if [ "$DRY_RUN" != "1" ]; then
		"$@"
	fi
}

# Chạy bước chỉ khi điều kiện kiểm tra (lệnh thứ nhất) KHÔNG thỏa → script idempotent
unless() {
	local check=$1
	shift
	if [ "$DRY_RUN" != "1" ] && eval "$check" >/dev/null 2>&1; then
		log "skip (already done): $*"
		return 0
	fi
	run "$@"
}

verify_pin() {
	local app=$1 expected=$2 actual
	[ "$DRY_RUN" = "1" ] && return 0
	actual=$(git -C "apps/$app" rev-parse HEAD)
	if [ "$actual" != "$expected" ]; then
		log "WARNING: $app is at $actual, pinned $expected"
	fi
}
