"""Nhịp giãn cách gọi nguồn dùng chung (_throttle) và cầu chì nguồn (SourceBreaker).

Các hàm lấy dữ liệu nằm ở src/ingest_market.py (gọi src/sources). Các hàm
fetch_* cũ của module này (gọi vnstock, phục vụ main.py) đã gỡ cùng vnstock
(11/2026).
"""
import os as _os
import threading
import time

# Giãn cách tối thiểu giữa hai lần gọi nguồn (giây). Mặc định 3,1s là hạn mức
# cũ của vnstock gói khách (20 lệnh/phút); workflow đặt 1,05 (job ngày/tuần/
# tháng) và 5 (trickle). Tên biến giữ nguyên VNSTOCK_MIN_INTERVAL dù đã bỏ
# vnstock (11/2026) để không phải đổi secret/env trong các workflow. Nguồn
# iq.vietcap.com.vn bóp lưu lượng sau vài nghìn lệnh/ngày (04/10/2026).
_MIN_CALL_INTERVAL = float(_os.getenv("VNSTOCK_MIN_INTERVAL", "3.1"))

# An toàn đa luồng (BCTC song song, 04/10/2026): mỗi lần gọi GIỮ CHỖ một khe
# thời gian dưới khoá rồi mới ngủ ngoài khoá. Tổng tốc độ của mọi luồng cộng
# lại vẫn ≤ 1 lần / _MIN_CALL_INTERVAL — tức vẫn dưới hạn mức 60 lần/phút của
# khoá API dù chạy nhiều luồng. Bản cũ dùng một biến toàn cục không khoá: hai
# luồng đọc cùng giá trị sẽ gọi cùng lúc và vượt hạn mức.
_lock = threading.Lock()
_next_slot: float = 0.0


def _throttle() -> None:
    """Chờ tới khe gọi kế tiếp của nhịp giãn cách chung (an toàn đa luồng)."""
    global _next_slot
    with _lock:
        now = time.monotonic()
        start = max(now, _next_slot)
        _next_slot = start + _MIN_CALL_INTERVAL
    wait = start - time.monotonic()
    if wait > 0:
        time.sleep(wait)


class SourceBreaker:
    """Ngắt mạch cho vòng lặp gọi API theo từng mã.

    - `before()` gọi trước mỗi mã: False nếu đã quá `deadline` (time.monotonic)
      hoặc đã dừng → vòng lặp phải `break`.
    - `record(ok)` gọi sau mỗi mã: `pause_after` mã lỗi LIÊN TIẾP → ngủ
      `pause_seconds`; quá `max_pauses` lần nghỉ mà vẫn lỗi liên tiếp → dừng
      ("nguon_treo"). Một mã thành công đặt lại bộ đếm.

    Lý do (04/10/2026): từ máy chủ GitHub (Azure), iq.vietcap.com.vn hết thời
    gian chờ liên tục — mỗi mã tốn ~5 phút do vnstock tự thử lại 9 lần x 30
    giây; 51 phút đi được ~120/1.603 mã, GitHub cắt job trước khi dbt chạy.
    Cùng lúc, gọi từ máy ở VN trả lời 0,1–1,3 giây — nguồn chặn theo IP.
    Mặc định: SOURCE_PAUSE_AFTER=3, SOURCE_PAUSE_SECONDS=180, SOURCE_MAX_PAUSES=2
    → nguồn chặn hẳn thì mất tối đa ~50 phút rồi bỏ giai đoạn, thay vì hàng giờ.
    """

    def __init__(self, name: str, deadline: float | None = None,
                 pause_after: int | None = None, pause_seconds: float | None = None,
                 max_pauses: int | None = None, max_symbols: int | None = None):
        self.name = name
        self.deadline = deadline
        # Hạn mức mã mỗi lần chạy (nạp rải, 05/10/2026): nguồn chỉ chịu ~100–150
        # lệnh mỗi đợt nên mỗi lần chạy chỉ gọi một ít. Đủ hạn mức = dừng BÌNH
        # THƯỜNG ("du_han_muc"), không phải sự cố.
        self.max_symbols = max_symbols
        self.fetched: list[str] = []
        self.pause_after = pause_after if pause_after is not None else int(_os.getenv("SOURCE_PAUSE_AFTER", "3"))
        self.pause_seconds = pause_seconds if pause_seconds is not None else float(_os.getenv("SOURCE_PAUSE_SECONDS", "180"))
        self.max_pauses = max_pauses if max_pauses is not None else int(_os.getenv("SOURCE_MAX_PAUSES", "2"))
        self.consecutive = self.pauses = self.n_errors = self.n_done = 0
        self.stopped, self.reason = False, None

    def before(self) -> bool:
        if self.stopped:
            return False
        if self.max_symbols is not None and self.n_done >= self.max_symbols:
            self.stopped, self.reason = True, "du_han_muc"
            print(f"[{self.name}] đủ hạn mức {self.max_symbols} mã cho lần chạy này.", flush=True)
            return False
        if self.deadline is not None and time.monotonic() > self.deadline:
            self.stopped, self.reason = True, "het_ngan_sach"
            print(f"[{self.name}] hết ngân sách sau {self.n_done} mã — dừng.", flush=True)
            return False
        return True

    def record(self, ok: bool, symbol: str | None = None) -> None:
        self.n_done += 1
        if ok:
            self.consecutive = 0
            if symbol is not None:
                self.fetched.append(symbol)
            return
        self.n_errors += 1
        self.consecutive += 1
        if self.consecutive < self.pause_after:
            return
        if self.pauses >= self.max_pauses:
            self.stopped, self.reason = True, "nguon_treo"
            print(f"[{self.name}] {self.consecutive} mã lỗi liên tiếp sau {self.pauses} lần nghỉ"
                  f" — nguồn treo/chặn, dừng giai đoạn sau {self.n_done} mã.", flush=True)
            return
        print(f"[{self.name}] {self.consecutive} mã lỗi liên tiếp — nghỉ "
              f"{self.pause_seconds:.0f} giây.", flush=True)
        time.sleep(self.pause_seconds)
        self.pauses += 1
        self.consecutive = 0

    def notes(self) -> str:
        """Tóm tắt một dòng cho etl_load_log.notes."""
        s = f"{self.n_done} ma, {self.n_errors} loi, {self.pauses} lan nghi"
        if self.stopped:
            s += f"; dung som: {self.reason}"
        return s
