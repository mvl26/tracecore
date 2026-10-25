<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
	adminAPI,
	APIError,
	request,
	setCSRF,
	passwordResetPath,
	type Bootstrap,
	type RecordList,
} from "./api";
import MasterPanel from "./MasterPanel.vue";
import UnitPanel from "./UnitPanel.vue";

const route = useRoute(),
	router = useRouter();
const session = ref<Bootstrap | null>(null),
	busy = ref(true),
	error = ref(""),
	online = ref(navigator.onLine);
const username = ref(""),
	password = ref(""),
	otp = ref(""),
	challenge = ref(""),
	otpPrompt = ref("");
const list = ref<RecordList | null>(null),
	detail = ref<Record<string, unknown> | null>(null);
const search = ref(""),
	offset = ref(0),
	counts = ref<{ screen: string; title: string; count: number; capped: boolean }[]>([]);
const master = ref<{ name?: string } | null>(null),
	unit = ref<{ name?: string } | null>(null);
const attention = ref<{ screen: string; title: string; name: string; status: string }[]>([]);
const roleID = computed(() => String(route.path.split("/")[1] || ""));
const screenID = computed(() => String(route.path.split("/")[2] || ""));
const space = computed(() => session.value?.roles.find((x) => x.id === roleID.value));
const screen = computed(() => space.value?.screens.find((x) => x.id === screenID.value));
const home = computed(() => !roleID.value);
const title = computed(
	() =>
		screen.value?.title ||
		(space.value ? "Tổng quan · " + space.value.title : "Trung tâm quản trị"),
);
const statusText: Record<string, string> = {
	ready: "Sẵn sàng",
	forbidden: "Chưa có quyền dữ liệu",
	not_implemented: "Chưa sẵn sàng",
};
const labels: Record<string, string> = {
	name: "Mã",
	modified: "Cập nhật",
	instrument_name: "Tên dụng cụ",
	instrument_group: "Nhóm dụng cụ",
	status: "Trạng thái",
	version_no: "Phiên bản",
	max_cycles: "Cơ số tối đa",
	image: "Ảnh",
	set_type: "Loại bộ",
	method: "Phương pháp",
	current_bom_version: "BOM hiện hành",
	shelf_life_days: "Hạn lưu (ngày)",
	cycles_used: "Chu trình đã dùng",
	department: "Khoa",
	equipment_name: "Tên thiết bị",
	equipment_type: "Loại thiết bị",
	employee_name: "Họ tên",
	full_name: "Họ tên",
	reason: "Lý do",
	extra_cycles: "Chu trình thêm",
	valid_until: "Hiệu lực đến",
	set_unit: "Bộ dụng cụ",
	equipment: "Thiết bị",
	program: "Chương trình",
	result: "Kết quả",
	docstatus: "Chứng từ",
	is_active: "Đang hoạt động",
	station: "Trạm",
	zone_station_name: "Tên khu / trạm",
	station_step: "Bước",
	expiry: "Hạn dùng",
	timestamp: "Thời điểm",
	user: "Người thực hiện",
	action: "Hành động",
	ref_doctype: "Loại hồ sơ",
	ref_name: "Mã hồ sơ",
	item_name: "Tên vật tư",
	item_group: "Nhóm",
	stock_uom: "Đơn vị",
	disabled: "Ngừng dùng",
	enabled: "Kích hoạt",
	user_type: "Loại tài khoản",
};
const label = (field: string) => labels[field] || field.replaceAll("_", " ");
const stateLabels: Record<string, string> = {
	Active: "Đang dùng",
	Retired: "Ngừng dùng",
	New: "Mới cấp",
	Processing: "Đang xử lý",
	Sterile: "Vô khuẩn",
	Requested: "Đề nghị",
	Approved: "Đã duyệt",
	Rejected: "Từ chối",
	Locked: "Khóa",
	Ready: "Sẵn sàng",
	Packed: "Đã đóng gói",
	Released: "Đã giải phóng",
	Issued: "Đã cấp phát",
	Used: "Đã sử dụng",
	Void: "Hết hiệu lực",
	"In Sterile Stock": "Trong kho vô khuẩn",
	"In Load": "Trong mẻ",
	Quarantine: "Cách ly",
	Recalled: "Đã thu hồi",
};
const text = (value: unknown) => {
	if (value === null || value === undefined || value === "") return "—";
	if (typeof value === "object") return JSON.stringify(value);
	const raw = String(value);
	if (stateLabels[raw]) return stateLabels[raw];
	const date = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}:\d{2}))?(?:[:.\d]*)$/);
	return date ? `${date[3]}/${date[2]}/${date[1]}${date[4] ? " " + date[4] : ""}` : raw;
};
let generation = 0;
async function bootstrap() {
	busy.value = true;
	error.value = "";
	try {
		session.value = await adminAPI("bootstrap");
		setCSRF(session.value!.csrf_token);
		await load();
	} catch (e) {
		if (e instanceof APIError && [401, 403].includes(e.status)) session.value = null;
		else error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function login() {
	busy.value = true;
	error.value = "";
	try {
		const response = await request(
			"login",
			challenge.value
				? { otp: otp.value, tmp_id: challenge.value }
				: { usr: username.value, pwd: password.value },
			true,
			true,
		);
		password.value = "";
		if (response.message === "Password Reset") {
			const target = passwordResetPath(response.redirect_to || "", window.location.origin);
			if (!target) throw new Error("Tài khoản cần đổi mật khẩu. Liên hệ quản trị hệ thống.");
			window.location.assign(target);
			return;
		}
		if (response.verification && response.message !== "Logged In") {
			challenge.value = response.tmp_id;
			otpPrompt.value =
				response.verification.prompt ||
				"Nhập mã từ ứng dụng xác thực hoặc phương thức đã đăng ký.";
			// Initial authenticator enrollment needs the stock, audited Frappe enrollment flow.
			if (!response.verification.setup)
				otpPrompt.value =
					"Tài khoản cần thiết lập xác thực hai bước. Mở trang thiết lập an toàn để hoàn tất.";
			return;
		}
		if (!["Logged In", "No App"].includes(response.message))
			throw new Error("Đăng nhập chưa hoàn tất. Kiểm tra yêu cầu của tài khoản và thử lại.");
		challenge.value = "";
		otp.value = "";
		window.location.assign("/tracecore" + (route.path === "/login" ? "" : route.path));
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function logout() {
	busy.value = true;
	error.value = "";
	try {
		await request("logout", {}, true);
		session.value = null;
		list.value = null;
		detail.value = null;
		counts.value = [];
		await router.replace("/");
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function load() {
	const current = ++generation;
	busy.value = false;
	list.value = null;
	detail.value = null;
	master.value = null;
	unit.value = null;
	counts.value = [];
	attention.value = [];
	error.value = "";
	if (!session.value || home.value || route.path === "/login") return;
	if (!space.value) {
		error.value = "Không có quyền mở không gian này.";
		return;
	}
	if (screenID.value && !screen.value) {
		error.value = "Chức năng không thuộc không gian này.";
		return;
	}
	if (screen.value && screen.value.state !== "ready") return;
	busy.value = true;
	try {
		if (!screenID.value || screenID.value === "dashboard") {
			const data = await adminAPI("dashboard", { role: roleID.value });
			if (current === generation) {
				counts.value = data.counts;
				attention.value = data.attention;
			}
		} else {
			const data = await adminAPI("records", {
				role: roleID.value,
				screen: screenID.value,
				search: search.value,
				start: offset.value,
			});
			if (current === generation) list.value = data;
		}
	} catch (e) {
		if (current !== generation) return;
		if (e instanceof APIError && e.status === 401) {
			session.value = null;
			password.value = "";
		}
		error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
async function openRecord(name: unknown) {
	if (["instruments", "set-types"].includes(screenID.value)) {
		master.value = { name: String(name) };
		return;
	}
	if (screenID.value === "set-units") {
		unit.value = { name: String(name) };
		return;
	}
	const current = generation;
	error.value = "";
	busy.value = true;
	try {
		const data = await adminAPI("detail", {
			role: roleID.value,
			screen: screenID.value,
			name: String(name),
		});
		if (current === generation) detail.value = data.record;
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
function go(role = "", screen = "") {
	router.push("/" + role + (screen ? "/" + screen : ""));
}
function page(delta: number) {
	offset.value = Math.max(0, offset.value + delta);
	load();
}
function network() {
	online.value = navigator.onLine;
}
async function saved() {
	try {
		list.value = await adminAPI("records", {
			role: roleID.value,
			screen: screenID.value,
			search: search.value,
			start: offset.value,
		});
	} catch (e) {
		error.value = (e as Error).message;
	}
}
watch(
	() => route.path,
	() => {
		search.value = "";
		offset.value = 0;
		load();
	},
);
onMounted(() => {
	bootstrap();
	window.addEventListener("online", network);
	window.addEventListener("offline", network);
});
onUnmounted(() => {
	window.removeEventListener("online", network);
	window.removeEventListener("offline", network);
});
</script>

<template>
	<div v-if="!session" class="login-page">
		<form class="login-card" @submit.prevent="login">
			<div class="wordmark">TRACECORE</div>
			<p class="subtle">Quản lý vận hành Khoa Kiểm soát nhiễm khuẩn</p>
			<h1>{{ challenge ? "Xác thực hai bước" : "Đăng nhập" }}</h1>
			<template v-if="!challenge"
				><label for="user">Tài khoản</label
				><input
					id="user"
					v-model="username"
					autocomplete="username"
					required
					autofocus /><label for="password">Mật khẩu</label
				><input
					id="password"
					v-model="password"
					type="password"
					autocomplete="current-password"
					required
			/></template>
			<template v-else
				><p>{{ otpPrompt }}</p>
				<label for="otp">Mã xác thực</label
				><input
					id="otp"
					v-model="otp"
					inputmode="numeric"
					autocomplete="one-time-code"
					required
				/><a href="/login?redirect-to=%2Ftracecore"
					>Thiết lập / khôi phục xác thực</a
				></template
			>
			<p v-if="error" class="alert danger" role="alert">{{ error }}</p>
			<p v-if="!online" class="alert warning">Đang mất kết nối mạng.</p>
			<button class="primary wide" :disabled="busy || !online">
				{{ busy ? "Đang kết nối…" : "Tiếp tục" }}
			</button>
			<button
				v-if="challenge"
				type="button"
				class="secondary wide"
				@click="
					challenge = '';
					otp = '';
				"
			>
				Dùng tài khoản khác
			</button>
		</form>
	</div>
	<div v-else class="shell">
		<aside>
			<div class="brand">
				<div class="wordmark">TRACECORE</div>
				<p>Quản lý vận hành KSNK</p>
			</div>
			<button class="home-button" :class="{ active: home }" @click="go()">
				▦ &nbsp; {{ session.admin_overview ? "Admin tổng" : "Không gian làm việc" }}
			</button>
			<nav aria-label="Không gian theo vai trò">
				<template v-for="role in session.roles" :key="role.id">
					<button
						class="role-button"
						:class="{ active: roleID === role.id }"
						@click="go(role.id)"
					>
						<small>{{ role.id }}</small
						>{{ role.title }}
					</button>
					<template v-if="roleID === role.id"
						><button
							v-for="item in role.screens"
							:key="item.id"
							class="screen-button"
							:class="{ active: screenID === item.id }"
							@click="go(role.id, item.id)"
						>
							{{ item.title
							}}<span v-if="item.state !== 'ready'" aria-label="Chưa sẵn sàng">
								·</span
							>
						</button></template
					>
				</template>
			</nav>
			<footer>
				<strong>{{ session.full_name || session.user }}</strong>
				<p>{{ online ? "Trực tuyến" : "Mất kết nối" }}</p>
				<button class="secondary" :disabled="busy || !online" @click="logout">
					Đăng xuất
				</button>
			</footer>
		</aside>
		<section class="workspace">
			<header>
				<div>
					<b>{{ space ? "Đang xem: " + space.title : "Trung tâm TraceCore" }}</b
					><small>Danh tính: {{ session.full_name || session.user }}</small>
				</div>
				<button class="secondary" @click="go()">Về trang tổng</button>
			</header>
			<div class="zonebar" :class="roleID"></div>
			<main>
				<div class="breadcrumb">
					<button @click="go()">TraceCore</button
					><template v-if="space"> / {{ space.title }}</template
					><template v-if="screen"> / {{ screen.title }}</template>
				</div>
				<div class="heading">
					<div>
						<h1>{{ home ? "Không gian làm việc TraceCore" : title }}</h1>
						<p class="subtle">
							{{
								home
									? "Chọn vai trò để mở các trang nghiệp vụ tương ứng."
									: space?.description
							}}
						</p>
					</div>
					<span v-if="space" class="badge">{{ space.id }}</span>
				</div>
				<p v-if="!online" class="alert warning" role="status">
					Mất kết nối. Dữ liệu đang hiển thị có thể chưa cập nhật.
				</p>
				<div v-if="error" class="alert danger" role="alert">
					{{ error }} <button class="secondary" @click="load">Thử lại</button>
				</div>
				<p v-if="busy" role="status" class="loading">Đang tải dữ liệu…</p>
				<div v-else-if="home" class="role-grid">
					<button
						v-for="role in session.roles"
						:key="role.id"
						class="role-card"
						@click="go(role.id)"
					>
						<span class="badge">{{ role.id }}</span>
						<h2>{{ role.title }}</h2>
						<p>{{ role.description }}</p>
						<span class="open-space">Mở không gian →</span>
					</button>
					<div v-if="!session.roles.length" class="card empty">
						Tài khoản chưa được cấp vai trò TraceCore. Liên hệ quản trị hệ thống.
					</div>
				</div>
				<template v-else-if="space && (!screenID || screenID === 'dashboard') && !error">
					<div class="card">
						<h2>
							{{
								roleID === "R01"
									? "Cần quyết định của Trưởng khoa"
									: "Việc cần theo dõi"
							}}
						</h2>
						<div
							v-for="item in attention"
							:key="item.screen + item.name"
							class="alert"
							:class="item.screen === 'equipment' ? 'warning' : 'danger'"
						>
							<div>
								<b>{{ item.title }} · {{ item.name }}</b>
								<p>{{ text(item.status) }}</p>
							</div>
							<button class="secondary" @click="go(roleID, item.screen)">
								Xem hồ sơ
							</button>
						</div>
						<p v-if="!attention.length" class="empty">
							Không có cảnh báo từ các nguồn dữ liệu hiện hỗ trợ.
						</p>
					</div>
					<div class="card">
						<h2>Tổng quan hồ sơ</h2>
						<p class="subtle">
							Số lượng là tổng hồ sơ được phép đọc, không phải số việc chờ duyệt.
						</p>
						<div v-if="counts.length" class="stats">
							<button
								v-for="item in counts"
								:key="item.screen"
								@click="go(roleID, item.screen)"
							>
								<strong>{{ item.count }}{{ item.capped ? "+" : "" }}</strong
								><span>{{ item.title }}</span>
							</button>
						</div>
						<p v-else class="empty">
							Chưa có nguồn dữ liệu sẵn sàng cho tài khoản này.
						</p>
					</div>
					<div class="card">
						<h2>Chức năng trong không gian</h2>
						<div class="feature-grid">
							<button
								v-for="item in space.screens.filter((x) => x.id !== 'dashboard')"
								:key="item.id"
								@click="go(roleID, item.id)"
							>
								<b>{{ item.title }}</b
								><span class="subtle">{{ statusText[item.state] }}</span>
							</button>
						</div>
					</div>
				</template>
				<div v-else-if="screen && screen.state !== 'ready'" class="card empty">
					<h2>{{ screen.title }}</h2>
					<p>
						{{
							screen.state === "forbidden"
								? "Tài khoản chưa được cấp quyền đọc dữ liệu cho chức năng này."
								: "Chức năng này đang chờ hoàn thiện backend hoặc giao diện nghiệp vụ."
						}}
					</p>
					<p class="subtle">Không có dữ liệu minh họa trong ứng dụng.</p>
				</div>
				<section v-else-if="list && !error" class="card">
					<form
						class="filters"
						@submit.prevent="
							offset = 0;
							load();
						"
					>
						<input
							v-model="search"
							aria-label="Tìm theo mã"
							placeholder="Tìm theo mã hồ sơ…"
							maxlength="140"
						/><button class="primary" :disabled="!online">Tìm kiếm</button
						><button type="button" class="secondary" :disabled="!online" @click="load">
							Làm mới</button
						><button
							v-if="list.can_create"
							type="button"
							class="primary"
							:disabled="!online"
							@click="master = {}"
						>
							Thêm mới</button
						><button
							v-if="list.can_issue"
							type="button"
							class="primary"
							:disabled="!online"
							@click="unit = {}"
						>
							Cấp Set ID
						</button>
					</form>
					<div v-if="list.rows.length" class="table-scroll">
						<table>
							<thead>
								<tr>
									<th>Mã hồ sơ</th>
									<th
										v-for="field in list.fields
											.filter((f) => f !== 'image')
											.slice(0, 5)"
										:key="field"
									>
										{{ label(field) }}
									</th>
									<th>Cập nhật</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="row in list.rows" :key="String(row.name)">
									<td>
										<button class="record-link" @click="openRecord(row.name)">
											{{ row.name }}
										</button>
									</td>
									<td
										v-for="field in list.fields
											.filter((f) => f !== 'image')
											.slice(0, 5)"
										:key="field"
									>
										<span :class="{ badge: field === 'status' }">{{
											text(row[field])
										}}</span>
									</td>
									<td>{{ text(row.modified) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
					<p v-else class="empty">
						Không có hồ sơ phù hợp trong phạm vi quyền truy cập.
					</p>
					<div class="pagination">
						<button class="secondary" :disabled="offset === 0" @click="page(-25)">
							← Trước</button
						><span>{{ offset + 1 }}–{{ offset + list.rows.length }} hồ sơ</span
						><button class="secondary" :disabled="!list.has_more" @click="page(25)">
							Sau →
						</button>
					</div>
				</section>
				<div v-if="detail" class="modal-backdrop" @click.self="detail = null">
					<section
						role="dialog"
						aria-modal="true"
						aria-labelledby="record-title"
						class="detail-modal"
					>
						<div class="heading">
							<h2 id="record-title">{{ detail.name }}</h2>
							<button class="secondary" autofocus @click="detail = null">
								Đóng
							</button>
						</div>
						<dl>
							<template v-for="(value, field) in detail" :key="field"
								><dt>{{ label(String(field)) }}</dt>
								<dd>{{ text(value) }}</dd></template
							>
						</dl>
						<p class="subtle">Dữ liệu thật · Chỉ hiển thị các trường được phép.</p>
					</section>
				</div>
				<MasterPanel
					v-if="master"
					:role="roleID"
					:screen="screenID"
					:name="master.name"
					@close="master = null"
					@saved="saved"
				/>
				<UnitPanel v-if="unit" :name="unit.name" @close="unit = null" @saved="saved" />
			</main>
		</section>
	</div>
</template>
