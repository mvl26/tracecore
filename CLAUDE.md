# TraceCore — hướng dẫn cho Claude Code

App Frappe v15 `tracecore` (cạnh `erpnext`, `hrms`) quản lý khoa KSNK/CSSD: truy xuất dụng cụ qua 8 trạm T1–T8 với cổng kiểm soát 5 bước, Set ID GS1 GIAI, Cycle ID GS1 DataMatrix, đồ vải, nhân sự, thiết bị, kho, chi phí, cơ số, báo cáo, chất thải y tế. **Từ v1.12 (Amendment A-113, 2026-11-03):** 7 module KSNK toàn viện M11–M17 (chương trình KSNK, giám sát tuân thủ, giám sát NKBV, vi sinh–cách ly–ổ dịch, vệ sinh môi trường, an toàn nghề nghiệp, ATTP & truyền thông) + bảng chỉ số KSNK toàn viện ở M9; 13 vai trò R01–R13. Bốn surface: WEB (Desk), STN (kiosk, Page `station`), PDA (PWA cùng Page), DEPT (Portal).

Trả lời người dùng bằng tiếng Việt; thuật ngữ kỹ thuật giữ tiếng Anh (DocType, RPC, hook, Page, PWA…).

## Nguồn sự thật — đọc trước khi làm

| File | Dùng khi |
| --- | --- |
| `docs/srs.md` | Yêu cầu FR/NFR, BRU (Appendix A), quyết định phạm vi (Appendix C) |
| `docs/use-cases.md` | Luồng nghiệp vụ UC-01..57 (UC-40..57 = v1.12), ma trận UC → FR |
| `docs/architecture.md` | Module, DocType (§5.3), naming series (§5.3.3), runtime, 15 ADR (ADR-015 engine phiếu giám sát) |
| `docs/ux-foundations.md` | 4 surface, 63 màn SCR đã duyệt (SCR-47..66 = v1.12), luồng, anchor screens |
| `docs/design.md` + `docs/tokens.json` | Mọi giá trị giao diện; khi lệch nhau `tokens.json` thắng |
| `docs/implementation-plan.md` | 74 FEAT (FEAT-056..074 = v1.12, epic E-12..E-19, sprint S6–S9, DoD v1.12 §6.1), thứ tự sprint, acceptance criteria, engineering foundations F-1..F-22 |
| `docs/rtm.md` | Truy vết FR/NFR → UC → SCR → FEAT |

- Tài liệu mâu thuẫn nhau hoặc thiếu thông tin → dừng lại hỏi, không tự chọn.
- Thay đổi yêu cầu hoặc kiến trúc (DocType mới ngoài architecture §5.3, đổi ADR) phải qua amendment và cập nhật Revision History trước khi code.
- SCR-44..46 là đề xuất chưa duyệt: không hiện thực. SCR-47..66 đã duyệt theo A-113 (người dùng duyệt D1–D11 ngày 03/11/2026; chủ đầu tư chưa xác nhận).

## Quy trình làm việc (Superpowers)

- **Không chạy `brainstorming`** cho FEAT đã có trong `implementation-plan.md`: thiết kế đã được chủ đầu tư duyệt. Không viết spec mới trong `docs/superpowers/specs/`. Chỉ brainstorm khi việc nằm ngoài tài liệu, và kết quả ghi là đề xuất amendment.
- **Lập kế hoạch theo FEAT** bằng `writing-plans`, đầu vào là mục FEAT trong implementation-plan §3, acceptance criteria EARS và handoff detailed-design / ui-design. Lưu tại `docs/superpowers/plans/FEAT-NNN-<slug>.md`. Mỗi task ghi rõ FR / BRU / AC mà nó đáp ứng.
- **Không dùng git worktree.** App phải nằm ở `apps/tracecore` trong bench thì mới chạy được `bench run-tests`. Làm trên nhánh `feat/FEAT-NNN-<slug>` ngay trong `apps/tracecore`.
- **TDD bắt buộc** (`test-driven-development`): viết test `FrappeTestCase` trước, thấy fail, rồi mới code. Mỗi BRU có ít nhất 1 test gắn marker `@bru("BRU-XXX-NNN")`.
- **Xong** nghĩa là: test `FrappeTestCase` pass, coverage changed-code ≥ 70 %, lint sạch, mọi AC của FEAT đạt. Chạy lệnh thật và dán kết quả trước khi báo xong. **Không chạy E2E (Playwright)** trừ khi người dùng bảo chạy.
- **Kết thúc nhánh**: merge vào `develop` (Conventional Commits). **Không tự tạo Pull Request**; chỉ tạo PR khi người dùng bảo.

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
diff-cover coverage.xml --compare-branch=origin/develop --fail-under=70

# Sau khi đổi DocType / fixtures / assets
bench --site <SITE> migrate
bench build --app tracecore

# Lint (pre-commit chạy đủ: ruff, eslint/prettier, bandit, check_bru_coverage)
pre-commit run --all-files
```

- E2E: Playwright for Python (`pytest-playwright`), viewport kiosk 1366×768 và PDA 412×915, offline bằng `context.set_offline(True)`. Không dùng Cypress. Chỉ chạy khi người dùng bảo.
- Tokens: `scripts/build_tokens.py` sinh `tracecore/public/css/tokens.css` từ `docs/tokens.json` (F-11). Không sửa tay `tokens.css`.

## Quy tắc kiến trúc — không được vi phạm

- Module Frappe = phân hệ: `core`, `instrument` (M1), `reprocessing` (M2), `linen` (M3), `hr` (M4), `equipment` (M5), `inventory` (M6), `costing` (M7), `par` (M8), `admin_reports` (M9), `waste` (M10), `ui`; **v1.12 (A-113):** `infection_program` (M11, Module Def `Infection Program`), `compliance_audit` (M12, `Compliance Audit`), `hai_surveillance` (M13, `HAI Surveillance`), `microbiology` (M14, `Microbiology`), `environmental_hygiene` (M15, `Environmental Hygiene`), `occupational_safety` (M16, `Occupational Safety`), `food_safety` (M17, `Food Safety`). Không import chéo M1–M17; M12 là engine phiếu dùng chung — các module khác chỉ Link tới `Audit Template`/`Audit Session` hoặc đi qua hook.
- **Amendment 2026-10-19 (tên module, architecture §5.2):** Module Def `Core` đã thuộc frappe, `HR` đã thuộc hrms, nên không đăng ký trùng tên. Thực tế trong repo:
  - Dịch vụ `core` ở package Python thường `tracecore/core/` (giữ đường dẫn ADR: `tracecore.core.gs1`, `tracecore.core.audit`, `tracecore.core.idempotency.idempotent`, `tracecore.core.step_gate`…).
  - DocType nền xuyên suốt (Audit Log, Code Registry, Idempotency Key, Print Job…) ở module Frappe `TraceCore` (thư mục `tracecore/tracecore/`).
  - Zone Station ở `Admin Reports` (M9); Page `station` ở `UI`.
  - M4 `hr` hiện chỉ là package `tracecore/hr/`, chưa đăng ký Module Def; khi M4 có DocType đầu tiên phải đặt tên module khác `HR` qua amendment.
  - Module Def đã đăng ký: `TraceCore, Instrument, Reprocessing, Linen, Equipment, Inventory, Costing, Par, Admin Reports, Waste, UI`; đăng ký thêm tại FEAT-056 (A-113): `Infection Program, Compliance Audit, HAI Surveillance, Microbiology, Environmental Hygiene, Occupational Safety, Food Safety` (không trùng tên module của frappe/erpnext/hrms).
- Không import chéo giữa M1–M17; chỉ đi qua `core` hoặc Link/hook.
- **Chỉ `core.step_gate` được đổi trạng thái Set Unit / chuyển bước.** Không `set_value('Set Unit', …, 'status')` ở nơi khác. Frappe Workflow chỉ để hiển thị.
- Chứng từ đi Nháp → Ghi sổ → Hủy, không xóa (`is_submittable=1`). `Audit Log` append-only, cấm delete ở permission và hook.
- RPC đặt tên `tracecore.v1.<domain>.<action>`. Mọi RPC ghi của trạm/PDA dùng `@idempotent` với `X-Idempotency-Key`; `client_ts` là ISO 8601 có offset.
- Tận dụng ERPNext/HRMS (Item/Batch/Stock Entry, Asset, Quality, Employee, Department = khoa). Không tạo DocType trùng chức năng.
- Mã GS1 và DataMatrix sinh tại server qua `core.gs1`. Naming series theo architecture §5.3.3.
- Mã bệnh nhân lưu trường Password (AES), không ghi ra log; áp dụng cho DocType M13/M14 (Device Episode, HAI Case, Surgical Surveillance, Microbiology Isolate, Isolation Order…) và điều tra cắt ngang; **không có trường họ tên người bệnh**; M16 không có trường kết quả xét nghiệm/chẩn đoán nhân viên; mọi danh sách, báo cáo, export che mã BN, xem đầy đủ chỉ R01/R11 có lý do + Audit Log (NFR-PRIV-01, ADR-010 mở rộng).
- Nội dung chuyên môn (mẫu phiếu giám sát, định nghĩa ca NKBV, quy tắc đa kháng, ngưỡng môi trường, bước theo dõi phơi nhiễm) là fixtures Nháp có phiên bản do R01 duyệt tại bệnh viện; `bench migrate` không ghi đè bản bệnh viện đã sửa (NFR-MAINT-04). Không mã hóa cứng tiêu chí chuyên môn trong code.
- Mọi chuỗi hiển thị qua `_()`; không hard-code tiếng Việt ngoài `_()`; bản dịch ở `translations/vi.csv`, thuật ngữ theo QĐ 3671/QĐ-BYT. Ngày `dd/mm/yyyy`, 24 h, dấu phẩy thập phân, VND không lẻ, `Asia/Ho_Chi_Minh`.
- Không xây SPA Vue riêng; UI là Desk, Page `station`, PWA, Portal (ADR-002).
- Không tích hợp HIS/EMR/LIS/WHONET trực tuyến (quyết định D3 giữ ở v1.12): mẫu số ngày, danh sách phẫu thuật, kết quả vi sinh, hóa chất chỉ nhập file CSV/Excel/WHONET qua `Import Mapping Profile` (hồ sơ ánh xạ cột, F-21); API `tracecore.v1.ic.*` chỉ làm khi chủ đầu tư mở D3 (FEAT-074). Không chạy deploy production (`install_prod.sh` chỉ viết, không chạy).

## Quy tắc giao diện (tóm tắt `docs/design.md`)

- Chỉ dùng token `--tc-*`. Không gõ hex/px trực tiếp, không thêm màu ngoài palette.
- Font Arial / Segoe UI; mã định danh (Set ID, Cycle ID, mã lô) dùng Courier New. Không web font, không icon font tải mạng, không ảnh nền trang trí, không gradient. Card phẳng, chỉ modal/toast có bóng. Motion chỉ 120/200 ms và tắt khi `prefers-reduced-motion`.
- STN/PDA: chữ ≥ 16 px, nút ≥ 48 px (nút chính 56 px), khoảng cách ≥ 12 px, ≤ 3 chạm sau quét. Không hover-only, swipe, long-press, drag.
- Trạng thái không chỉ bằng màu: badge, gate, stepper luôn có chữ hoặc ký hiệu. Chữ trắng trên cam dùng `--tc-warn-fill` (#B85A00), trên xám dùng `--tc-neutral-fill` (#6B6B6B).
- Lỗi chặn nghiệp vụ: `alert-error` inline đỏ toàn khối, theo thứ tự kết quả → lý do → hành động. Không dùng modal hay toast cho lỗi chặn.
- Màn trạm/PDA: ô quét luôn trên cùng và có focus; đủ 4 trạng thái loading / empty / error / offline (FR-M9-14).
- Desk: chỉ override biến CSS qua `tracecore-theme.css` (`app_include_css`); không sửa SCSS của Frappe.
- **Không dùng Taste Skill** hay skill "art direction" nào khác (đã tắt trong `.claude/settings.json`): design system đã được duyệt, không thiết kế lại.
