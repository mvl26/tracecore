<script setup lang="ts">
import { onMounted, ref } from "vue";
import { adminAPI, request, createBusinessMutation } from "./api";
import { useDialog } from "./useDialog";
const props = defineProps<{ role: string; screen: string; name?: string }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const busy = ref(true),
	error = ref(""),
	message = ref(""),
	values = ref<Record<string, any>>({}),
	modified = ref(""),
	canWrite = ref(false);
const canWriteMethods = ref(false);
const fields = ref<
	{
		name: string;
		label: string;
		type: string;
		options?: string;
		required: boolean;
		readonly: boolean;
	}[]
>([]);
const bom = ref<any>(null),
	versions = ref<any[]>([]),
	version = ref(""),
	reason = ref(""),
	effective = ref(new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Ho_Chi_Minh" }));
const methodNames = ["Steam 121", "Steam 134", "Plasma", "EO"];
const dialogRoot = ref<HTMLElement | null>(null);
useDialog(dialogRoot);
const mutate = createBusinessMutation();
async function load() {
	busy.value = true;
	error.value = "";
	try {
		const data = await adminAPI("master_form", {
			role: props.role,
			screen: props.screen,
			name: props.name,
		});
		values.value = data.values;
		fields.value = data.fields;
		modified.value = data.modified;
		canWrite.value = data.can_write;
		canWriteMethods.value = data.can_write_methods;
		if (props.screen === "set-types" && props.name) {
			const data = await request("tracecore.v1.set_type.versions", { set_type: props.name });
			versions.value = data.versions;
			await loadBOM();
		} else if (props.screen === "set-types")
			bom.value = { lines: [{ instrument: "", qty: 1 }] };
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function loadBOM() {
	try {
		bom.value = await request("tracecore.v1.set_type.bom", {
			set_type: props.name,
			...(version.value ? { version: version.value } : {}),
		});
	} catch (e) {
		error.value = (e as Error).message;
	}
}
async function save() {
	busy.value = true;
	error.value = "";
	try {
		if (props.screen === "set-types" && !props.name) {
			const result = await mutate("tracecore.v1.set_type_admin.create", {
				header: values.value,
				lines: bom.value.lines.map((x: any, i: number) => ({
					instrument: x.instrument,
					qty: Number(x.qty),
					position: i + 1,
				})),
			});
			if (!result.ok) throw new Error("Không tạo được loại bộ. Kiểm tra dữ liệu và BOM.");
			emit("saved");
			emit("close");
			return;
		}
		await adminAPI(
			"save_master",
			{
				role: props.role,
				screen: props.screen,
				name: props.name,
				modified: modified.value,
				values: values.value,
			},
			true
		);
		message.value = "Đã lưu danh mục.";
		emit("saved");
		if (!props.name) {
			emit("close");
			return;
		}
		await load();
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
async function saveBOM() {
	busy.value = true;
	error.value = "";
	try {
		const result = await mutate("tracecore.v1.set_type_admin.save_bom", {
			set_type: props.name,
			lines: bom.value.lines.map((x: any, i: number) => ({
				instrument: x.instrument,
				qty: Number(x.qty),
				position: i + 1,
			})),
			effective_from: effective.value,
			reason: reason.value,
			base_version: Math.max(
				0,
				...versions.value.map((x) => Number(x.bom_version || x.version))
			),
		});
		if (!result.ok)
			throw new Error("Không thể lưu BOM. Kiểm tra ngày hiệu lực, thành phần và lý do.");
		message.value = "Đã tạo phiên bản BOM mới.";
		reason.value = "";
		await load();
		emit("saved");
	} catch (e) {
		error.value = (e as Error).message;
	} finally {
		busy.value = false;
	}
}
function close() {
	if (canWrite.value && !window.confirm("Đóng hồ sơ? Các chỉnh sửa chưa lưu sẽ bị bỏ.")) return;
	emit("close");
}
onMounted(load);
</script>
<template>
	<div class="modal-backdrop">
		<section
			ref="dialogRoot"
			class="detail-modal"
			role="dialog"
			aria-modal="true"
			aria-labelledby="master-title"
			@keydown.esc="!busy && close()"
		>
			<div class="heading">
				<h2 id="master-title">
					{{
						name ||
						(screen === "instruments" ? "Thêm dụng cụ" : "Thêm loại bộ cùng BOM v1")
					}}
				</h2>
				<button class="secondary" :disabled="busy" @click="close">Đóng</button>
			</div>
			<p v-if="error" class="alert danger" role="alert">{{ error }}</p>
			<p v-if="message" class="alert" role="status">{{ message }}</p>
			<p v-if="busy" role="status">Đang xử lý…</p>
			<form v-if="fields.length" @submit.prevent="save">
				<div class="form-grid">
					<label v-for="field in fields" :key="field.name"
						>{{ field.label }}{{ field.required ? " *" : "" }}
						<select
							v-if="field.type === 'Select'"
							v-model="values[field.name]"
							:disabled="!canWrite || busy || field.readonly"
						>
							<option
								v-for="option in (field.options || '').split('\n')"
								:key="option"
								:value="option"
							>
								{{ option || "—" }}
							</option>
						</select>
						<input
							v-else-if="field.type === 'Check'"
							v-model="values[field.name]"
							type="checkbox"
							:disabled="!canWrite || busy"
						/>
						<input
							v-else
							v-model="values[field.name]"
							:type="
								['Int', 'Float', 'Currency'].includes(field.type)
									? 'number'
									: 'text'
							"
							:step="field.type === 'Int' ? 1 : 'any'"
							:required="field.required"
							:disabled="!canWrite || busy || field.readonly"
							maxlength="140"
						/>
					</label>
				</div>
				<fieldset
					v-if="screen === 'instruments' && values.compatible_methods"
					:disabled="!canWrite || busy || !canWriteMethods"
				>
					<legend>Phương pháp tương thích</legend>
					<label v-for="method in methodNames" :key="method" class="method-check"
						><input
							v-model="values.compatible_methods"
							type="checkbox"
							:value="method"
						/>
						{{ method }}</label
					>
				</fieldset>
				<div class="actions">
					<span class="subtle">{{
						canWrite
							? "Server kiểm tra quy tắc và ghi audit khi lưu."
							: "Tài khoản chỉ có quyền đọc."
					}}</span
					><button v-if="canWrite" class="primary" :disabled="busy">Lưu danh mục</button>
				</div>
			</form>
			<section v-if="bom" class="bom-section">
				<h2>BOM · Phiên bản {{ bom.bom_version || 1 }}</h2>
				<div v-if="name" class="filters">
					<select v-model="version" aria-label="Phiên bản BOM" @change="loadBOM">
						<option value="">Đang hiệu lực</option>
						<option
							v-for="v in versions"
							:key="v.bom_version || v.version"
							:value="v.bom_version || v.version"
						>
							V{{ v.bom_version || v.version }} · {{ v.effective_from }}
						</option></select
					><a
						class="secondary"
						:href="
							'/api/method/tracecore.v1.set_type.count_sheet?set_type=' +
							encodeURIComponent(name || '') +
							(version ? '&version=' + version : '')
						"
						target="_blank"
						rel="noopener"
						>Phiếu kiểm đếm PDF</a
					>
				</div>
				<div class="table-scroll">
					<table>
						<thead>
							<tr>
								<th>Vị trí</th>
								<th>Dụng cụ</th>
								<th>Số lượng</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(line, i) in bom.lines" :key="i">
								<td>{{ Number(i) + 1 }}</td>
								<td>
									<input
										v-model="line.instrument"
										:disabled="!canWrite || busy"
										aria-label="Mã dụng cụ"
									/>
								</td>
								<td>
									<input
										v-model="line.qty"
										type="number"
										min="1"
										max="999"
										:disabled="!canWrite || busy"
										aria-label="Số lượng"
									/>
								</td>
								<td>
									<button
										v-if="canWrite"
										class="secondary"
										:disabled="busy"
										@click="bom.lines.splice(i, 1)"
									>
										Bỏ
									</button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<template v-if="canWrite"
					><button
						class="secondary"
						:disabled="busy"
						@click="bom.lines.push({ instrument: '', qty: 1 })"
					>
						Thêm thành phần</button
					><template v-if="name"
						><label>Ngày hiệu lực<input v-model="effective" type="date" /></label
						><label
							>Lý do phiên bản mới<input v-model="reason" maxlength="500" /></label
						><button
							class="primary"
							:disabled="busy || !reason.trim()"
							@click="saveBOM"
						>
							Tạo phiên bản BOM mới
						</button>
						<p class="subtle">
							Các phiên bản đã có được giữ nguyên. Mọi thay đổi tạo phiên bản mới.
						</p></template
					></template
				>
			</section>
		</section>
	</div>
</template>
