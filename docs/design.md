# Design System: TraceCore

> Nguồn sự thật duy nhất cho mọi hiện thực UI, cùng với `docs/tokens.json`.
> Sinh bởi ux-foundations · Mode: **design-file (INGEST #09) + images (EXTRACT CSS #17 + 21 ảnh)** · Fidelity: `mapped`
> Cập nhật: 2026-10-17 · Áp dụng cho 4 surface: WEB (Frappe Desk), STN (trạm kiosk), PDA (PWA Android), DEPT (Cổng khoa)
> Quy tắc ưu tiên: **SRS NFR-USAB-01 / NFR-USAB-02 / NFR-ACC-01 / NFR-L10N-01 > #17 CSS > #09 §3–4 > ảnh design-refs**

---

## 1. Visual Theme & Atmosphere

**Tin cậy – lâm sàng – một chiều.** TraceCore là công cụ làm việc theo ca trong CSSD: người dùng đeo găng, màn hình ướt, 120–200 bộ/ngày. Giao diện phẳng, nền xám xanh rất nhạt (`#F4F6F9`), card trắng viền xanh nhạt, không bóng đổ. Màu không phải trang trí mà là **mã khu và mã trạng thái**: đỏ = khu bẩn / chặn, cam = khu sạch / cảnh báo, xanh lá đậm = khu vô khuẩn / Đạt, navy = chủ đạo & khoa. Một dải 8 px trên cùng (zonebar) luôn cho biết trạm đang ở khu nào. Mật độ: web dày (bảng 13 px), trạm thưa và lớn (≥ 16 px, nút 48–56 px). Mã định danh (Set ID, Cycle ID, mã lô) luôn ở font mono để mắt phân biệt mã với chữ.

Nguyên tắc #09 §2 được giữ nguyên: **quét trước – gõ sau**; **găng tay và màn ướt**; **trạng thái luôn thấy** (badge + stepper); **chặn rõ ràng** (đỏ toàn khối, có lý do và hành động kế tiếp, không modal nhỏ); **một chiều theo khu** (rail chỉ hiện chức năng khu của trạm); **offline minh bạch**; **in được**.

## 2. Design Tokens

Giá trị **dẫn xuất từ `tokens.json`** (W3C DTCG, 234 token). Bảng dưới là bản đọc nhanh; khi lệch nhau, `tokens.json` thắng.

### 2.1 Màu — vai trò (semantic)

| Vai trò | CSS var | Giá trị | Nguồn | Dùng cho |
| :-- | :-- | :-- | :-- | :-- |
| Primary | `--tc-primary` | `#1F4E79` | #17 `--navy` | Header, nút chính, H2, stepper current, th, zone dept |
| Primary hover | `--tc-primary-hover` | `#17375E` | #17 th border | Hover nút chính |
| Primary soft | `--tc-primary-soft` | `#EBF3FB` | #17 `--soft` | Nav active, nền scan box, callout info |
| Accent | `--tc-accent` | `#2E75B6` | #17 `--blue` | H3 card, link, zone web, focus ring |
| Zone dirty | `--tc-zone-dirty` | `#C00000` | #17 `--dirty` | Zonebar T1–T2, border-left |
| Zone clean | `--tc-zone-clean` | `#E36C09` | #17 `--clean` | Zonebar T3–T5, border-left |
| Zone sterile | `--tc-zone-sterile` | `#375623` | #17 `--sterile` | Zonebar T5b–T7 |
| Zone dept | `--tc-zone-dept` | `#1F4E79` | #17 `.zone-dept` | Zonebar Cổng khoa / PDA T8 |
| Zone web | `--tc-zone-web` | `#2E75B6` | #17 `.zone-web` | Zonebar Web desktop |
| Status pass fill / text / tint / strong | `--tc-pass`, `--tc-pass-tint`, `--tc-pass-strong` | `#375623` / `#F2F7EE` / `#DCE9D5` | #17 | Badge g, toast ok, alert ok, gate ok, stepper done |
| Status fail fill / text / tint | `--tc-fail`, `--tc-fail-tint` | `#C00000` / `#FFF2F2` | #17 | Badge r, btn danger, alert error, bom short, gate bad |
| Status warn **fill** | `--tc-warn-fill` | **`#B85A00`** | *điều chỉnh AA* | Badge o, btn warn có chữ trắng (#E36C09 chỉ 3.27:1) |
| Status warn **text** | `--tc-warn-text` | **`#B45309`** | *điều chỉnh AA* | Chữ cảnh báo trên trắng/tint |
| Status warn border/large | `--tc-warn` | `#E36C09` | #17 `--clean` | Border-left alert/kpi, progress bar, chữ ≥ 24 px |
| Status warn tint | `--tc-warn-tint` | `#FFF7EE` | #17 | Nền alert warn, ins due |
| Status info | `--tc-info`, `--tc-info-tint` | `#2E75B6` / `#EBF3FB` | #17 | Alert info (chữ trong alert dùng `--tc-text-heading`) |
| Status neutral **fill** | `--tc-neutral-fill` | **`#6B6B6B`** | *điều chỉnh AA* | Badge x Nháp/Hết hiệu lực (#7F7F7F chỉ 4.00:1) |
| Status neutral text | `--tc-text-muted` | **`#5F5F5F`** | *điều chỉnh AA* | Tag mã, meta |
| Neutral border | `--tc-neutral` | `#7F7F7F` | #17 `--grey` | Viền/icon phi văn bản |
| Surface page / card / zebra | `--tc-bg`, `--tc-card`, `--tc-zebra` | `#F4F6F9` / `#FFFFFF` / `#F2F2F2` | #17 | Nền |
| Surface disabled | `--tc-disabled-bg`, `--tc-disabled-text` | **`#E5E5E5` / `#595959`** | *điều chỉnh* | Nút disabled (#17 trắng/#BFBFBF = 1.84:1 FAIL) |
| Text primary / secondary / nav | `--tc-text`, `--tc-text-2`, `--tc-text-nav` | `#1d1d1f` / `#555555` / `#333333` | #17 | Body / label / nav |
| Text heading / subheading | `--tc-text-heading`, `--tc-text-sub` | `#1F4E79` / `#2E75B6` | #17 | H1–H2, kpi / H3 card |
| Border default / input / strong | `--tc-line`, `--tc-border-input`, `--tc-border-strong` | `#C8D8EE` / `#BFBFBF` / `#1F4E79` | #17 | Card / input, td, stepper pending / scan dashed, actions top |
| Focus ring | `--tc-focus` | `#2E75B6` | #17 `:focus-visible` | 3 px solid, offset 2 px |
| Photo placeholder | `--tc-photo-bg`, `--tc-photo-border`, `--tc-photo-text` | `#dfe6ee→#c9d3de` / `#b9c4d0` / `#3b4a5a` | #17 `.photo` | Khung "Ảnh thực tế" khi chưa có ảnh |
| Waste (v1.11) | `--tc-waste-infectious/-hazardous/-general/-recyclable` | `#F2C200` / `#1d1d1f` / `#2A7A34` / `#FFFFFF` | TT 20/2021, *đề xuất* | Mã màu túi chất thải — luôn kèm chữ |

**Ghi chú tương phản (WCAG 2.1, đo tại `tokens.json › $contrast-report`):**

- Đạt AA chữ thường: trắng/navy 8.66; trắng/blue 4.84; trắng/dirty 6.48; trắng/sterile 8.34; ink/bg 15.55; navy/soft 7.73; #555/trắng 7.46; sterile/#DCE9D5 6.62; dirty/#FFF2F2 5.93; focus/trắng 4.84.
- **Không đạt AA ở nguồn gốc → đã điều chỉnh:** (1) trắng trên `#E36C09` = 3.27 → badge/nút cảnh báo có chữ dùng `#B85A00` (4.67); `#E36C09` giữ cho zonebar, border-left, progress bar và chữ lớn ≥ 24 px. (2) `#E36C09` làm chữ trên `#FFF7EE` = 3.09 → chữ cảnh báo dùng `#B45309` (4.73). (3) trắng trên `#7F7F7F` = 4.00 → badge x dùng `#6B6B6B` (5.33); chữ xám tag dùng `#5F5F5F` (6.39). (4) nút disabled trắng/`#BFBFBF` = 1.84 → `#595959` trên `#E5E5E5` (5.56). (5) blue `#2E75B6` làm chữ trên soft `#EBF3FB` = 4.32 → trong callout info / nav active dùng navy cho chữ, blue chỉ cho viền.
- Nguyên tắc NFR-ACC-01: **Đạt/Không đạt không chỉ bằng màu** → badge luôn có chữ; gate panel có chữ "Đạt/Chưa/Không đạt"; stepper done có ✓; BOM thiếu có chữ "Thiếu".

### 2.2 CSS custom properties (sinh từ tokens.json)

```css
:root {
  /* raw palette — #17 :root */
  --navy:#1F4E79; --blue:#2E75B6; --soft:#EBF3FB; --dirty:#C00000; --clean:#E36C09;
  --sterile:#375623; --grey:#7F7F7F; --bg:#F4F6F9; --line:#C8D8EE; --ink:#1d1d1f;

  /* semantic */
  --tc-primary:var(--navy); --tc-primary-hover:#17375E; --tc-primary-soft:var(--soft); --tc-on-primary:#FFFFFF;
  --tc-accent:var(--blue);
  --tc-zone-dirty:var(--dirty); --tc-zone-clean:var(--clean); --tc-zone-sterile:var(--sterile);
  --tc-zone-dept:var(--navy); --tc-zone-web:var(--blue); --tc-zone-waste:var(--ink);
  --tc-pass:var(--sterile); --tc-pass-tint:#F2F7EE; --tc-pass-strong:#DCE9D5;
  --tc-fail:var(--dirty); --tc-fail-tint:#FFF2F2;
  --tc-warn:var(--clean); --tc-warn-fill:#B85A00; --tc-warn-text:#B45309; --tc-warn-tint:#FFF7EE;
  --tc-info:var(--blue); --tc-info-tint:var(--soft);
  --tc-neutral:var(--grey); --tc-neutral-fill:#6B6B6B;
  --tc-waste-infectious:#F2C200; --tc-waste-hazardous:#1d1d1f; --tc-waste-general:#2A7A34; --tc-waste-recyclable:#FFFFFF;
  --tc-bg:var(--bg); --tc-card:#FFFFFF; --tc-zebra:#F2F2F2; --tc-track:#eeeeee; --tc-overlay:rgba(0,0,0,.45);
  --tc-disabled-bg:#E5E5E5; --tc-disabled-text:#595959; --tc-frame:#222222;
  --tc-photo-bg:linear-gradient(135deg,#dfe6ee,#c9d3de); --tc-photo-border:#b9c4d0; --tc-photo-text:#3b4a5a;
  --tc-text:var(--ink); --tc-text-2:#555555; --tc-text-nav:#333333; --tc-text-heading:var(--navy);
  --tc-text-sub:var(--blue); --tc-text-link:var(--blue); --tc-text-inverse:#FFFFFF; --tc-text-muted:#5F5F5F;
  --tc-line:var(--line); --tc-border-input:#BFBFBF; --tc-border-strong:var(--navy); --tc-border-th:#17375E;
  --tc-border-row:#eeeeee; --tc-border-label:#333333; --tc-border-label-plasma:var(--blue);
  --tc-focus:var(--blue);

  /* typography */
  --tc-font-sans:Arial,"Segoe UI","Helvetica Neue",sans-serif;
  --tc-font-mono:"Courier New",Consolas,monospace;
  --tc-fs-2xs:11px; --tc-fs-xs:12px; --tc-fs-sm:13px; --tc-fs-md:14px; --tc-fs-base:15px; --tc-fs-lg:16px;
  --tc-fs-xl:17px; --tc-fs-2xl:20px; --tc-fs-3xl:21px; --tc-fs-4xl:27px; --tc-fs-5xl:29px; --tc-fs-6xl:45px;
  --tc-lh-tight:1.1; --tc-lh-snug:1.2; --tc-lh-label:1.3; --tc-lh-base:1.5; --tc-fw-bold:700;

  /* space (2/4px) */
  --tc-sp-0-5:2px; --tc-sp-1:4px; --tc-sp-1-5:6px; --tc-sp-2:8px; --tc-sp-2-5:10px; --tc-sp-3:12px; --tc-sp-3-5:14px;
  --tc-sp-4:16px; --tc-sp-4-5:18px; --tc-sp-5:20px; --tc-sp-6:24px; --tc-sp-6-5:26px; --tc-sp-7:28px; --tc-sp-8:32px;
  --tc-sp-12:48px; --tc-sp-14:56px; --tc-sp-22:90px;

  /* radius */
  --tc-r-xs:3px; --tc-r-sm:4px; --tc-r-md:5px; --tc-r-lg:6px; --tc-r-xl:8px; --tc-r-pill:14px; --tc-r-badge:10px;
  --tc-r-count:11px; --tc-r-phone:32px;

  /* border width */
  --tc-bw-hair:1px; --tc-bw-med:1.5px; --tc-bw-thick:2px; --tc-bw-focus:3px; --tc-bw-accent:4px; --tc-bw-alert:5px; --tc-bw-kpi:6px; --tc-bw-frame:12px;

  /* size */
  --tc-touch-min:48px; --tc-touch-station:56px; --tc-touch-gap:12px; --tc-touch-table:34px;
  --tc-checkbox:22px; --tc-checkbox-station:32px; --tc-rail-w:250px; --tc-zonebar-h:8px; --tc-scan-btn-min:110px;
  --tc-photo:64px; --tc-photo-big:210px; --tc-datamatrix:46px; --tc-label-w:280px; --tc-phone-w:380px; --tc-modal-w:440px;

  /* shadow, motion, z */
  --tc-shadow-none:none; --tc-shadow-phone:0 6px 24px rgba(0,0,0,.25); --tc-shadow-overlay:0 8px 32px rgba(0,0,0,.30);
  --tc-dur-fast:120ms; --tc-dur-base:200ms; --tc-dur-toast:3200ms; --tc-ease:cubic-bezier(.2,0,0,1);
  --tc-z-rail:10; --tc-z-actions:20; --tc-z-modal:50; --tc-z-toast:60;
}
/* Surface overrides — gắn data-surface trên <html> hoặc wrapper page */
[data-surface="STN"]{ --tc-fs-2xs:16px; --tc-fs-xs:16px; --tc-fs-sm:16px; --tc-fs-md:17px; --tc-fs-base:19px; --tc-fs-lg:20px;
  --tc-fs-2xl:24px; --tc-fs-3xl:24px; --tc-fs-4xl:32px; --tc-checkbox:32px; --tc-touch-table:48px; }
[data-surface="PDA"]{ --tc-fs-2xs:16px; --tc-fs-xs:16px; --tc-fs-sm:16px; --tc-fs-md:18px; --tc-fs-base:21px; --tc-fs-lg:21px;
  --tc-fs-2xl:20px; --tc-checkbox:32px; --tc-touch-table:48px; --tc-rail-w:0px; }
[data-surface="DEPT"]{ --tc-fs-base:16px; --tc-fs-sm:14px; --tc-touch-table:48px; }
@media (prefers-reduced-motion:reduce){ *{transition:none!important;animation:none!important} }
:focus-visible{ outline:var(--tc-bw-focus) solid var(--tc-focus); outline-offset:2px; }
```

**Dark mode (tùy chọn, chỉ WEB):** bộ `color-dark.*` trong tokens.json re-value cùng vai trò (`--tc-bg:#121417; --tc-card:#1B1F24; --tc-text:#E8EAED; …`). STN/PDA **không** có dark mode — kiosk CSSD luôn sáng. Chưa kiểm chứng trên thiết bị thật → Known Gaps.

### 2.3 Ánh xạ sang Frappe v15 theme variables

Frappe Desk v15 dùng CSS variables trong `frappe/public/scss/desk/css_variables.scss`. App `tracecore` nạp một file `tracecore/public/css/tracecore-theme.css` qua `app_include_css` để override **chỉ các biến dưới đây**, không chạm SCSS gốc:

| Frappe variable | Gán | Ghi chú |
| :-- | :-- | :-- |
| `--primary`, `--primary-color`, `--btn-primary` | `var(--tc-primary)` | Nút primary Desk → navy |
| `--primary-hover` (nếu theme có) / `.btn-primary:hover` | `var(--tc-primary-hover)` | |
| `--bg-color` | `var(--tc-bg)` | Nền Desk |
| `--card-bg`, `--fg-color`, `--control-bg` | `var(--tc-card)` | Card/form trắng |
| `--text-color` | `var(--tc-text)` | |
| `--text-muted`, `--text-light` | `var(--tc-text-2)` | |
| `--heading-color` | `var(--tc-text-heading)` | |
| `--border-color`, `--dark-border-color` | `var(--tc-line)`, `var(--tc-border-input)` | |
| `--sidebar-bg` / `.layout-side-section` | `var(--tc-card)` + border-right `--tc-line` | Giống rail #17 |
| `--navbar-bg` | `var(--tc-card)` | Navbar trắng; zonebar 8 px chèn trên navbar bằng `::before` |
| `--font-stack` | `var(--tc-font-sans)` | Arial/Segoe UI thay Inter |
| `--font-size-base` (Desk 13px) | giữ 13px cho List/Form chuẩn; page tùy biến đặt `font-size:var(--tc-fs-base)` | Không phá layout Desk |
| `--border-radius`, `--border-radius-md` | `var(--tc-r-sm)`, `var(--tc-r-lg)` | 4/6 px |
| `--shadow-base`, `--shadow-sm` | `var(--tc-shadow-none)` | Card phẳng |
| `--green`, `--green-600`, `.indicator-pill.green` | `var(--tc-pass)` | Indicator Đạt |
| `--red`, `--red-600`, `.indicator-pill.red` | `var(--tc-fail)` | |
| `--orange`, `--yellow`, `.indicator-pill.orange` | `var(--tc-warn-fill)` (nền chữ trắng) / `var(--tc-warn)` (dot) | |
| `--blue`, `.indicator-pill.blue` | `var(--tc-accent)` | |
| `--gray-600`, `.indicator-pill.gray` | `var(--tc-neutral-fill)` | Nháp |
| Workflow state colors (`Workflow State.style` Success/Danger/Warning/Primary/Inverse) | pass / fail / warn-fill / primary / neutral-fill | Đặt qua `style` trong fixtures |

**Frappe UI (Vue, cho Frappe page/PWA):** Frappe UI dùng Tailwind preset; `tailwind.config.js` của page STN/PDA extend `theme.colors` bằng các token (`primary: '#1F4E79'`, `surface-soft: '#EBF3FB'`, `zone.dirty…`), `fontFamily.sans = tokens.typography.family.sans`, `spacing` chỉ giữ thang 2/4 px. Ánh xạ component: `Button` (variant `solid`→button-primary, `outline`→button-secondary, `subtle`→chip, theme `red`→danger, `green`→ok) · `Badge` (theme green/red/orange/gray → g/r/o/x, nhưng nền phải lấy fill token AA) · `Alert`/`Toast` (`useToast`) · `Dialog` → PIN modal · `TextInput`/`Select`/`Checkbox`/`FormControl` → form grid · `ListView` → data table · `Tabs` → Master form tabs · `Progress` → par bar. Component không có sẵn trong Frappe UI (Scan box, Stepper T1–T8, Gate panel, Zone bar, BOM checklist, Label preview, Actions bar, Phone frame) viết trong `tracecore/public/js/components/` theo spec §4.

### 2.4 Typography

Họ chữ: `Arial, "Segoe UI", sans-serif` cho toàn bộ UI (#09 §3). `"Courier New", monospace` **chỉ** cho mã định danh (Set ID, Cycle ID, Load ID, mã lô, mã QR túi, tag UC/SCR), ô quét và số lượng BOM. Không dùng font web tải về (kiosk offline, LAN bệnh viện).

| Bậc | WEB | STN | PDA | lh | weight | Dùng |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 2xs | 11px | **16px** | **16px** | 1.5 | 700 (badge) / 400 | Badge, tag, stepper chip, label form, crumb |
| xs | 12px | 16px | 16px | 1.5 | 400 | Chips, rail foot, nhãn in |
| sm | 13px | 16px | 16px | 1.5 | 400 | Bảng, kpi small, ins name (bold) |
| md | 14px | 17px | 18px | 1.5 | 400 | Nút, card H3 (bold, blue), checkbox label |
| base | 15px | 19px | 21px | 1.5 | 400 | Body |
| lg | 16px | 20px | 21px | 1.5 | 700 | Rail who, modal H3, res code (mono), nút PDA |
| 2xl | 20px | 24px | 20px | 1.2 | 400 mono | Ô quét |
| 3xl | 21px | 24px | 24px | 1.2 | 700 navy | H2 title trang |
| 4xl | 27px | 32px | 32px | 1.1 | 700 navy | KPI số |
| 5xl | 29px | — | — | 1.2 | 700 navy | H1 login |

Quy tắc: H2 navy bold; H3 card blue bold md; mọi chữ trên STN/PDA ≥ 16 px (NFR-ACC-01); số liệu và ngày theo NFR-L10N-01 (`dd/mm/yyyy`, 24h, thập phân dấu phẩy, VND không lẻ `184.500 ₫`).

### 2.5 Spacing, Radius, Elevation

- **Spacing** (2/4 px): `2 4 6 8 10 12 14 16 18 20 24 26 28 32 48 56 90`. Section gap 24; card padding 14×16; card gap 12; intra-form gap 8×16; main padding 20×26 (STN giữ, PDA 12); padding-bottom main 90 để chừa actions bar.
- **Radius**: tag 3 · input/alert 4 · btn/toast 5 · card/kpi/ins 6 · scan box/modal/role 8 · chips/stepper 14 (pill) · badge 10 · phone 32.
- **Elevation**: phẳng. Card = viền `--tc-line` 1 px, không bóng. Chỉ modal/toast (`--tc-shadow-overlay`) và khung phone (`--tc-shadow-phone`) có bóng.
- **Border**: 1 px card/input/td · 1.5 px nút phụ · 2 px scan dashed & actions top · 4 px nav active · 5 px alert left · 6 px kpi left / modal top / role top.

## 3. Layout & Grid

**Shell chung (#17 `#app`)**: `rail` 250 px cố định trái (trắng, border-right line, sticky, 100vh) gồm `who` (tên + vai trò + trạm), `nav` (danh sách link, badge số đỏ), `foot` (trạng thái mạng + số giao dịch chờ + Đăng xuất). `main` flex-1, padding 20×26, bottom 90. Trên cùng `main` là **zonebar 8 px** màu khu. Tiếp theo: `crumb` (12 px navy) › `title` (H2 + tag mono UC/SCR + badge) › nội dung › `actions` bar cố định đáy (left = rail width, border-top 2 px navy, padding 10×26, gap 10, safe-area).

| Surface | Container | Grid | Breakpoint | Shell |
| :-- | :-- | :-- | :-- | :-- |
| WEB | Frappe Desk `page-container` (max 1920) | Form 2 cột (`.two`, `.grid` 1fr 1fr, gap 12 / 8×16), KPI 4 cột (gap 10), `.inst` auto-fill minmax(210px,1fr) | ≤ 900: 1 cột, kpi 2 cột; Desk sidebar ẩn ≤ 991 (Frappe) | Desk navbar + sidebar Frappe; zonebar web (blue) dưới navbar |
| STN | Full-screen Chromium kiosk 1366×768–1920×1080 | Như WEB nhưng mọi control ≥ 48 px; vùng quét luôn trên cùng; BOM 2 cột (ảnh bộ trái 1fr · checklist phải 1fr) | 1366: KPI 2 cột, inst 3 cột | Rail 250 (chỉ trạm của khu); zonebar màu khu; actions bar luôn hiện |
| PDA | Khung 380 px (viewport ≥ 360) | 1 cột, nút full-width, stack dọc | ≤ 480 | Top bar navy 30 px (giờ · người · mạng · số chờ) · zonebar · body padding 12 · footer trạng thái; không rail (menu = màn danh sách 2×2 nút lớn) |
| DEPT | Trang web đơn giản (Frappe Website/Portal page), max 1200 | 1–2 cột | ≤ 900: 1 cột | Rail 250 với 7 mục cổng khoa; zonebar dept (navy) |

Touch target: **≥ 48 px** mọi surface tương tác chạm (NFR-USAB-01); nút chính STN/PDA 56 px; khoảng cách nút ≥ 12 px; web-only cho phép 34 px trong ô bảng.

## 4. Components

Ký hiệu trạng thái: **D** default · **H** hover · **F** focus · **A** active/pressed · **X** disabled · **L** loading · **E** error. Giá trị web; STN/PDA áp override §2.2.

### 4.1 Actions

**`button-primary`** (#17 `.btn`) — nền `--tc-primary`, chữ trắng 14 px, radius 5, padding 11×18, **min-height 48** (STN/PDA 56, full-width trên PDA), border 0. H: `--tc-primary-hover`. F: ring 3 px `--tc-focus` offset 2. A: translateY(1px). X: nền `--tc-disabled-bg`, chữ `--tc-disabled-text`, cursor not-allowed, **vẫn hiện lý do bị khóa cạnh nút** (vd "Chưa thể xác nhận — còn: xử lý nhắc tra dầu (1)"). L: spinner 16 px trắng trái chữ, chữ đổi "Đang ghi sổ…", nút khóa.
**`button-secondary`** (`.btn.sec`) — nền trắng, chữ `--tc-primary`, border 1.5 px `--tc-primary`. H: nền `--tc-primary-soft`. Dùng: In, Chụp ảnh, Bỏ bộ này, Đăng xuất.
**`button-danger`** (`.btn.danger`) — nền `--tc-fail`, chữ trắng. Dùng: Theo dõi thu hồi, Không đạt, Hủy phiếu. Luôn qua confirm (PIN modal nếu nghiệp vụ yêu cầu).
**`button-ok`** (`.btn.ok`) — nền `--tc-pass`, chữ trắng. Dùng: Xác nhận bộ, Xác nhận tất cả, Giải phóng.
**`button-warn`** (`.btn.warn`) — nền **`--tc-warn-fill`** (không dùng #E36C09), chữ trắng. Dùng: Hoãn (lý do), Cách ly.
**`button-table`** — như primary/secondary nhưng min-height 34, padding 5×12, 13 px — **WEB only**.
**`chip`** (#17 `.chips button`) — trắng, border 1 px `--tc-primary`, chữ primary 12 px, radius 14, padding 4×10 (STN: min-height 48, padding 10×16, 16 px). H: nền soft. A: nền primary chữ trắng. Dùng: mã gợi ý dưới ô quét, bộ lọc nhanh.
**`qty-stepper`** (`.qty`) — nút −/+ 32×32 (STN 48×48) border primary, số mono 44 px giữa. X: mờ 40 %.
**`flag-toggle`** (`.flag button`) — pill 12 px border input; **on**: nền `--tc-fail`, chữ trắng, kèm chữ ("Hỏng", "Thiếu"), không chỉ màu.
**`link`** — `--tc-text-link`, không gạch chân mặc định, gạch chân khi H/F; trên nền soft dùng navy.

### 4.2 Scan box (`scan-box`, #17 `.scan`)

Khối nền `--tc-primary-soft`, border **2 px dashed** `--tc-primary`, radius 8, padding 12, flex gap 10. Bên trong: `input` mono 20 px (STN 24, PDA 20), padding 12, border 1 px primary, radius 5, flex 1, `autofocus`, `inputmode="none"` trên kiosk có máy quét HID (bàn phím ảo không bật), Enter = quét; nút **Quét** primary min-width 110. Dưới: hàng `chips` gợi ý. Trạng thái: **idle** (placeholder "Quét Set ID…", con trỏ nhấp nháy) · **reading** (border đổi `--tc-accent` 2 px solid, 300 ms) · **ok** (flash nền `--tc-pass-tint` 400 ms + âm ngắn + rung 50 ms trên PDA) · **error** (border `--tc-fail` 2 px solid, nền `--tc-fail-tint`, kèm `alert-error` ngay dưới với lý do + hành động, **không modal**) · **locked** (khi chưa quét máy: input disabled, placeholder "Quét QR máy trước", nền `--tc-disabled-bg`). Quy tắc: luôn tự focus lại sau mỗi giao dịch; chỉ một scan box có focus trên màn; label `aria-label` tiếng Việt.

### 4.3 Stepper T1–T8 (`stepper`, #17)

Flex wrap gap 4, margin 6 0 14. Mỗi bước `span` padding 5×11 (STN 10×16), 11 px (STN 16), radius 14, border 1 px `--tc-border-input`, nền trắng, chữ `--tc-text-2` = **pending**. **done**: nền `--tc-pass-strong`, border + chữ `--tc-pass`, tiền tố "✓ ". **current**: nền `--tc-primary`, chữ trắng bold, border primary. **failed**: nền `--tc-fail-tint`, border + chữ `--tc-fail`, tiền tố "✕ ". Nhãn chuẩn: `T1 Tiếp nhận · T2 Rửa · T3 Lắp ráp · T4 Đóng gói · T5 Tiệt khuẩn · T6 Kho VK · T7 Cấp phát · T8 Sử dụng`. Biến thể **workflow stepper** cho WF-01..09 dùng cùng class với nhãn trạng thái. Trên PDA: ẩn stepper đầy đủ, chỉ hiện chip current + badge.

### 4.4 Gate panel 5 cổng (`gates` / `gt`, #17)

Flex wrap gap 6. Mỗi cổng `gt`: border 1 px input, radius 6, padding 5×10, nền trắng, dòng 1 tên cổng 11 px `--tc-text-2`, dòng 2 bold 13 px kết quả. Cổng: `T1 Tiếp nhận · kiểm đếm` · `T2 Rửa – khử khuẩn` · `T3 Lắp ráp` · `T4 Đóng gói` · `T5 Tiệt khuẩn · giải phóng` · (tổng) `Vô khuẩn`. **ok**: border + chữ `--tc-pass`, nền `--tc-pass-tint`, chữ "Đạt". **pending**: chữ "Chưa". **bad**: border + chữ `--tc-fail`, nền `--tc-fail-tint`, chữ "Không đạt". STN: padding 10×14, chữ 16/18. Dùng trên SCR-07/08/09/10/11, SCR-21 (Khoa truy xuất), SCR-14.

### 4.5 Zone bar & zone banner

`zonebar`: div cao **8 px** full-width ngay trên nội dung main (WEB: dưới navbar Frappe), màu `--tc-zone-*` theo khu của trạm: dirty (T1, T2) · clean (T3, T4, T5) · sterile (T5b, T6, T7) · dept (T8, Cổng khoa, PDA khoa) · web (Desk quản trị) · waste (trạm/kho chất thải, màu ink; băng phụ 4 px màu nhóm túi khi đang thao tác loại cụ thể). Không có chữ; tên khu lặp lại trong `tag` cạnh H2 (vd "Khu bẩn · UC-05") để không phụ thuộc màu. PDA: zonebar nằm dưới top bar.

### 4.6 KPI tile (`kpi`, #17)

Card trắng, border 1 px line, **border-left 6 px**, radius 6, padding 10×12; số `b` 27 px navy lh 1.1 (STN 32); nhãn `small` 13 px `--tc-text-2`. Biến thể theo ngưỡng: **ok** left `--tc-pass`; **warn** left `--tc-warn` + nền `--tc-warn-tint`; **alert** left `--tc-fail` + nền `--tc-fail-tint` (ảnh 02 xác nhận); default left navy. Grid `kpis` 4 cột gap 10 (≤ 900: 2 cột). L: số thay bằng skeleton 60×27. Empty: "0" + nhãn, không ẩn tile. Có thể click → mở danh sách lọc tương ứng (cursor pointer, F ring).

### 4.7 Alert / callout (`alert`, #17)

Khối border-left **5 px**, padding 9×12, margin 8 0, radius 0 4 4 0, chữ `--tc-text`. **error** (mặc định): left `--tc-fail`, nền `--tc-fail-tint`, tiêu đề bold "Không …" + lý do + hành động kế tiếp (nút hoặc link) — đây là "chặn đỏ toàn khối" của EI-UI-007; trên STN chiếm full-width card và có nút lớn. **warn**: left `--tc-warn`, nền `--tc-warn-tint`, chữ đậm dùng `--tc-warn-text`. **ok**: left `--tc-pass`, nền `--tc-pass-tint`. **info**: left `--tc-info`, nền `--tc-info-tint`, chữ navy. Có thể chứa nút hành động bên phải (ảnh 02: "Xem và duyệt", "Theo dõi"). Mã trong alert dùng `code` mono. Icon tùy chọn trước chữ (✕ ! ✓ i) để không chỉ dựa màu.

### 4.8 Badge trạng thái (`badge`, #17)

Inline-block, padding 2×9, radius 10, 11 px bold (STN 16 px, padding 4×12, min-height 28), chữ trắng, `white-space:nowrap`. Nền: mặc định navy (Đang dùng, trạng thái WF trung gian) · **g** `--tc-pass` (Đạt, Đã giải phóng, Vô khuẩn, Đã cấp phát) · **o** **`--tc-warn-fill`** (Chờ duyệt, Cách ly, Cần xem xét, Dưới tối thiểu, Sắp quá hạn) · **r** `--tc-fail` (Không đạt, Thu hồi, Hết hiệu lực do lỗi, Quá hạn) · **x** **`--tc-neutral-fill`** (Nháp, Ngừng, Đã hủy). Luôn có chữ; không dùng badge trống làm dot. Biến thể `count` (rail nav): min-width 22, radius 11, 11 px, nền `--tc-fail`, margin-left auto. `tag` (mã UC/SCR/khu): mono 11 px, chữ `--tc-text-muted`, border 1 px `#ccc`, nền trắng, padding 2×6, radius 3.

### 4.9 Card (`card`, #17)

Nền trắng, border 1 px `--tc-line`, radius 6, padding 14×16, margin-bottom 12, không bóng. `h3` 14 px bold `--tc-text-sub` margin-bottom 10, có thể kèm `tag`. Biến thể: **res** (kết quả quét: padding 12, `b.code` mono 16 px navy block) · **pill** (`recv .pill`: padding 6×10, 13 px; `.bad` border fail) · **role** (login: border-top 6 px navy / clean / sterile, padding 18, radius 8) · **ins** (xem BOM). Empty state trong card: chữ `--tc-text-2` + hướng dẫn 1 câu (ảnh 07: "Quét thẻ nhân viên giao, rồi quét mã bộ…"). Loading: 3 dòng skeleton.

### 4.10 Data table (`table`, #17)

Width 100 %, border-collapse, 13 px (STN 16). `th` nền navy chữ trắng trái, padding 7×9, border 1 px `--tc-border-th`. `td` padding 6×9 (STN 10×12, min-height 48 khi có control), border 1 px `--tc-border-input`, vertical-align top. Dòng chẵn nền `--tc-zebra`. Badge trong ô cho trạng thái; nút trong ô `button-table`. Trên WEB chuẩn Frappe List View giữ Desk nhưng áp màu indicator §2.3; Report/Query report dùng DataTable Frappe với `--tc-*`. Trạng thái: **loading** skeleton 5 dòng; **empty** 1 dòng span toàn bảng "Không có dữ liệu — <gợi ý tiêu chí>" (SCR-14 E1); **error** alert-error trên bảng với nút Thử lại. Sort/filter/paginate theo FR-M9-13; ô quét làm phím tắt tìm (focus `/`). Cột số căn phải, mã mono.

### 4.11 BOM checklist với ảnh thực tế (`inst` / `ins` / `photo` / `tray` / `bom`, #17)

Bố cục 2 cột: trái **ảnh bộ đã sắp xếp** (`photo.big` 100 %×210, radius 4; `photo-thumbs` 3 góc 60×44) · phải **grid dụng cụ** (`inst` auto-fill ≥ 210). Mỗi `ins`: border 1 px line, radius 6, padding 8, flex gap 10: `photo` 64×64 (ảnh thật `object-fit:cover`; khi chưa có ảnh: gradient `--tc-photo-bg`, border photo, icon 📷 + "Ảnh thực tế" 11 px) · `nm` 13 px bold navy · `pos` 11 px `--tc-text-2` ("Vị trí 1 theo ảnh · × 6 · bảo dưỡng 11/10") · `qty` hoặc checkbox 22 px (STN 32) + nhãn "Đã đặt đúng vị trí n theo ảnh thực tế". Trạng thái: **short** (thiếu) border + nền `--tc-fail` / fail-tint, chữ "Thiếu n"; **done** border pass, nền pass-tint; **due** (đến hạn bảo dưỡng) border `--tc-warn`, nền warn-tint, 2 nút secondary "Đã tra dầu khớp" / "Hoãn (lý do)". Biến thể bảng (`bom label`, ảnh 07): dòng flex padding 8×10, border-bottom `--tc-border-row`, ảnh 64, tên, số lượng bold, checkbox + chữ "Đủ/Chưa"; `.short` nền fail-tint. `tray`: khung SVG sơ đồ khay (max-height 230) — chỉ hiển thị khi loại bộ có sơ đồ. Nút "Xác nhận tất cả thành phần" button-ok dưới grid. Ô "Ghi chú bất thường" textarea full-width với placeholder ví dụ. Progress cơ số `par`: track 10 px `--tc-track`, radius 5, fill pass; ≥ 90 % `--tc-warn`; ≥ 100 % `--tc-fail`; luôn kèm chữ "47/300 chu trình (16%)".

### 4.12 Label preview (`label`, #17)

Khối 280 px, border 1 px `--tc-border-label`, padding 10, nền trắng, 12 px lh 1.3, chữ đen (mô phỏng nhãn in 134 °C). Góc phải `dm` 46×46 DataMatrix (render thật bằng thư viện GS1 ở build; placeholder pattern trong prototype). Dòng: Cycle ID mono bold · chuỗi GS1 `(01)…(11)…(17)…(21)…` 10 px mono · Set ID mono · tên bộ · khoa · phương pháp · loại gói · "Đóng gói: NV… · dd/mm/yyyy hh:mm" · "Chỉ thị: lô … · BOM vN" · **"HẠN SỬ DỤNG: dd/mm/yyyy"** bold · cảnh báo đỏ "THIẾU DỤNG CỤ — xem phiếu kiểm đếm" nếu có · dòng cuối loại nhãn. Biến thể **plasma** (`label.plasma`): border **dashed** `--tc-border-label-plasma`, dòng cuối "Nhãn plasma H2O2"; **hấp**: border solid, "Nhãn hấp hơi nước 134°C"; **LOANER**: thêm dòng "LOANER" bold. Nhãn có tiếng Anh phụ (NFR-USAB-02). Kèm nút secondary "In lại (lý do)".

### 4.13 PIN modal & dialog (`#modal`, #17)

Overlay `--tc-overlay` full, z 50, căn giữa. `box` nền trắng, radius 8, padding 20, width `min(440px, 92vw)`, **border-top 6 px navy** (danger: fail; warn: warn). `h3` 16 px navy. Nội dung: form grid 1 cột. `row` nút căn phải gap 8 (STN: nút full-width xếp dọc, 56 px). **PIN**: input `type=password inputmode=numeric` 6 ô (PIN phê duyệt 6 số theo NFR-SEC-01; demo #17 4 số), mono 24 px, autofocus; sai → alert-error trong modal, đếm số lần; 5 lần → khóa + thông báo. Focus trap, Esc đóng (trừ modal bắt buộc), `aria-modal`. Chỉ dùng modal cho **xác nhận/PIN/nhập lý do**; **không** dùng cho lỗi chặn quét (nguyên tắc #09 §2.4).

### 4.14 Toast (`#toast`, #17)

Cố định top 14 right 14 (PDA: bottom trên footer), nền `--tc-pass` chữ trắng, padding 10×16, radius 5, max-width 380, z 60, hiển thị 3200 ms, `role=status aria-live=polite`. **err**: nền `--tc-fail` (aria-live assertive, 6000 ms, có nút đóng); **warn**: nền `--tc-warn-fill`. Nội dung 1 câu, bắt đầu bằng kết quả ("Đã ghi sổ phiếu TN-…"). Không dùng toast cho lỗi chặn nghiệp vụ (dùng alert-error inline).

### 4.15 Rail nav với badge số (`rail`, #17)

Width 250, trắng, border-right line, sticky, 100vh, flex column. `who`: padding 16 16 12, border-bottom; `b` 16 px navy; `small` `--tc-text-2`. `nav a`: flex gap 10, padding 10×16 (STN 14×16, min-height 48), chữ `--tc-text-nav`, border-left 4 px transparent. **on**: nền `--tc-primary-soft`, border-left navy, chữ navy bold. H: nền `#F7FAFD`. F: ring. Badge `n` đếm việc chờ (đỏ). `foot`: padding 12×16, border-top, 12 px: **offline indicator** "● Trực tuyến · 0 giao dịch chờ đồng bộ" (dot pass) / "● Ngoại tuyến · 7 chờ đồng bộ" (dot fail, chữ `--tc-fail` bold) / "● Đang đồng bộ 3/7" (dot warn-text) + nút Đăng xuất secondary. Quy tắc một chiều: STN chỉ liệt kê trạm thuộc khu của máy (T1–T2 | T3–T5 | T5b–T7); WEB dùng sidebar Frappe với cùng style. ≤ 900 px: rail thành thanh ngang scroll, border-bottom 4 px thay border-left.

### 4.16 Actions bar cố định (`actions`, #17)

`position:fixed; left:250px (0 khi ≤900/PDA); right:0; bottom:0`, nền trắng, border-top 2 px navy, padding 10×26 + safe-area, flex gap 10 wrap, z 20. Thứ tự: nút chính (primary/ok, có thể X với lý do) → nút phụ (secondary) → danger ở cuối phải. Nhãn động mang số lượng ("Ghi sổ phiếu tiếp nhận (3 bộ)"). STN: nút 56 px, tối đa 3 nút (≤ 3 chạm). Thanh không che nội dung nhờ `main padding-bottom 90`.

### 4.17 Phone frame PDA (`phone`, #17)

Chỉ dùng **trong prototype/tài liệu và chế độ xem PDA trên web**: width 380, border 12 px `--tc-frame`, radius 32, nền trắng, overflow hidden, bóng phone. `top` navy chữ trắng 12 px (giờ | người · mạng · số chờ). Trên thiết bị thật PWA **không** vẽ khung; `top` trở thành app bar thật 44 px + zonebar + `body` padding 12 + footer trạng thái 40 px. Nút PDA `.btn` full-width, min-height 56, 16–21 px, margin-top 8.

### 4.18 Form grid & field (`grid` / `f` / `two`, #17)

Grid 2 cột gap 8×16 (PDA 1 cột). `f label` block 11 px `--tc-text-2` (STN 16); `f input/select` width 100 %, padding 8 (STN 12, min-height 48), border 1 px input, radius 4, nền trắng, 15 px. `f .v` (giá trị chỉ đọc): border input, padding 7×9, min-height 36 (STN 48), nền trắng. Trạng thái: F ring; **error**: border `--tc-fail` 2 px + dòng lỗi 13 px `--tc-fail` dưới field + `aria-describedby`; X nền disabled; required dấu `*` navy sau label. Validation hiển thị tại field **và** tổng hợp trong alert-error trên actions bar khi bấm Ghi sổ. Checkbox `ck` 24 px (STN 32) + nhãn 14 px. Signature pad: canvas 100 %×160, border input, nút Xóa secondary; hoặc "Quét thẻ để ký". Date/time theo NFR-L10N-01.

### 4.19 Offline & trạng thái màn hình (FR-M9-14)

Mỗi màn trạm/PDA bắt buộc có 4 trạng thái: **loading** (skeleton, không spinner chặn), **empty** (hướng dẫn 1 câu + ảnh/icon), **error** (alert-error với 3 hành động chuẩn: Thử lại · Chuyển offline · Gọi R02), **offline** (foot rail đổi đỏ; banner info mỏng dưới zonebar "Đang ngoại tuyến — giao dịch được lưu cục bộ"; nút Ghi sổ vẫn bật). Thiết bị ngoại vi lỗi (in, cân): alert-warn + nút "In sau (hàng đợi)" / "Nhập tay (ghi nguồn)".

### 4.20 Per-surface variants

| Component | WEB | STN | PDA | DEPT |
| :-- | :-- | :-- | :-- | :-- |
| button | 48 px (Desk btn chuẩn 32 px chỉ trong Form Desk) | 48/56 px | 56 px full-width | 48 px |
| scan-box | 20 px mono, chip 12 px | 24 px, chip 48 px | 20 px, nút Quét full | 20 px |
| stepper | đầy đủ 8 | đầy đủ 8, 16 px | chip current + badge | đầy đủ (Khoa truy xuất) |
| table | 13 px, row 34 | 16 px, row 48 | thay bằng card list | 14–16 px |
| rail | Frappe sidebar | rail trạm theo khu | không (menu 2×2) | rail 7 mục |
| badge | 11 px | 16 px, 28 px cao | 16 px | 14 px |
| modal | 440 | 440, nút dọc 56 | full-screen sheet | 440 |

## 5. Accessibility Rules (bắt buộc — từ SRS)

- **NFR-ACC-01**: WEB đạt **WCAG 2.1 AA** (tương phản, bàn phím, nhãn form). STN/PDA: tương phản **≥ 4,5:1**, **cỡ chữ ≥ 16 px**, Đạt/Không đạt **không chỉ bằng màu**. Mọi cặp màu chữ/nền chỉ được chọn từ bảng §2.1 đã đo; cặp mới phải đo trước khi dùng.
- **NFR-USAB-01**: mọi nút/checkbox/chip trên STN/PDA **≥ 48 px**, nút chính 56 px, khoảng cách ≥ 12 px; thao tác chính ≤ 3 chạm sau quét; không hover-only (mọi thông tin hover phải có dạng hiện sẵn hoặc tap); dùng được khi găng/màn ướt → không swipe, không long-press, không drag.
- **NFR-USAB-02 / EI-UI-006**: 100 % chuỗi tiếng Việt, thuật ngữ QĐ 3671/QĐ-BYT; nhãn in có tiếng Anh phụ; 0 chuỗi chưa dịch trên 43 SCR.
- **NFR-L10N-01**: `dd/mm/yyyy`, 24h, dấu phẩy thập phân, VND không lẻ, Asia/Ho_Chi_Minh.
- **Focus**: `:focus-visible` outline 3 px `--tc-focus` offset 2 trên mọi control, kể cả nút trong bảng và chip; thứ tự tab = thứ tự đọc; scan box là tab đầu tiên của main.
- **Bàn phím (WEB/DEPT)**: mọi thao tác không cần chuột; Enter = quét/ghi sổ trong scan box; Esc đóng modal; `/` focus ô quét.
- **Ngữ nghĩa**: landmark (`nav`, `main`, `aside`), heading đúng cấp (H1 trang/H2 title/H3 card), `aria-live` cho toast và kết quả quét, `aria-label` tiếng Việt cho nút icon, bảng có `th scope`.
- **Reduced motion**: tắt transition/animation (#17 đã có).
- **Không chỉ màu**: badge/gate/stepper/flag luôn có chữ hoặc ký hiệu; zonebar lặp tên khu bằng chữ trong tag.
- **Kiosk**: tránh timeout ẩn — khóa phiên 10 phút (NFR-SEC-01) phải cảnh báo trước 60 s bằng banner.

## 6. Voice & Microcopy

Giọng: **ngắn, mệnh lệnh nhẹ, nghiệp vụ**; tiếng Việt chuẩn QĐ 3671 (khử khuẩn, tiệt khuẩn, chỉ thị hóa học/sinh học, Bowie-Dick, mẻ, lô rửa, cổng bước, giải phóng mẻ, cách ly, cơ số, hạn lưu). Xưng hô: không "bạn"; dùng vai trò/tên khi cần ("R02 có thể tiếp nhận cưỡng bức").

| Làm | Tránh |
| :-- | :-- |
| "Không dùng được. Gói CY-… đang **Đã sử dụng**. Trả về KSNK để tái xử lý." (kết quả → lý do → hành động) | "Lỗi! Thao tác không hợp lệ." |
| "Chưa thể xác nhận hoàn thành đóng gói — còn: xử lý nhắc tra dầu (1)." (nêu đúng mục còn thiếu) | "Vui lòng hoàn tất các bước." |
| "Ghi sổ phiếu tiếp nhận (3 bộ)" (nút mang số) | "Submit" / "OK" |
| "Quét thẻ nhân viên giao, rồi quét mã bộ." (empty state chỉ việc kế tiếp) | "Không có dữ liệu." |
| "Đạt" / "Không đạt" / "Chưa" | "Pass" / "Fail" / "N/A" (trừ nhãn in dòng phụ tiếng Anh) |

Lỗi chặn: đỏ, câu đầu bold nêu kết quả, câu sau lý do có mã nghiệp vụ (BRU-…) khi hữu ích cho R02, câu cuối hành động. Toast thành công: 1 câu bắt đầu bằng "Đã …". Cảnh báo sớm (cơ số ≥ 90 %, hạn 7 ngày): "Sắp …". Số: `184.500 ₫`, `47/300 chu trình (16%)`, `20/09/2026 09:58`.

Tone theo surface: STN/PDA ngắn nhất (≤ 12 từ/câu, nút ≤ 5 từ); WEB cho phép câu dài hơn trong alert quản lý; DEPT thân thiện hơn một chút với người ngoài KSNK nhưng vẫn không dùng "bạn".

## 7. Do's and Don'ts

- **Do** dùng token `--tc-*` cho mọi màu/khoảng cách/bán kính; **Don't** gõ hex/px trực tiếp.
- **Do** bắt đầu mọi màn trạm bằng scan box có focus; **Don't** đặt form nhập trên vùng quét.
- **Do** hiện lỗi chặn bằng `alert-error` inline đỏ toàn khối + hành động; **Don't** dùng modal/toast cho lỗi chặn nghiệp vụ.
- **Do** kèm chữ cho mọi trạng thái màu; **Don't** chỉ đổi màu nền để báo Đạt/Không đạt.
- **Do** dùng `--tc-warn-fill #B85A00` / `--tc-neutral-fill #6B6B6B` khi có chữ trắng; **Don't** đặt chữ trắng lên `#E36C09` hay `#7F7F7F`.
- **Do** mono cho mã; **Don't** mono cho câu văn.
- **Do** nút ≥ 48 px và cách nhau ≥ 12 px trên STN/PDA; **Don't** dùng nút 34 px ngoài bảng web.
- **Do** rail chỉ hiện trạm của khu; **Don't** cho trạm T1 thấy menu T4.
- **Do** giữ actions bar cố định với nhãn động; **Don't** rải nút Ghi sổ giữa trang.
- **Do** 4 trạng thái loading/empty/error/offline cho mỗi màn trạm; **Don't** màn trắng khi mất mạng.
- **Do** mở rộng Frappe qua `app_include_css` + Workflow State style; **Don't** sửa SCSS core hoặc tạo bộ màu riêng cho Desk.
- **Don't** thêm màu mới ngoài palette (kể cả "xanh nhạt hơn") — nếu cần, đề xuất amendment tokens.json.
- **Don't** dùng font web, icon font tải mạng, hoặc ảnh nền trang trí.

## 8. Agent Quick Reference

```
Nền trang #F4F6F9 · card #FFF viền #C8D8EE r6 p14×16 · chữ #1d1d1f 15px Arial · mã Courier New
Primary #1F4E79 (hover #17375E) · accent/link/focus #2E75B6 · soft #EBF3FB
Zone: dirty #C00000 · clean #E36C09 · sterile #375623 · dept navy · web blue → zonebar 8px trên cùng
Status fill: pass #375623 · fail #C00000 · warn #B85A00 (KHÔNG #E36C09) · neutral #6B6B6B (KHÔNG #7F7F7F)
Tint: pass #F2F7EE · fail #FFF2F2 · warn #FFF7EE · info #EBF3FB · stepper done #DCE9D5
Nút: primary 48px r5 p11×18 (STN/PDA 56px) · secondary trắng viền 1.5 navy · danger fail · ok pass · disabled #E5E5E5/#595959
Scan box: soft + dashed 2px navy r8 p12 · input mono 20px (STN 24) · nút Quét ≥110px · chips dưới
Stepper: pill r14 · pending trắng/#BFBFBF/#555 · done #DCE9D5/#375623 "✓" · current navy/trắng bold
Gate: 5 cổng + Vô khuẩn · ok tint pass "Đạt" · bad tint fail "Không đạt" · pending "Chưa"
Badge: r10 p2×9 11px bold trắng · g/o/r/x · count đỏ r11 trên nav
Alert: border-left 5px + tint · error/warn/ok/info · có nút hành động · không modal cho lỗi chặn
Layout: rail 250 trái · main p20×26 pb90 · actions bar fixed bottom border-top 2px navy · grid 2 cột gap 8×16 (≤900: 1 cột)
STN/PDA: chữ ≥16px · touch ≥48 · gap ≥12 · ≤3 chạm · offline indicator ở foot rail / footer PDA
Frappe: override --primary,--bg-color,--text-color,--border-color,--font-stack,indicator colors qua tracecore-theme.css
Mặc định: hành động chính → button-primary/ok trong actions bar · xác nhận PIN → modal 440 border-top 6 navy · thành công → toast pass 3.2s
```

Recipe một màn trạm: `zonebar(khu) → crumb → title(H2 + tag UC/SCR + badge) → stepper(T1–T8 current) → card[scan-box + chips] → card[kết quả: res/BOM/gates/form grid] → alert(nếu chặn) → actions bar[primary(count) · secondary · danger]`.

## 9. Provenance & Known Gaps

**Provenance (prose).** Hệ thống thiết kế được **ingest** từ BA #09 "Đặc tả Giao diện & Hệ thống Thiết kế v1.10" (bảng màu 9 token, font Arial/Segoe UI 11pt web · 14–16pt trạm · 16–18pt PDA, Courier New cho mã, thư viện 14 component, 5 archetype, 37 màn hình) và **extract** fidelity cao từ CSS của #17 "Giao diện theo vai trò v1.10" (file HTML chạy được, iframe `srcdoc` trong `input/BA_v1_10.html`: `:root` 10 biến, ~290 dòng CSS với đầy đủ class rail/stepper/scan/gates/label/phone/kpi/alert/badge/modal/toast và media query 900 px, `prefers-reduced-motion`, `:focus-visible`), được kiểm chứng bằng 21 ảnh `docs/design-refs/*.png` (xác nhận zonebar, rail, stepper, scan dashed, gate panel, kpi tint, badge, label preview, phone frame). Điều chỉnh theo SRS (ưu tiên cao hơn nguồn): nút 46 px → **48 px** (NFR-USAB-01); chữ trạm/PDA sàn **16 px** (NFR-ACC-01); 5 cặp màu không đạt AA được thay bằng token `aa-*` (xem §2.1); thêm nhóm `status.waste.*` và `zone.waste` cho M10 (v1.11, TT 20/2021); PIN 4 số demo → 6 số (NFR-SEC-01). Tool Projects không truy cập được trong phiên này nên #17 được lấy từ bản nhúng trong `BA_v1_10.html` (cùng v1.10 · 20/09/2026).

```json
{ "design_provenance": {
    "mode": "design-file",
    "mode_secondary": "images",
    "fidelity": "mapped",
    "source": null,
    "inputs": [
      "input/ba_md/d09.md (#09 UI v1.10)",
      "input/BA_v1_10.html › section#d17 iframe srcdoc (#17 Giao dien theo vai tro v1.10, CSS :root + classes)",
      "docs/design-refs/01..21_*.png (21 ảnh)"
    ],
    "overrides_from_srs": ["NFR-USAB-01", "NFR-USAB-02", "NFR-ACC-01", "NFR-L10N-01", "NFR-SEC-01"],
    "generated": "2026-10-17"
} }
```

**Known Gaps.**
1. **Ảnh thực tế chưa có** — #17 dùng placeholder `.photo`; ảnh dụng cụ/bộ sẽ được tải lên tại SCR-01/02 và import hàng loạt SCR-43. Tỷ lệ khung (1:1 thumb, 16:9 ảnh bộ) là giả định.
2. **Dark mode** chỉ phác cho WEB, chưa kiểm chứng; STN/PDA cố định sáng.
3. **Icon set chưa chọn** — #17 dùng emoji (📷) và ký tự (●, ✓). Đề xuất: Frappe icons (`frappe-icon`/`feather`) cho WEB, SVG inline 24 px stroke 2 cho STN/PDA; cần quyết định trước anchor screens.
4. **Hover/active/loading** của nhiều component không có trong #17 — giá trị §4 là đề xuất hợp lý, chưa được chủ đầu tư duyệt riêng.
5. **Breakpoint** chỉ có 900 px trong #17; 480/1366/1920 là suy ra từ NFR-COMPAT-01.
6. **Motion** không được định nghĩa trong nguồn; §2.2 đề xuất 120/200 ms.
7. **Frappe variable names** ánh xạ theo v15 `css_variables.scss`; cần xác nhận tên biến chính xác khi scaffold (một số theme biến đổi giữa 15.x).
8. **Signature pad**, **bàn phím số PIN**, **sheet PDA full-screen**, **banner cảnh báo khóa phiên** chưa có trong #17 — spec mới.
9. **Mã màu túi chất thải** (`status.waste.*`) là giá trị đề xuất dựa trên TT 20/2021, chưa đối chiếu mẫu túi thực tế của bệnh viện.
10. **Nhãn in**: kích thước thật (mm), DPI máy ZPL/TSPL và phông in chưa chốt; preview 280 px chỉ để đối chiếu nội dung.
11. **Print format** (phiếu PDF) chưa có token riêng — dùng cùng palette, đen trắng khi in.
