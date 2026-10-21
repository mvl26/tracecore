# FEAT-003 RBAC, tài khoản và xác thực trạm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. TDD bắt buộc: test đỏ trước, hiện thực tối thiểu, rồi test xanh.

**Goal:** Cấp đúng quyền R01–R10 theo ma trận SEC #13; cho nhân viên đăng nhập trạm bằng thẻ khi năng lực còn hiệu lực; quản lý phiên 8 giờ, khóa idle 10 phút, một thẻ–một phiên; xác minh PIN và vận hành tài khoản web an toàn.

**Architecture:** Logic xác thực trạm nằm ở `tracecore.core.station_auth`; API ở `tracecore.v1.station`. HRMS `Employee` được mở rộng bằng Custom Field. `Station Competency` và `Station Session` là DocType nền thuộc module `TraceCore`; FEAT-037 mở rộng ma trận năng lực/chứng chỉ. Quyền sinh từ một nguồn chuẩn `permission_matrix.csv`; amendment mới hơn thắng ma trận BA v1.10.

**Tech Stack:** Frappe/ERPNext/HRMS v15, Python 3.11, Redis, bcrypt/passlib, Page `station`, Playwright Python.

**Spec:** `docs/implementation-plan.md` FEAT-003; `docs/srs.md` FR-M9-05, FR-M9-08, FR-M9-09, FR-M4-01 (partial), FR-M4-03 (partial), BRU-HR-001, NFR-SEC-01/03/08; `docs/architecture.md` §5.3.1, §6 Security, ADR-010; BA #13 SEC §3–§4; UC-20, UC-33; SCR-33 và shell STN/PDA.

**Nhánh/môi trường:** `feat/FEAT-003-rbac-station-auth` tại bench độc lập `~/tracecore-codex`, base `183c7a2`. Không sửa `~/tracecore-dev`, không lấy thay đổi chưa commit của FEAT-005.

## Quyết định triển khai A-06

| # | Quyết định | Áp dụng |
| :- | :- | :- |
| A1 | Ma trận #13 là baseline; amendment FEAT-002/038 và audit bất biến thắng khi xung đột. DocType chưa tồn tại chưa sinh `Custom DocPerm`; dòng matrix vẫn được test. | Task 1 |
| A2 | R01/R02/R09/R10 đăng nhập WEB bằng User + 2FA; trạm dùng mã thẻ + PIN khi thao tác đặc quyền. | Task 2, 5 |
| A3 | `tc_card_id` duy nhất, trim/uppercase; `tc_pin_hash` là Password chứa bcrypt hash, không audit/serialize. | Task 2, 5 |
| A4 | Phiên dùng opaque bearer token chỉ trả một lần; DB chỉ lưu SHA-256. Phiên tuyệt đối 8 giờ, idle server 10 phút. RPC không tin `employee` do client gửi. | Task 3, 4 |
| A5 | Mỗi Employee chỉ có một Station Session mở. Login mới đóng phiên cũ trong cùng transaction và ghi audit. | Task 3, 6 |
| A6 | FEAT-003 tạo competency khung: hiệu lực trực tiếp hoặc tạm tối đa 24 giờ; kiểm chứng chỉ chỉ chạy khi có requirement. UI đầy đủ thuộc FEAT-036/037. | Task 2, 3 |
| A7 | PIN đúng 6 chữ số; sai 3 lần khóa 5 phút trong Redis theo Employee; không ghi PIN/hash/token. | Task 3, 4 |
| A8 | Password tối thiểu 10 ký tự, khóa sau 5 lần sai, hết hạn 90 ngày; reset bắt đổi lần sau, không gửi/lưu mật khẩu rõ. | Task 5 |

## Global constraints và review focus

- Không import chéo M1–M10; không xóa User/Employee/Session/Competency/Audit.
- API lỗi có mã ổn định; chuỗi qua `_()`/`__()`.
- Mọi BRU trong scope có test `@bru`; coverage changed-code ≥ 70%; pre-commit và architecture check sạch.
- Security focus: replay token, token plaintext, race hai login, expiry/idle, Employee disabled, client-supplied user, enumeration thẻ, brute-force PIN, quyền ngoài matrix.

### Task 0: Amendment A-06 và truy vết

**Files:** Modify `docs/architecture.md`, `docs/srs.md`; create this plan.

- [ ] Ghi Revision History A-06: A1–A8, không thêm FR/BRU mới.
- [ ] Làm rõ token hash, absolute/idle expiry, competency khung và precedence quyền.
- [ ] Lint docs; commit `docs: amendment A-06 cho FEAT-003`.

### Task 1: Ma trận RBAC R01–R10

**Files:** Create `tracecore/fixtures/permission_matrix.csv`, `tracecore/setup/permissions.py`, `tracecore/fixtures/custom_docperm.json`, `tracecore/tests/test_permissions.py`; modify role fixture/hooks.

- [ ] Test đỏ: đủ 10 role, không ô/DocType trùng, chỉ R/W/S/A; đối chiếu mọi DocType hiện hữu; không role nghiệp vụ có delete; Audit Log bất biến; amendment Zone/Equipment thắng baseline.
- [ ] Generator deterministic R/W/S/A → quyền Frappe; báo cáo DocType chưa tồn tại; fixture sinh lại byte-for-byte.
- [ ] Bật 2FA cho R01/R02/R09/R10; test permission theo user R01/R02/R04/R09/R10.
- [ ] Commit `feat(auth): ma trận RBAC R01-R10 từ SEC #13`.

### Task 2: Employee extension và DocType năng lực/phiên

**Files:** Modify custom fields/hooks; create `station_competency/*`, `station_session/*`, tests, translations.

- [ ] Test đỏ Employee fields: `tc_card_id` unique, `tc_pin_hash` Password/no_copy/hidden, `tc_card_enabled`; fixture bao gồm Employee.
- [ ] Test `Station Competency`: Employee + Station + hiệu lực; temporary cần reason/approved_by, tối đa 24 h; không delete; R02/R10 manage.
- [ ] Test `Station Session`: employee/user/station/start/last_activity/absolute_expires/end/reason/token_hash; token hidden; open-session uniqueness; audit/no delete.
- [ ] Implement, migrate hai site; commit `feat(auth): khung năng lực và phiên đăng nhập trạm`.

### Task 3: `core.station_auth` theo TDD

**Files:** Create station auth service/tests; modify errors, audit hooks, translations.

- [ ] `@bru("BRU-HR-001")`: thẻ + competency đúng trạm/còn hạn mở phiên; thiếu/sai/hết hạn/inactive/card disabled từ chối rõ và audit Reject.
- [ ] Test session 8 h, idle 10 phút, heartbeat; expired/ended/token sai; DB/audit không có plaintext token.
- [ ] Test race/một thẻ–một phiên: khóa hàng, đóng phiên cũ `Replaced`, chỉ một phiên mở.
- [ ] Test PIN bcrypt, sai lần 3 khóa Redis 5 phút, unlock; không enumeration/log secret.
- [ ] Implement `login`, `authenticate_session`, `heartbeat`, `logout`, `verify_pin`, `close_employee_sessions`; commit.

### Task 4: API station và guard RPC

**Files:** Modify `v1/station.py`, `_common.py`, station/pack/agent tests; create security tests.

- [ ] Test POST `login/logout/heartbeat/verify_pin`: schema, HTTP/mã lỗi, client_ts, audit/idempotency.
- [ ] Login nhận `card_id`, `station`; trả token một lần + display/role/expires, không trả secret.
- [ ] API sau login nhận token; verify_pin trả proof TTL ngắn cho thao tác đặc quyền.
- [ ] Guard RPC trạm nhưng giữ luồng `TC Agent`; Pack T4 lấy `packed_by` từ session, không client; regression FEAT-018.
- [ ] Commit `feat(v1): API phiên và xác minh PIN trạm`.

### Task 5: Vận hành tài khoản web và vô hiệu nhân viên

**Files:** Create `core/account.py`, tests; modify hooks/install/provision/settings/translations.

- [ ] Test password min 10, expiry 90 ngày, khóa sau 5; 2FA đúng role.
- [ ] Đổi PIN/password yêu cầu giá trị cũ và audit không secret; reset bởi R10 hoặc R02 có proof, bắt đổi lần sau.
- [ ] Employee nghỉ việc: card/User disabled, mọi session đóng; lịch sử audit giữ nguyên.
- [ ] Test chỉ R10 tạo/vô hiệu User; commit.

### Task 6: Shell trạm đăng nhập, idle lock, logout

**Files:** Modify Page `station`, `station_t4.js`, tests; create Playwright tests.

- [ ] UI kiosk/PDA: chưa có phiên chỉ hiện quét thẻ; success hiện người/trạm/hạn; lỗi inline có lý do/hành động.
- [ ] Idle 10 phút khóa/xóa state; logout/rút/quét lại thẻ kết thúc session; server expiry ép về login.
- [ ] Token chỉ ở memory/sessionStorage, không localStorage; calls truyền token an toàn.
- [ ] Test login trạm thứ hai khiến trạm cũ heartbeat bị từ chối; commit.

### Task 7: Devdata, regression và bàn giao review

**Files:** Modify devdata/e2e prepare/tests, RTM nếu cần.

- [ ] Seed demo Employee/card/competency idempotent, không secret production cố định.
- [ ] Migrate/build dev; unit/integration toàn app; Playwright login → T4 → logout.
- [ ] Chạy coverage, diff-cover ≥70, pre-commit, architecture và BRU checks.
- [ ] Lập bảng AC → evidence cho toàn FR/BRU scope.
- [ ] Dừng ở nhánh đã verify; không merge/deploy; xin review trước PR/cherry-pick.
