<script setup lang="ts">
import { onMounted, ref } from "vue";
import { request, createBusinessMutation } from "./api";
import { useDialog } from "./useDialog";
const props = defineProps<{ name?: string }>(),
	emit = defineEmits<{ close: []; saved: [] }>();
const ctx = ref<any>(null),
	history = ref<any[]>([]),
	cursor = ref<string | null>(null),
	busy = ref(false),
	error = ref(""),
	notice = ref(""),
	preview = ref("");
const type = ref(""),
	count = ref(1),
	department = ref(""),
	maxCycles = ref<number | undefined>(),
	kind = ref("tag"),
	printer = ref(""),
	reason = ref(""),
	scan = ref("");
const issued = ref<string[]>([]);
const dialogRoot = ref<HTMLElement | null>(null);
useDialog(dialogRoot);
const labels: Record<string, string> = {
	set_id: "Set ID",
	set_type: "Loại bộ",
	set_type_name: "Tên loại bộ",
	department: "Khoa",
	status: "Trạng thái",
	cycles_used: "Chu trình đã dùng",
	max_cycles: "Cơ số tối đa",
	remaining: "Chu trình còn lại",
	cycles_source: "Nguồn bộ đếm",
	active_cycle_id: "Cycle ID hiện tại",
	current_station: "Trạm hiện tại",
	cycle_bom_version: "Phiên bản BOM ghim",
	bom_version_applied: "Phiên bản BOM áp dụng",
	bom_pinned: "Đã ghim BOM",
	tag_verified_on: "Thời điểm xác minh thẻ",
	tag_verified_by: "Người xác minh",
	code_status: "Trạng thái mã",
	print_counts: "Số lần in",
};
const mutate = createBusinessMutation();
async function load() {
	busy.value = true;
	try {
		ctx.value = await request("tracecore.v1.set_unit.form_context", {
			...(props.name ? { set_unit: props.name } : {}),
			...(type.value ? { set_type: type.value } : {}),
		});
		if (props.name) await moreHistory();
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
const historyBusy = ref(false);
async function moreHistory() {
	if (historyBusy.value) return;
	historyBusy.value = true;
	try {
		const data = await request("tracecore.v1.set_unit.history", {
			set_unit: props.name,
			...(cursor.value ? { before: cursor.value } : {}),
		});
		history.value.push(...data.events);
		cursor.value = data.next_before;
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		historyBusy.value = false;
	}
}
async function issue() {
	busy.value = true;
	error.value = "";
	try {
		const result = await mutate("tracecore.v1.set_unit.create_batch", {
			set_type: type.value,
			count: count.value,
			department: department.value || null,
			max_cycles: maxCycles.value,
		});
		if (!result.ok)
			throw new Error("Không cấp được Set ID. Kiểm tra loại bộ, cơ số và cấu hình GS1.");
		issued.value = result.set_ids;
		notice.value = "Đã cấp " + result.set_ids.length + " Set ID.";
		emit("saved");
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function showPreview() {
	busy.value = true;
	error.value = "";
	try {
		const data = await request("tracecore.v1.set_unit.tag_preview", {
			set_unit: props.name,
			kind: kind.value,
		});
		preview.value = data.png_b64 ? "data:image/png;base64," + data.png_b64 : "";
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function printTag() {
	if (!window.confirm("Gửi yêu cầu in lại thẻ/nhãn cho bộ này?")) return;
	busy.value = true;
	error.value = "";
	try {
		const data = await mutate("tracecore.v1.set_unit.reprint_tag", {
			set_unit: props.name,
			kind: kind.value,
			printer: printer.value,
			reason: reason.value,
		});
		if (!data.ok)
			throw new Error("Không gửi được yêu cầu in. Kiểm tra máy in, mẫu nhãn và lý do.");
		notice.value = "Đã gửi yêu cầu in. Kết quả thực tế phụ thuộc worker và máy in.";
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function verify() {
	busy.value = true;
	error.value = "";
	try {
		const data = await mutate("tracecore.v1.set_unit.verify_tag", {
			set_unit: props.name,
			raw: scan.value,
		});
		if (!data.ok) throw new Error("Mã quét không khớp hoặc không hợp lệ.");
		notice.value = "Đã xác minh thẻ.";
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
onMounted(load);
</script>
<template>
	<div class="modal-backdrop">
		<section
			ref="dialogRoot"
			role="dialog"
			aria-modal="true"
			aria-labelledby="unit-title"
			class="detail-modal"
			@keydown.esc="!busy && emit('close')"
		>
			<div class="heading">
				<h2 id="unit-title">{{ name || "Cấp Set ID hàng loạt" }}</h2>
				<button class="secondary" :disabled="busy" @click="emit('close')">Đóng</button>
			</div>
			<p v-if="error" class="alert danger" role="alert">{{ error }}</p>
			<p v-if="notice" class="alert" role="status">{{ notice }}</p>
			<p v-if="busy" role="status">Đang xử lý…</p>
			<template v-if="ctx">
				<form v-if="!name && ctx.permissions?.can_issue" @submit.prevent="issue">
					<div class="form-grid">
						<label>Loại bộ<input v-model="type" required @change="load" /></label
						><label
							>Số bộ (1–{{ ctx.limits?.max_batch || 100 }})<input
								v-model="count"
								type="number"
								min="1"
								:max="ctx.limits?.max_batch || 100"
								required /></label
						><label>Khoa (tùy chọn)<input v-model="department" /></label
						><label
							>Cơ số tối đa (bỏ trống: theo cấu hình)<input
								v-model="maxCycles"
								type="number"
								min="1"
						/></label>
					</div>
					<p class="subtle">
						Cơ số nguồn: {{ ctx.max_cycles_cap?.value || "Chưa xác định" }}. Mã do
						server sinh; không thể sửa hoặc tái cấp.
					</p>
					<button class="primary" :disabled="busy || issued.length > 0">
						Cấp Set ID
					</button>
					<ul v-if="issued.length">
						<li v-for="id in issued" :key="id">
							<code>{{ id }}</code>
						</li>
					</ul>
				</form>
				<template v-if="name"
					><dl>
						<template v-for="(value, field) in ctx.summary" :key="field"
							><dt>{{ labels[String(field)] || field }}</dt>
							<dd>{{ value ?? "—" }}</dd></template
						>
					</dl>
					<section v-if="ctx.permissions?.can_print">
						<h2>Thẻ / nhãn</h2>
						<div class="filters">
							<select v-model="kind" aria-label="Loại nhãn">
								<option value="tag">Thẻ Set ID</option>
								<option value="tray">Nhãn khay</option></select
							><button class="secondary" :disabled="busy" @click="showPreview">
								Xem trước nhãn</button
							><a
								class="secondary"
								:href="
									'/api/method/tracecore.v1.set_unit.batch_csv?set_units=' +
									encodeURIComponent(JSON.stringify([name]))
								"
								>CSV khắc mã</a
							>
						</div>
						<img
							v-if="preview"
							:src="preview"
							alt="Xem trước nhãn Set ID"
							class="label-preview"
						/><label
							>Máy in<select v-model="printer">
								<option value="">Chọn máy in</option>
								<option
									v-for="p in ctx.printers_hint"
									:key="p.name"
									:value="p.name"
								>
									{{ p.printer_name || p.name }}
								</option>
							</select></label
						><label>Lý do in lại<input v-model="reason" maxlength="500" /></label
						><button
							class="primary"
							:disabled="busy || !printer || !reason.trim()"
							@click="printTag"
						>
							Gửi yêu cầu in lại
						</button>
					</section>
					<section v-if="ctx.permissions?.can_verify">
						<h2>Xác minh gắn thẻ</h2>
						<form class="filters" @submit.prevent="verify">
							<input
								v-model="scan"
								placeholder="Quét mã trên thẻ…"
								required
							/><button class="primary" :disabled="busy">Xác minh</button>
						</form>
					</section>
					<h2>Lịch sử vòng đời</h2>
					<div v-for="(event, i) in history" :key="i" class="history-event">
						<b>{{ event.title || event.action || event.kind }}</b>
						<p>{{ event.at }} · {{ event.by || event.user }}</p>
						<p class="subtle">{{ event.detail || event.description }}</p>
					</div>
					<p v-if="!history.length" class="empty">Chưa có lịch sử.</p>
					<button v-if="cursor" class="secondary" :disabled="busy" @click="moreHistory">
						Xem lịch sử cũ hơn
					</button>
				</template></template
			>
		</section>
	</div>
</template>
