# TraceCore — hướng dẫn cho Claude Code

App Frappe v15 `tracecore` (cạnh `erpnext`, `hrms`) quản lý khoa KSNK/CSSD: truy xuất dụng cụ qua 8 trạm T1–T8 với cổng kiểm soát 5 bước, Set ID GS1 GIAI, Cycle ID GS1 DataMatrix, đồ vải, nhân sự, thiết bị, kho, chi phí, cơ số, báo cáo, chất thải y tế. Bốn surface: WEB (Desk), STN (kiosk, Page `station`), PDA (PWA cùng Page), DEPT (Portal).

Trả lời người dùng bằng tiếng Việt; thuật ngữ kỹ thuật giữ tiếng Anh (DocType, RPC, hook, Page, PWA…).

## Nguồn sự thật — đọc trước khi làm

| File | Dùng khi |
| --- | --- |
| `docs/srs.md` | Yêu cầu FR/NFR, BRU (Appendix A), quyết định phạm vi (Appendix C) |
| `docs/use-cases.md` | Luồng nghiệp vụ UC-01..39, ma trận UC → FR |
| `docs/architecture.md` | Module, DocType (§5.3), naming series (§5.3.3), runtime, 14 ADR |
| `docs/ux-foundations.md` | 4 surface, 43 màn SCR, luồng, anchor screens |
| `docs/design.md` + `docs/tokens.json` | Mọi giá trị giao diện; khi lệch nhau `tokens.json` thắng |
| `docs/implementation-plan.md` | 50 FEAT, thứ tự sprint, acceptance criteria, engineering foundations F-1..F-20 |
| `docs/rtm.md` | Truy vết FR/NFR → UC → SCR → FEAT |

- Tài liệu mâu thuẫn nhau hoặc thiếu thông tin → dừng lại hỏi, không tự chọn.
- Thay đổi yêu cầu hoặc kiến trúc (DocType mới ngoài architecture §5.3, đổi ADR) phải qua amendment và cập nhật Revision History trước khi code.
- SCR-44..46 là đề xuất chưa duyệt: không hiện thực.

## Quy trình làm việc (Superpowers)

- **Không chạy `brainstorming`** cho FEAT đã có trong `implementation-plan.md`: thiết kế đã được chủ đầu tư duyệt. Không viết spec mới trong `docs/superpowers/specs/`. Chỉ brainstorm khi việc nằm ngoài tài liệu, và kết quả ghi là đề xuất amendment.
- **Lập kế hoạch theo FEAT** bằng `writing-plans`, đầu vào là mục FEAT trong implementation-plan §3, acceptance criteria EARS và handoff detailed-design / ui-design. Lưu tại `docs/superpowers/plans/FEAT-NNN-<slug>.md`. Mỗi task ghi rõ FR / BRU / AC mà nó đáp ứng.
- **Không dùng git worktree.** App phải nằm ở `apps/tracecore` trong bench thì mới chạy được `bench run-tests`. Làm trên nhánh `feat/FEAT-NNN-<slug>` ngay trong `apps/tracecore`.
- **TDD bắt buộc** (`test-driven-development`): viết test `FrappeTestCase` trước, thấy fail, rồi mới code. Mỗi BRU có ít nhất 1 test gắn marker `@bru("BRU-XXX-NNN")`.
- **Xong** nghĩa là: test pass, coverage changed-code ≥ 70 %, lint sạch, mọi AC của FEAT đạt. Chạy lệnh thật và dán kết quả trước khi báo xong.
- **Kết thúc nhánh**: mở PR vào `main` (Conventional Commits). Không merge thẳng; `main` cần CI xanh và 1 review.

## Môi trường và lệnh

Frappe/ERPNext/HRMS nhánh `version-15`, Python 3.11, Node 18, MariaDB 10.6, Redis 7. **Không lên v16.**

Bench dev nằm trong WSL `Ubuntu-22.04` tại `~/tracecore-dev`: site dev `<SITE>` = `tracecore-dev.local` (developer_mode), site test `<TEST_SITE>` = `test_site` (allow_tests). Mật khẩu DB root và Administrator của môi trường dev ở `~/.tracecore-dev-secrets`, không in ra chat, không commit. Khi Claude chạy từ Windows, gọi lệnh bench qua `wsl -d Ubuntu-22.04 -- bash -lc "cd ~/tracecore-dev && …"`.

```bash
# Một lần cho site test
bench --site <TEST_SITE> set-config allow_tests true

# Test toàn app / một module
bench --site <TEST_SITE> run-tests --app tracecore --coverage
bench --site <TEST_SITE> run-tests --module tracecore.<module>.doctype.<doctype>.test_<doctype>

# Coverage changed-code (ngưỡng CI)
diff-cover coverage.xml --compare-branch=origin/main --fail-under=70

# Sau khi đổi DocType / fixtures / assets
bench --site <SITE> migrate
bench build --app tracecore

# Lint (pre-commit chạy đủ: ruff, eslint/prettier, bandit, check_bru_coverage)
pre-commit run --all-files
```

- E2E: Playwright for Python (`pytest-playwright`), viewport kiosk 1366×768 và PDA 412×915, offline bằng `context.set_offline(True)`. Không dùng Cypress.
- Tokens: `scripts/build_tokens.py` sinh `tracecore/public/css/tokens.css` từ `docs/tokens.json` (F-11). Không sửa tay `tokens.css`.

## Quy tắc kiến trúc — không được vi phạm

- Module Frappe = phân hệ: `core`, `instrument` (M1), `reprocessing` (M2), `linen` (M3), `hr` (M4), `equipment` (M5), `inventory` (M6), `costing` (M7), `par` (M8), `admin_reports` (M9), `waste` (M10), `ui`.
- Không import chéo giữa M1–M10; chỉ đi qua `core` hoặc Link/hook.
- **Chỉ `core.step_gate` được đổi trạng thái Set Unit / chuyển bước.** Không `set_value('Set Unit', …, 'status')` ở nơi khác. Frappe Workflow chỉ để hiển thị.
- Chứng từ đi Nháp → Ghi sổ → Hủy, không xóa (`is_submittable=1`). `Audit Log` append-only, cấm delete ở permission và hook.
- RPC đặt tên `tracecore.v1.<domain>.<action>`. Mọi RPC ghi của trạm/PDA dùng `@idempotent` với `X-Idempotency-Key`; `client_ts` là ISO 8601 có offset.
- Tận dụng ERPNext/HRMS (Item/Batch/Stock Entry, Asset, Quality, Employee, Department = khoa). Không tạo DocType trùng chức năng.
- Mã GS1 và DataMatrix sinh tại server qua `core.gs1`. Naming series theo architecture §5.3.3.
- Mã bệnh nhân lưu trường Password (AES), không ghi ra log.
- Mọi chuỗi hiển thị qua `_()`; không hard-code tiếng Việt ngoài `_()`; bản dịch ở `translations/vi.csv`, thuật ngữ theo QĐ 3671/QĐ-BYT. Ngày `dd/mm/yyyy`, 24 h, dấu phẩy thập phân, VND không lẻ, `Asia/Ho_Chi_Minh`.
- Không xây SPA Vue riêng; UI là Desk, Page `station`, PWA, Portal (ADR-002).
- Không tích hợp HIS/EMR. Không chạy deploy production (`install_prod.sh` chỉ viết, không chạy).

## Quy tắc giao diện (tóm tắt `docs/design.md`)

- Chỉ dùng token `--tc-*`. Không gõ hex/px trực tiếp, không thêm màu ngoài palette.
- Font Arial / Segoe UI; mã định danh (Set ID, Cycle ID, mã lô) dùng Courier New. Không web font, không icon font tải mạng, không ảnh nền trang trí, không gradient. Card phẳng, chỉ modal/toast có bóng. Motion chỉ 120/200 ms và tắt khi `prefers-reduced-motion`.
- STN/PDA: chữ ≥ 16 px, nút ≥ 48 px (nút chính 56 px), khoảng cách ≥ 12 px, ≤ 3 chạm sau quét. Không hover-only, swipe, long-press, drag.
- Trạng thái không chỉ bằng màu: badge, gate, stepper luôn có chữ hoặc ký hiệu. Chữ trắng trên cam dùng `--tc-warn-fill` (#B85A00), trên xám dùng `--tc-neutral-fill` (#6B6B6B).
- Lỗi chặn nghiệp vụ: `alert-error` inline đỏ toàn khối, theo thứ tự kết quả → lý do → hành động. Không dùng modal hay toast cho lỗi chặn.
- Màn trạm/PDA: ô quét luôn trên cùng và có focus; đủ 4 trạng thái loading / empty / error / offline (FR-M9-14).
- Desk: chỉ override biến CSS qua `tracecore-theme.css` (`app_include_css`); không sửa SCSS của Frappe.
- **Không dùng Taste Skill** hay skill "art direction" nào khác (đã tắt trong `.claude/settings.json`): design system đã được duyệt, không thiết kế lại.
