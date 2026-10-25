<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { request, createBusinessMutation, type Bootstrap } from "./api";

const props = defineProps<{ session: Bootstrap }>();
const emit = defineEmits<{ logout: [] }>();
const route = useRoute(),
	router = useRouter();
const view = computed(() => String(route.path.split("/")[2] || "assembly"));
const step = computed(() => (view.value === "packs" ? "T4" : "T3"));
const stationView = computed(() => ["assembly", "packs", "dashboard"].includes(view.value));
const title = computed(
	() =>
		({
			assembly: "T3 · Kiểm tra – lắp ráp",
			dashboard: "T3 · Kiểm tra – lắp ráp",
			packs: "T4 · Đóng gói",
			instruments: "Tra cứu dụng cụ",
			overrides: "Đề nghị của tôi",
			history: "Lịch sử thực hiện",
		})[view.value] || "Không tìm thấy chức năng",
);
const data = ref<any>(null),
	opened = ref<any>(null),
	rows = ref<any[]>([]);
const requestsAvailable = ref(true);
const online = ref(navigator.onLine);
const raw = ref(""),
	search = ref(""),
	error = ref(""),
	message = ref(""),
	busy = ref(false);
const selectedStation = ref(""),
	card = ref(""),
	token = ref(""),
	actor = ref("");
const checked = ref<string[]>([]),
	queueMode = ref(""),
	ciRaw = ref(""),
	ci = ref(""),
	packType = ref("");
const packing = ref<any>(null),
	result = ref<any>(null),
	reason = ref("");
const maintenance = ref<Record<string, boolean>>({}),
	oilBatches = ref<Record<string, string>>({});
const mutate = createBusinessMutation();
let generation = 0,
	heartbeat: ReturnType<typeof setInterval> | undefined;
const lines = computed<any[]>(() => packing.value?.bom || opened.value?.bom?.lines || []);
const exceeded = computed(() => opened.value?.par?.state === "blocked");
const canPack = computed(
	() =>
		token.value &&
		packing.value &&
		lines.value.length > 0 &&
		checked.value.length === lines.value.length &&
		ci.value &&
		packType.value &&
		(packing.value.maintenance || []).every(
			(x: any) =>
				maintenance.value[x.instrument] &&
				(x.maint_type !== "Lubrication" || oilBatches.value[x.instrument]?.trim()),
		),
);
const menus = [
	{ id: "assembly", label: "T3 · Kiểm tra – lắp ráp" },
	{ id: "packs", label: "T4 · Đóng gói" },
	{ id: "instruments", label: "Tra cứu dụng cụ" },
	{ id: "history", label: "Lịch sử thực hiện" },
	{ id: "overrides", label: "Đề nghị của tôi" },
];
const ktv = (method: string, args: Record<string, unknown> = {}) =>
	request("tracecore.v1.ktv." + method, args);
function resetSet() {
	opened.value = null;
	packing.value = null;
	checked.value = [];
	ci.value = "";
	ciRaw.value = "";
	packType.value = "";
	result.value = null;
	maintenance.value = {};
	oilBatches.value = {};
	reason.value = "";
}
async function closeStation(invalidate = true) {
	if (invalidate) {
		++generation;
		busy.value = false;
	}
	const previous = token.value;
	token.value = "";
	actor.value = "";
	resetSet();
	if (heartbeat) clearInterval(heartbeat);
	if (previous) {
		try {
			await request(
				"tracecore.v1.station.logout",
				{ token: previous, client_ts: new Date().toISOString() },
				true,
			);
		} catch {
			/* local credentials are already discarded */
		}
	}
}
async function refresh() {
	const current = ++generation;
	busy.value = true;
	error.value = "";
	rows.value = [];
	queueMode.value = "";
	try {
		const info = await ktv("workspace", { step: step.value });
		if (current !== generation) return;
		data.value = info;
		selectedStation.value = info.stations[0]?.name || "";
		let records: any[] = [];
		if (view.value === "overrides") {
			const own = await ktv("personal_requests");
			if (current !== generation) return;
			requestsAvailable.value = own.available;
			records = own.rows;
		}
		if (view.value === "instruments")
			records = (
				await request("tracecore.v1.admin_ui.records", {
					role: "R04",
					screen: "instruments",
					search: search.value,
				})
			).rows;
		if (view.value === "history") records = await ktv("history");
		if (current === generation) rows.value = records;
	} catch (e) {
		if (current === generation) error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
async function loginStation() {
	const current = generation,
		station = selectedStation.value;
	busy.value = true;
	error.value = "";
	try {
		const response = await request(
			"tracecore.v1.station.login",
			{
				card_id: card.value,
				station: selectedStation.value,
				client_ts: new Date().toISOString(),
			},
			true,
		);
		if (!response.ok || !response.session?.token) throw new Error("Không mở được phiên trạm.");
		if (current !== generation || station !== selectedStation.value) {
			await request(
				"tracecore.v1.station.logout",
				{ token: response.session.token, client_ts: new Date().toISOString() },
				true,
			);
			return;
		}
		// A browser role preview must never execute as somebody else's station identity.
		if (response.session.user !== props.session.user) {
			await request(
				"tracecore.v1.station.logout",
				{ token: response.session.token, client_ts: new Date().toISOString() },
				true,
			);
			throw new Error(
				"Thẻ phải thuộc tài khoản đang đăng nhập. Hãy đổi tài khoản trước khi thao tác.",
			);
		}
		token.value = response.session.token;
		actor.value = response.session.employee_name;
		card.value = "";
		resetSet();
		heartbeat = setInterval(checkSession, 60000);
	} catch (e) {
		if (current === generation) error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
async function checkSession() {
	if (!token.value) return;
	const previous = token.value;
	try {
		const response = await request(
			"tracecore.v1.station.heartbeat",
			{ token: previous, client_ts: new Date().toISOString() },
			true,
		);
		if (!response.ok) throw new Error("Session expired");
	} catch {
		if (previous !== token.value) return;
		await closeStation();
		error.value = "Phiên trạm hết hạn hoặc mất kết nối. Quét thẻ lại trước khi tiếp tục.";
	}
}
async function scan(id = raw.value) {
	const current = generation;
	busy.value = true;
	error.value = "";
	message.value = "";
	resetSet();
	try {
		const context = await ktv("context", { set_id: id.trim(), step: step.value });
		if (current !== generation) return;
		opened.value = context;
		raw.value = opened.value.set.name;
		if (step.value === "T4" && token.value) {
			const response = await mutate("tracecore.v1.pack.scan", {
				raw: id.trim(),
				station: selectedStation.value,
				token: token.value,
			});
			if (current !== generation) return;
			if (!response.ok || response.kind !== "context")
				throw new Error("Mã quét chưa mở được ngữ cảnh đóng gói.");
			packing.value = response.context;
		}
	} catch (e) {
		if (current === generation) error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
async function resolveCI() {
	const current = generation;
	busy.value = true;
	error.value = "";
	ci.value = "";
	try {
		const response = await mutate("tracecore.v1.pack.resolve_ci", {
			raw: ciRaw.value,
			open_set: raw.value,
			station: selectedStation.value,
			token: token.value,
		});
		if (current !== generation) return;
		if (!response.ok) throw new Error("Lô chỉ thị chưa hợp lệ.");
		ci.value = response.ci.batch;
	} catch (e) {
		if (current === generation) error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
async function completePack() {
	if (!canPack.value || busy.value) return;
	const current = generation;
	busy.value = true;
	error.value = "";
	try {
		const response = await mutate("tracecore.v1.pack.generate_cycle_id", {
			set_id: opened.value.set.name,
			station: selectedStation.value,
			token: token.value,
			confirmed_lines: checked.value,
			ci_batch: ci.value,
			pack_type: packType.value,
			maint_actions: (packing.value.maintenance || []).map((x: any) => ({
				instrument: x.instrument,
				action: "Done",
				...(x.maint_type === "Lubrication"
					? { oil_batch: oilBatches.value[x.instrument] }
					: {}),
			})),
		});
		if (current !== generation) return;
		if (!response.ok) throw new Error("Chưa hoàn tất đóng gói. Kiểm tra điều kiện của bộ.");
		result.value = response;
		packing.value = null;
		message.value = "Đã tạo Cycle ID. Kiểm tra kết quả in bên dưới.";
		const refreshed = await ktv("workspace", { step: "T4" });
		if (current === generation) data.value = refreshed;
	} catch (e) {
		if (current === generation) error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
async function requestOverride() {
	if (!token.value || !reason.value.trim() || busy.value) return;
	const current = generation;
	busy.value = true;
	error.value = "";
	try {
		const response = await mutate("tracecore.v1.par.override.request", {
			set_id: opened.value.set.name,
			reason: reason.value,
			station: selectedStation.value,
			token: token.value,
		});
		if (current !== generation) return;
		if (!response.ok) throw new Error("Chưa gửi được đề nghị.");
		message.value = "Đã gửi đề nghị. Chờ người có thẩm quyền duyệt trước khi tiếp tục.";
		reason.value = "";
	} catch (e) {
		if (current === generation) error.value = (e as Error).message;
	} finally {
		if (current === generation) busy.value = false;
	}
}
function visibility() {
	if (document.visibilityState === "visible") checkSession();
}
function network() {
	online.value = navigator.onLine;
	if (!online.value) closeStation();
}
async function enterView() {
	const current = ++generation;
	await closeStation(false);
	if (current !== generation) return;
	raw.value = "";
	message.value = "";
	await refresh();
	if (stationView.value && typeof route.query.set === "string") await scan(route.query.set);
}
watch(view, enterView);
onMounted(() => {
	enterView();
	document.addEventListener("visibilitychange", visibility);
	window.addEventListener("online", network);
	window.addEventListener("offline", network);
});
onUnmounted(() => {
	generation++;
	closeStation();
	document.removeEventListener("visibilitychange", visibility);
	window.removeEventListener("online", network);
	window.removeEventListener("offline", network);
});
</script>

<template>
	<div class="ktv-shell">
		<aside class="ktv-sidebar">
			<div class="ktv-identity">
				<strong>{{ session.full_name }}</strong>
				<p>KTV khu sạch · R04</p>
				<small>{{ actor || "Không gian làm việc TraceCore" }}</small>
			</div>
			<nav aria-label="Chức năng KTV">
				<RouterLink
					v-for="item in menus"
					:key="item.id"
					:to="'/R04/' + item.id"
					:class="{
						selected:
							view === item.id || (view === 'dashboard' && item.id === 'assembly'),
					}"
					>{{ item.label }}</RouterLink
				>
			</nav>
			<footer>
				<p>{{ token ? "● Phiên trạm đang hoạt động" : "● Chế độ xem" }}</p>
				<RouterLink v-if="session.admin_overview" to="/">Về trang tổng</RouterLink
				><button :disabled="busy" @click="closeStation().then(() => emit('logout'))">
					Đăng xuất
				</button>
			</footer>
		</aside>
		<main class="ktv-main" :aria-busy="busy">
			<p v-if="!online" class="ktv-error" role="alert">
				Mất kết nối. Phiên thao tác đã khóa; kết nối lại và quét thẻ trước khi tiếp tục.
			</p>
			<div class="ktv-zone"></div>
			<p class="ktv-breadcrumb">TraceCore › KTV khu sạch › {{ title }}</p>
			<h1>{{ title }} <small>Khu sạch · R04</small></h1>
			<div v-if="error" class="ktv-error" role="alert">{{ error }}</div>
			<div v-if="message" class="ktv-notice" role="status">{{ message }}</div>
			<template v-if="stationView">
				<div class="ktv-steps" aria-label="Tiến trình">
					<span>T1 Tiếp nhận</span><span>T2 Rửa</span
					><RouterLink to="/R04/assembly" :class="{ active: step === 'T3' }"
						>T3 Lắp ráp</RouterLink
					><RouterLink to="/R04/packs" :class="{ active: step === 'T4' }"
						>T4 Đóng gói</RouterLink
					><span>T5 Tiệt khuẩn</span><span>T6 Kho VK</span><span>T7 Cấp phát</span
					><span>T8 Sử dụng</span>
				</div>
				<div class="ktv-stats">
					<button @click="queueMode = queueMode === 'waiting' ? '' : 'waiting'">
						<strong>{{ data?.waiting ?? "—" }}{{ data?.capped ? "+" : "" }}</strong
						><span>Bộ chờ {{ step }}</span></button
					><button @click="router.push('/R04/history')">
						<strong
							>{{ data?.completed ?? "—"
							}}{{ data?.completed > 1000 ? "+" : "" }}</strong
						><span>Hồ sơ hoàn tất, cập nhật hôm nay</span></button
					><button @click="queueMode = queueMode === 'issues' ? '' : 'issues'">
						<strong>{{ data?.issues?.length ?? "—" }}</strong
						><span>Bộ cần xử lý lại</span>
					</button>
				</div>
				<section v-if="queueMode" class="ktv-card">
					<h2>
						{{
							queueMode === "waiting"
								? "Bộ sẵn sàng tại " + step
								: "Bộ cần xử lý lại"
						}}
					</h2>
					<p v-if="!(queueMode === 'waiting' ? data?.queue : data?.issues)?.length">
						Chưa có bộ trong danh sách.
					</p>
					<div class="ktv-chips">
						<button
							v-for="item in queueMode === 'waiting' ? data?.queue : data?.issues"
							:key="item.name"
							:disabled="busy"
							@click="scan(item.name)"
						>
							{{ item.name }} · {{ item.set_type }}
						</button>
					</div>
					<small
						>Danh sách theo quyền tài khoản, tối đa 100 bộ; đếm trên 1.000 bộ cập nhật
						gần nhất.</small
					>
				</section>
				<section class="ktv-card ktv-access">
					<div>
						<strong>{{
							token ? "Đã xác thực: " + actor : "Xác thực thẻ để thao tác tại trạm"
						}}</strong>
						<p v-if="!data?.card_ready">
							Môi trường chưa sẵn sàng xác thực thẻ. Bạn vẫn có thể tra cứu bộ và
							BOM.
						</p>
						<p v-else-if="!token">
							Chọn trạm và quét thẻ nhân viên của tài khoản đang đăng nhập.
						</p>
					</div>
					<form v-if="!token" @submit.prevent="loginStation">
						<select
							v-model="selectedStation"
							aria-label="Trạm thao tác"
							:disabled="busy"
						>
							<option value="">Chọn trạm</option>
							<option
								v-for="station in data?.stations"
								:key="station.name"
								:value="station.name"
							>
								{{ station.zone_station_name || station.name }}
							</option></select
						><input
							v-model="card"
							type="password"
							placeholder="Quét thẻ nhân viên"
							aria-label="Thẻ nhân viên"
							autocomplete="off"
							:disabled="busy || !data?.card_ready"
						/><button
							:disabled="busy || !card || !selectedStation || !data?.card_ready"
						>
							Mở phiên trạm
						</button>
					</form>
					<button v-else :disabled="busy" @click="closeStation()">Khóa trạm</button>
				</section>
				<section class="ktv-card">
					<h2>Chọn bộ để {{ step === "T3" ? "kiểm đếm" : "đóng gói" }}</h2>
					<form class="ktv-scan" @submit.prevent="scan()">
						<input
							v-model="raw"
							aria-label="Set ID"
							placeholder="Quét hoặc nhập Set ID…"
							:disabled="busy"
							autofocus
						/><button class="primary" :disabled="busy || !raw.trim()">
							{{ busy ? "Đang xử lý…" : "Quét bộ" }}
						</button>
					</form>
					<p class="ktv-muted">
						Dùng mã Set ID thật. Dữ liệu kiểm tra hiển thị theo chu trình hiện tại của
						bộ.
					</p>
				</section>
				<template v-if="opened">
					<section class="ktv-card">
						<h2>
							{{ opened.set.name }}
							<small>{{ opened.bom.set_type_name || opened.set.set_type }}</small>
						</h2>
						<div class="ktv-set-summary">
							<span>Chu trình {{ opened.set.current_cycle_no }}</span
							><span>{{ opened.set.status }}</span
							><span
								>Cơ số {{ opened.set.cycles_used }} /
								{{ opened.set.max_cycles || "—" }}</span
							><span>BOM v{{ opened.bom.bom_version }}</span>
						</div>
						<div class="ktv-chips">
							<span v-for="gate in opened.gates" :key="gate.step"
								>{{ gate.step }} · {{ gate.result }}</span
							>
						</div>
					</section>
					<section v-if="exceeded" class="ktv-card ktv-warning">
						<h2>Bộ đã đạt cơ số</h2>
						<p>Cần quyết định của người có thẩm quyền trước khi tiếp tục.</p>
						<label
							>Lý do đề nghị sử dụng vượt cơ số<textarea
								v-model="reason"
								:disabled="busy"
							/></label
						><button
							:disabled="busy || !token || !reason.trim()"
							@click="requestOverride"
						>
							Gửi đề nghị sử dụng vượt cơ số
						</button>
					</section>
					<section class="ktv-card">
						<h2>
							Ảnh bộ & danh sách dụng cụ
							<small>{{ checked.length }} / {{ lines.length }} dòng đã kiểm</small>
						</h2>
						<div class="ktv-bom-layout">
							<div class="ktv-tray">
								<img
									v-if="opened.bom.tray_images?.[0]?.image_url"
									:src="opened.bom.tray_images[0].image_url"
									alt="Ảnh khay dụng cụ"
								/>
								<p v-else>Chưa có ảnh khay cho phiên bản BOM này.</p>
							</div>
							<div class="ktv-table-scroll">
								<table>
									<thead>
										<tr>
											<th>Đã kiểm</th>
											<th>Dụng cụ</th>
											<th>Số lượng</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="line in lines" :key="line.instrument">
											<td>
												<input
													v-model="checked"
													type="checkbox"
													:value="line.instrument"
													:aria-label="'Đã kiểm ' + line.instrument"
													:disabled="busy || !!result"
												/>
											</td>
											<td>
												<img
													v-if="line.thumbnail || line.image"
													class="ktv-thumb"
													:src="line.thumbnail || line.image"
													alt=""
												/>{{ line.instrument_name || line.instrument
												}}<small>{{ line.instrument }}</small>
											</td>
											<td>{{ line.qty }}</td>
										</tr>
										<tr v-if="!lines.length">
											<td colspan="3">
												Chưa có BOM khả dụng. Không thể hoàn tất.
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
						<p class="ktv-muted">
							Đánh dấu sau khi kiểm đếm và kiểm tra tình trạng thực tế của từng dòng.
						</p>
					</section>
					<section v-if="step === 'T3'" class="ktv-card">
						<h2>Kết quả kiểm tra – lắp ráp</h2>
						<p class="ktv-warning">
							{{
								data?.assembly_ready
									? "Chức năng ghi nhận T3 chưa sẵn sàng trên môi trường này. Các đánh dấu chỉ phục vụ đối chiếu, chưa lưu hồ sơ."
									: "Chức năng ghi nhận T3 chưa sẵn sàng trên môi trường này. Các đánh dấu chỉ phục vụ đối chiếu, chưa lưu hồ sơ hoặc thay đổi cổng kiểm soát."
							}}
						</p>
						<button disabled>Hoàn tất T3</button
						><RouterLink :to="{ path: '/R04/packs', query: { set: opened.set.name } }"
							>Mở bộ này tại T4</RouterLink
						>
					</section>
					<section v-if="step === 'T4' && !result" class="ktv-card">
						<h2>Vật tư đóng gói & chỉ thị</h2>
						<p v-if="!packing">
							Quét thẻ và quét lại bộ để máy chủ kiểm tra cổng T3, cơ số, bảo dưỡng
							và vật tư.
						</p>
						<template v-else
							><label
								>Loại gói<select v-model="packType" :disabled="busy">
									<option value="">Chọn loại gói</option>
									<option
										v-for="item in packing.pack_types"
										:key="item.item"
										:value="item.item"
									>
										{{ item.item }} · Hạn {{ item.expected_expiry }}
									</option>
								</select></label
							>
							<form class="ktv-inline" @submit.prevent="resolveCI">
								<input
									v-model="ciRaw"
									placeholder="Quét mã lô chỉ thị"
									aria-label="Lô chỉ thị"
									:disabled="busy"
									@input="ci = ''"
								/><button :disabled="busy || !ciRaw">Kiểm tra lô</button>
							</form>
							<p v-if="ci">Lô đã xác thực: {{ ci }}</p>
							<label v-for="item in packing.maintenance" :key="item.instrument"
								><input
									v-model="maintenance[item.instrument]"
									type="checkbox"
									:disabled="busy" />
								Đã bảo dưỡng {{ item.instrument }} theo hướng dẫn<input
									v-if="item.maint_type === 'Lubrication'"
									v-model="oilBatches[item.instrument]"
									:aria-label="'Lô dầu ' + item.instrument"
									placeholder="Quét hoặc nhập lô dầu bôi trơn"
									:disabled="busy" /></label
							><button
								class="primary"
								:disabled="busy || !canPack"
								@click="completePack"
							>
								Hoàn tất đóng gói & tạo nhãn
							</button></template
						>
					</section>
					<section v-if="result" class="ktv-card" role="status">
						<h2>Kết quả đóng gói</h2>
						<p>{{ result.pack?.name || result.pack?.cycle_id }}</p>
						<img
							v-if="result.datamatrix_png_b64"
							:src="'data:image/png;base64,' + result.datamatrix_png_b64"
							alt="Nhãn DataMatrix"
						/>
						<p>{{ result.hri }}</p>
						<p>Trạng thái in: {{ result.print?.status || "Chưa có kết quả" }}</p>
						<p v-if="result.print?.warning">{{ result.print.warning }}</p>
					</section>
				</template>
			</template>
			<section v-else class="ktv-card">
				<form v-if="view === 'instruments'" class="ktv-inline" @submit.prevent="refresh">
					<input
						v-model="search"
						placeholder="Tìm theo mã dụng cụ"
						aria-label="Tìm dụng cụ"
					/><button :disabled="busy">Tìm kiếm</button>
				</form>
				<p v-if="view === 'overrides'">
					Chỉ hiển thị đề nghị do tài khoản {{ session.user }} tạo; KTV không duyệt đề
					nghị.
				</p>
				<p v-if="view === 'overrides' && !requestsAvailable" class="ktv-warning">
					Chức năng đề nghị vượt cơ số chưa được cài trên môi trường này.
				</p>
				<p v-if="view === 'history'">
					Hồ sơ do tài khoản hiện tại tạo, tối đa 100 hồ sơ mỗi loại.
				</p>
				<div class="ktv-table-scroll">
					<table>
						<thead>
							<tr>
								<th>Mã hồ sơ</th>
								<th>
									{{ view === "instruments" ? "Tên dụng cụ" : "Bộ dụng cụ" }}
								</th>
								<th>
									{{
										view === "instruments"
											? "Trạng thái"
											: "Kết quả / trạng thái"
									}}
								</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="row in rows" :key="row.name">
								<td>{{ row.name }}</td>
								<td>{{ row.instrument_name || row.set_unit }}</td>
								<td>
									{{
										row.status ||
										row.result ||
										(row.docstatus === 1 ? "Đã hoàn tất" : "Bản nháp")
									}}
								</td>
							</tr>
							<tr v-if="!rows.length">
								<td colspan="3">
									{{ busy ? "Đang tải…" : "Chưa có dữ liệu phù hợp." }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</section>
		</main>
	</div>
</template>

<style scoped>
.ktv-shell {
	display: grid;
	grid-template-columns: var(--tc-rail-w) minmax(0, 1fr);
	min-height: 100vh;
	color: var(--tc-text);
}
.ktv-sidebar {
	background: var(--tc-card);
	border-right: var(--tc-bw-hair) solid var(--tc-line);
	display: flex;
	flex-direction: column;
	position: sticky;
	top: 0;
	height: 100vh;
}
.ktv-identity {
	padding: var(--tc-sp-6);
	border-bottom: var(--tc-bw-hair) solid var(--tc-line);
}
.ktv-identity strong {
	font-size: var(--tc-fs-2xl);
	color: var(--tc-primary);
}
.ktv-identity p {
	margin: var(--tc-sp-2) 0;
}
.ktv-sidebar nav {
	padding: var(--tc-sp-4) 0;
	flex: 1;
}
.ktv-sidebar nav a {
	display: block;
	padding: var(--tc-sp-4-5) var(--tc-sp-6);
	text-decoration: none;
	border-left: var(--tc-bw-alert) solid transparent;
}
.ktv-sidebar nav a.selected {
	background: var(--tc-bg);
	border-left-color: var(--tc-primary);
	font-weight: var(--tc-fw-bold);
}
.ktv-sidebar footer {
	padding: var(--tc-sp-5);
	border-top: var(--tc-bw-hair) solid var(--tc-line);
}
.ktv-sidebar footer a {
	display: block;
	margin-bottom: var(--tc-sp-4);
}
.ktv-main {
	padding: var(--tc-sp-6) var(--tc-sp-8) var(--tc-sp-12);
	min-width: 0;
}
.ktv-zone {
	height: var(--tc-zonebar-h);
	background: var(--tc-warn);
}
.ktv-breadcrumb {
	font-size: var(--tc-fs-md);
	margin: var(--tc-sp-2) 0 var(--tc-sp-4-5);
}
.ktv-main h1 {
	font-size: var(--tc-fs-4xl);
	color: var(--tc-primary);
	margin: 0 0 var(--tc-sp-6);
}
.ktv-main small {
	font-size: var(--tc-fs-sm);
	font-weight: var(--tc-fw-regular);
}
.ktv-main h1 small {
	display: inline-block;
	border: var(--tc-bw-hair) solid var(--tc-line);
	padding: var(--tc-sp-1) var(--tc-sp-2-5);
	vertical-align: middle;
	background: var(--tc-card);
}
.ktv-steps,
.ktv-chips {
	display: flex;
	gap: var(--tc-sp-2);
	flex-wrap: wrap;
	margin: var(--tc-sp-4) 0;
}
.ktv-steps > * {
	border: var(--tc-bw-hair) solid var(--tc-line);
	padding: var(--tc-sp-2) var(--tc-sp-3);
	border-radius: var(--tc-r-full);
	background: var(--tc-card);
	text-decoration: none;
	font-size: var(--tc-fs-md);
}
.ktv-steps .active {
	background: var(--tc-primary);
	color: var(--tc-on-primary);
}
.ktv-stats {
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: var(--tc-sp-3-5);
	margin: 22px 0;
}
.ktv-stats button {
	background: var(--tc-card);
	border: var(--tc-bw-hair) solid var(--tc-line);
	border-left: var(--tc-bw-alert) solid var(--tc-primary);
	padding: var(--tc-sp-4) var(--tc-sp-5);
	text-align: left;
}
.ktv-stats strong {
	display: block;
	font-size: var(--tc-fs-4xl);
}
.ktv-stats span {
	display: block;
	margin-top: var(--tc-sp-1);
}
.ktv-card {
	background: var(--tc-card);
	border: var(--tc-bw-hair) solid var(--tc-line);
	border-radius: var(--tc-r-xl);
	padding: var(--tc-sp-5);
	margin: var(--tc-sp-4) 0;
}
.ktv-card h2 {
	font-size: var(--tc-fs-xl);
	color: var(--tc-primary);
	margin: 0 0 var(--tc-sp-4-5);
}
.ktv-card h2 small {
	display: inline-block;
	margin-left: var(--tc-sp-3);
}
.ktv-scan {
	display: flex;
	gap: var(--tc-sp-3);
	border: var(--tc-bw-thick) dashed var(--tc-primary);
	padding: var(--tc-sp-3-5);
	background: var(--tc-bg);
	border-radius: var(--tc-r-xl);
}
.ktv-scan input {
	font-size: var(--tc-fs-3xl);
	min-width: 0;
	flex: 1;
	padding: var(--tc-sp-4-5);
}
.ktv-main input:not([type="checkbox"]),
.ktv-main select,
.ktv-main textarea {
	border: var(--tc-bw-hair) solid var(--tc-line);
	border-radius: var(--tc-r-md);
	padding: var(--tc-sp-3);
	background: var(--tc-card);
	color: inherit;
}
.ktv-main button,
.ktv-sidebar button {
	border: var(--tc-bw-hair) solid var(--tc-primary);
	border-radius: var(--tc-r-md);
	padding: var(--tc-sp-3) var(--tc-sp-4-5);
	color: var(--tc-primary);
}
.ktv-main button.primary {
	background: var(--tc-primary);
	color: var(--tc-on-primary);
	min-width: var(--tc-scan-btn-min);
}
.ktv-main label {
	display: block;
	margin: var(--tc-sp-3-5) 0;
}
.ktv-main label select,
.ktv-main textarea {
	display: block;
	width: 100%;
	margin-top: var(--tc-sp-2);
}
.ktv-inline,
.ktv-access form {
	display: flex;
	gap: var(--tc-sp-2-5);
	flex-wrap: wrap;
}
.ktv-access p,
.ktv-muted {
	font-size: var(--tc-fs-md);
	color: var(--tc-text-muted);
}
.ktv-set-summary {
	display: flex;
	gap: var(--tc-sp-6);
	flex-wrap: wrap;
}
.ktv-chips > * {
	padding: var(--tc-sp-1-5) var(--tc-sp-3);
	border: var(--tc-bw-hair) solid var(--tc-line);
	border-radius: var(--tc-r-full);
}
.ktv-bom-layout {
	display: grid;
	grid-template-columns: minmax(160px, 30%) minmax(0, 1fr);
	gap: var(--tc-sp-6);
}
.ktv-tray {
	background: var(--tc-bg);
	display: grid;
	place-items: center;
	padding: var(--tc-sp-4);
	text-align: center;
	min-height: 180px;
}
.ktv-tray img {
	max-width: 100%;
	max-height: var(--tc-tray-max);
	object-fit: contain;
}
.ktv-table-scroll {
	overflow: auto;
}
.ktv-main table {
	width: 100%;
	border-collapse: collapse;
}
.ktv-main th {
	background: var(--tc-primary);
	color: var(--tc-on-primary);
	text-align: left;
	padding: var(--tc-sp-3-5);
}
.ktv-main td {
	padding: var(--tc-sp-3-5);
	border-bottom: var(--tc-bw-hair) solid var(--tc-line);
}
.ktv-main td small {
	display: block;
	margin-top: var(--tc-sp-1);
}
.ktv-main input[type="checkbox"] {
	width: var(--tc-checkbox);
	height: var(--tc-checkbox);
	accent-color: var(--tc-primary);
}
.ktv-thumb {
	width: var(--tc-photo-sm-w);
	height: var(--tc-photo-sm-h);
	object-fit: contain;
	float: left;
	margin-right: var(--tc-sp-3);
}
.ktv-error,
.ktv-warning,
.ktv-notice {
	padding: var(--tc-sp-4);
	border-left: var(--tc-bw-alert) solid var(--tc-warn);
	background: var(--tc-card);
	margin: var(--tc-sp-4) 0;
}
.ktv-error {
	border-left-color: var(--tc-fail);
}
.ktv-card > a {
	margin-left: var(--tc-sp-5);
}
@media (max-width: 900px) {
	.ktv-shell {
		grid-template-columns: 220px minmax(0, 1fr);
	}
	.ktv-main {
		padding: var(--tc-sp-5);
	}
	.ktv-bom-layout {
		grid-template-columns: 1fr;
	}
	.ktv-stats {
		gap: var(--tc-sp-2);
	}
	.ktv-stats button {
		padding: var(--tc-sp-3);
	}
	.ktv-access form > * {
		width: 100%;
	}
}
@media (max-width: 600px) {
	.ktv-shell {
		display: block;
	}
	.ktv-sidebar {
		position: static;
		height: auto;
	}
	.ktv-sidebar nav {
		display: flex;
		overflow: auto;
		padding: 0;
	}
	.ktv-sidebar nav a {
		white-space: nowrap;
		padding: var(--tc-sp-3-5);
	}
	.ktv-identity {
		padding: var(--tc-sp-3-5);
	}
	.ktv-sidebar footer {
		display: flex;
		gap: var(--tc-sp-3);
		align-items: center;
		padding: var(--tc-sp-2-5);
	}
	.ktv-main {
		padding: var(--tc-sp-4);
	}
	.ktv-main h1 {
		font-size: var(--tc-fs-3xl);
	}
	.ktv-stats {
		grid-template-columns: 1fr;
	}
	.ktv-scan {
		flex-direction: column;
	}
	.ktv-main input:not([type="checkbox"]) {
		max-width: 100%;
	}
}
</style>
