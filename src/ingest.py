"""Lấy dữ liệu từ vnstock 4.0.x (API mới `vnstock.api.*`).

Tất cả lời gọi vnstock được gói ở đây để khi thư viện đổi API, bạn chỉ
sửa 1 file. Mọi hàm đều bọc try/except và trả về giá trị an toàn để job
không vỡ khi một mã hay một nguồn lỗi.
"""
from datetime import date, timedelta
import os as _os
import threading
import time
import pandas as pd

# Guest tier: 20 req/phút → cần ≥3s giữa các call.
# Community (API key): 60 req/phút → ~1,05s.
# Đặt VNSTOCK_MIN_INTERVAL=1.05 khi có key Community để nạp lại nhanh hơn 3 lần.
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


def apply_vnstock_timeout() -> None:
    """Đặt thời gian chờ MẶC ĐỊNH của vnstock.core.utils.client.send_request.

    vnstock 4.0.9 gọi send_request mà không truyền timeout (vd Company.events),
    nên mặc định 30 giây của hàm là con số thật; biến VNSTOCK_TIMEOUT của
    vnstock KHÔNG đi tới đường gọi này. Khi iq.vietcap.com.vn bóp lưu lượng, lần
    thử đầu treo đủ thời gian chờ rồi vnstock thử lại tới 9 lần → ~5 phút/mã
    (đo 04/10/2026). Mặc định 15 giây (VNSTOCK_REQUEST_TIMEOUT); lệnh bình
    thường đo được 0,1–7 giây.

    Sửa __defaults__ của CHÍNH đối tượng hàm nên mọi module đã `from ... import
    send_request` đều nhận. Phụ thuộc chi tiết nội bộ của vnstock — test
    tests/test_vnstock_timeout.py sẽ đỏ nếu bản nâng cấp đổi chữ ký hàm."""
    import inspect
    from vnstock.core.utils import client
    fn = client.send_request
    names = [n for n, prm in inspect.signature(fn).parameters.items()
             if prm.default is not inspect.Parameter.empty]
    if "timeout" not in names or fn.__defaults__ is None:
        print("[ingest] vnstock.send_request không còn tham số timeout — bỏ qua chỉnh thời gian chờ.")
        return
    defaults = list(fn.__defaults__)
    defaults[names.index("timeout")] = int(float(_os.getenv("VNSTOCK_REQUEST_TIMEOUT", "15")))
    fn.__defaults__ = tuple(defaults)

from vnstock.api.quote import Quote
from vnstock.api.financial import Finance
from vnstock.api.company import Company
from vnstock.api.listing import Listing
from vnstock.api.trading import Trading
from . import warehouse


def fetch_history(symbol: str, source: str = "VCI", days: int = 120) -> pd.DataFrame:
    """OHLCV ngày trong `days` phiên gần nhất. Đọc warehouse trước, gọi API nếu thiếu."""
    # 1) Thử warehouse
    try:
        con = warehouse.get_conn()
        df = warehouse.read_price_history(con, symbol, days)
        con.close()
        if len(df) >= max(days // 2, 10):
            return df
    except Exception:
        pass

    # 2) Fallback: gọi API
    start = (date.today() - timedelta(days=days * 2)).isoformat()
    end = date.today().isoformat()
    _throttle()
    try:
        df = Quote(symbol=symbol, source=source).history(
            start=start, end=end, interval="1D"
        )
        if df is None or df.empty:
            return pd.DataFrame()
        df.columns = [str(c).lower() for c in df.columns]
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        print(f"[history] {symbol}: {e}")
        return pd.DataFrame()


def fetch_index(symbol: str = "VNINDEX", source: str = "VCI", days: int = 30) -> dict:
    """Tóm tắt chỉ số thị trường: đóng cửa + %thay đổi phiên + xu hướng 5 phiên."""
    df = fetch_history(symbol, source, days=days)
    if df.empty or "close" not in df.columns:
        return {}
    close = df["close"].astype(float)
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last
    wk = float(close.iloc[-6]) if len(close) > 5 else None
    return {
        "index": symbol,
        "close": round(last, 2),
        "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
        "change_5d_pct": round((last / wk - 1) * 100, 2) if wk else None,
    }


def fetch_ratios(symbol: str, source: str = "VCI") -> dict:
    """P/E, P/B, ROE mới nhất. Trả {} nếu không lấy được."""
    _throttle()
    try:
        df = Finance(symbol=symbol, source=source, period="year").ratio()
        if df is None or len(df) == 0:
            return {}
        # vnstock trả về MultiIndex/cột tên khác nhau theo nguồn -> dò mềm.
        flat = {}
        row = df.iloc[0] if hasattr(df, "iloc") else df
        for col in (df.columns if hasattr(df, "columns") else []):
            name = " ".join([str(x) for x in col]).lower() if isinstance(col, tuple) else str(col).lower()
            val = row[col]
            if "p/e" in name or name.strip() == "pe":
                flat["pe"] = _num(val)
            elif "p/b" in name or name.strip() == "pb":
                flat["pb"] = _num(val)
            elif "roe" in name:
                flat["roe"] = _num(val)
        return flat
    except Exception as e:
        print(f"[ratios] {symbol}: {e}")
        return {}


def fetch_industry(symbol: str, source: str = "VCI") -> str:
    """Tên ngành của doanh nghiệp (nhãn dán cho bản tin)."""
    _throttle()
    try:
        df = Company(symbol=symbol, source=source).overview()
        if df is None or df.empty:
            return ""
        df.columns = [str(c).lower() for c in df.columns]
        for c in df.columns:
            if "industry" in c or "ngành" in c or "icb_name" in c or "sector" in c:
                v = df.iloc[0][c]
                if v and str(v).lower() != "nan":
                    return str(v)
        return ""
    except Exception as e:
        print(f"[industry] {symbol}: {e}")
        return ""


def fetch_news(symbol: str, source: str = "VCI", limit: int = 5) -> list[dict]:
    """Tin doanh nghiệp gần nhất (API hợp lệ, không scrape)."""
    _throttle()
    try:
        df = Company(symbol=symbol, source=source).news()
        if df is None or df.empty:
            return []
        df.columns = [str(c).lower() for c in df.columns]
        title_col = next((c for c in df.columns if "title" in c or "tiêu" in c), df.columns[0])
        out = []
        for _, r in df.head(limit).iterrows():
            out.append({
                "symbol": symbol,
                "id": str(r.get("id", r.get(title_col, ""))),
                "title": str(r.get(title_col, "")).strip(),
            })
        return out
    except Exception as e:
        print(f"[news] {symbol}: {e}")
        return []


def fetch_universe(group: str = "VN30", source: str = "VCI") -> list[str]:
    """Danh sách mã trong nhóm chỉ số để chạy screener."""
    _throttle()
    try:
        df = Listing(source=source).symbols_by_group(group)
        if df is None:
            return []
        if hasattr(df, "tolist"):
            return [str(s) for s in df.tolist()]
        col = df.columns[0]
        return [str(s) for s in df[col].tolist()]
    except Exception as e:
        print(f"[universe] {group}: {e}")
        return []


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


apply_vnstock_timeout()
