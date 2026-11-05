// A-126 (FEAT-089): nhận diện luồng quét để ô quét tự gửi khi máy quét gõ xong mã, không cần bấm Quét.
// Máy quét tại viện không gửi phím Enter. Ký tự máy quét đến dồn dập (cách nhau vài ms); gõ tay chậm hơn nhiều.
// Đủ MIN_CHARS ký tự liên tiếp cách nhau <= FAST_MS (hoặc một lần nhập thêm >= MIN_CHARS ký tự), rồi im lặng IDLE_MS
// thì gọi onComplete một lần. Xóa ký tự hoặc gõ chậm thì bỏ. Đồng hồ và hẹn giờ truyền vào được để test.

const TC_SCAN_FAST_MS = 50;
const TC_SCAN_IDLE_MS = 120;
const TC_SCAN_MIN_CHARS = 4;

class TcScanBurst {
	constructor(onComplete, options = {}) {
		this.onComplete = onComplete;
		this.now = options.now || (() => performance.now());
		this.schedule = options.schedule || ((fn, ms) => setTimeout(fn, ms));
		this.cancel = options.cancel || ((id) => clearTimeout(id));
		this.timer = null;
		this.reset();
	}

	reset() {
		this.cancel(this.timer);
		this.timer = null;
		this.fast = 0; // số ký tự liên tiếp đến theo tốc độ máy quét
		this.lastAt = null;
		this.lastLength = 0;
	}

	input(value) {
		const at = this.now();
		const length = (value || "").length;
		const added = length - this.lastLength;
		this.cancel(this.timer);
		this.timer = null;
		if (added <= 0) {
			// xóa hoặc ô bị xóa trắng (đã gửi): bắt đầu lại
			this.fast = 0;
			this.lastAt = at;
			this.lastLength = length;
			return;
		}
		if (added >= TC_SCAN_MIN_CHARS) this.fast = TC_SCAN_MIN_CHARS;
		else if (this.lastAt !== null && at - this.lastAt <= TC_SCAN_FAST_MS) this.fast += added;
		else this.fast = added;
		this.lastAt = at;
		this.lastLength = length;
		if (this.fast < TC_SCAN_MIN_CHARS) return;
		this.timer = this.schedule(() => {
			this.timer = null;
			this.reset();
			this.onComplete();
		}, TC_SCAN_IDLE_MS);
	}
}

// A-128 (FEAT-091): mã QR của mọi nút ở màn trạm. `CMD-BTN-<data-action viết hoa>`; nút cùng loại thứ n (n >= 2, theo
// thứ tự hiện trên màn) thêm `.<n>`. Nút đã có mã lệnh A-119 (`CMD-DO-…`) không dùng dạng này.
const TC_BUTTON_PREFIX = "CMD-BTN-";
const TC_BUTTON_CODE = /^CMD-BTN-([A-Z0-9][A-Z0-9_-]{0,47})(?:\.([1-9][0-9]?))?$/;

function tcButtonCode(action, index = 1) {
	const base = `${TC_BUTTON_PREFIX}${String(action || "").toUpperCase()}`;
	return index > 1 ? `${base}.${index}` : base;
}

function tcParseButtonCode(raw) {
	const match = TC_BUTTON_CODE.exec(
		String(raw || "")
			.trim()
			.toUpperCase()
	);
	return match
		? { action: match[1].toLowerCase(), index: match[2] ? Number(match[2]) : 1 }
		: null;
}

// A-128: gom phím tốc độ máy quét ở BẤT KỲ ô nào (kể cả ô số không nhận chữ), để mã lệnh quét lúc con trỏ đang ở ô số
// lượng / ghi chú vẫn chạy được. `key(k, target)` trả true khi phím thuộc luồng quét đang mở mà là Enter (để chặn mặc
// định). Hết IDLE_MS hoặc gặp Enter thì gọi onComplete(text, target lúc bắt đầu luồng) nếu đủ MIN_CHARS ký tự nhanh.
class TcKeyBurst {
	constructor(onComplete, options = {}) {
		this.onComplete = onComplete;
		this.now = options.now || (() => performance.now());
		this.schedule = options.schedule || ((fn, ms) => setTimeout(fn, ms));
		this.cancel = options.cancel || ((id) => clearTimeout(id));
		this.timer = null;
		this.reset();
	}

	reset() {
		this.cancel(this.timer);
		this.timer = null;
		this.text = "";
		this.fast = 0;
		this.lastAt = null;
		this.start = null;
	}

	finish() {
		const text = this.text;
		const start = this.start;
		const ok = this.fast >= TC_SCAN_MIN_CHARS;
		this.reset();
		if (ok) this.onComplete(text, start);
		return ok;
	}

	key(key, target) {
		const at = this.now();
		const quick = this.lastAt !== null && at - this.lastAt <= TC_SCAN_FAST_MS;
		if (key === "Enter")
			return quick && this.fast >= TC_SCAN_MIN_CHARS ? this.finish() : false;
		if (typeof key !== "string" || key.length !== 1) return false;
		this.cancel(this.timer);
		if (quick) {
			this.text += key;
			this.fast += 1;
		} else {
			this.text = key;
			this.fast = 1;
			this.start = target;
		}
		this.lastAt = at;
		this.timer = this.schedule(() => {
			this.timer = null;
			this.finish();
		}, TC_SCAN_IDLE_MS);
		return false;
	}
}
