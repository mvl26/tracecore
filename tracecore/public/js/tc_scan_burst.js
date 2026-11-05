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
