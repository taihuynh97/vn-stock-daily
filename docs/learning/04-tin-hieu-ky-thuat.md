# 04 — Tín hiệu kỹ thuật & Screener

## Files liên quan
- `src/signals.py` — tính RSI, MA, vol_ratio (pure functions)
- `src/screener.py` — lọc cổ phiếu tiềm năng theo value + momentum
- `config/screener.yml` — tiêu chí lọc (bạn có thể tùy chỉnh)

---

## Pure Functions là gì?

`signals.py` được thiết kế là **pure functions**: nhận input → trả output, không có side effect.

```python
def analyze(df: pd.DataFrame) -> dict:
    # Không gọi API
    # Không đọc/ghi file
    # Không có global state
    # Cùng input → luôn cùng output
    ...
    return {rsi, ma20, ma50, ...}
```

**Tại sao quan trọng?**
- Dễ test: không cần mock gì.
- Dễ reuse: `screener.py` và `main.py` đều gọi cùng `signals.analyze()`.
- Dễ parallelize: không có shared state.

---

## Moving Average (MA) — Đường trung bình động

```python
ma20 = close.rolling(20).mean()  # trung bình 20 phiên gần nhất
ma50 = close.rolling(50).mean()  # trung bình 50 phiên gần nhất
```

**Ý nghĩa:**
- MA20: xu hướng ngắn hạn (~1 tháng giao dịch)
- MA50: xu hướng trung hạn (~2.5 tháng)

**Tại sao cần `days=120` thay vì 50?**
Để tính MA50 đáng tin cậy cho hôm nay, bạn cần ít nhất 50 phiên. Nếu chỉ lấy 50 phiên → MA50 chỉ có 1 điểm, không ý nghĩa. `days=120` để có thêm "history" trước điểm MA50 đầu tiên.

**Cách dùng MA trong screener:**
```yaml
# config/screener.yml
momentum:
  above_ma50: true  # giá > MA50 = tín hiệu đà tăng
```

```python
# src/screener.py
if cfg.get("above_ma50") and close and ma50 and close > ma50:
    hits += 1; reasons.append("giá>MA50")
```

---

## RSI (Relative Strength Index) — Chỉ số sức mạnh tương đối

RSI đo **tốc độ và biên độ** của thay đổi giá, từ 0–100.

```python
def rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()                           # thay đổi giá
    gain = delta.clip(lower=0).rolling(period).mean()   # trung bình ngày tăng
    loss = (-delta.clip(upper=0)).rolling(period).mean() # trung bình ngày giảm
    rs = gain / loss.replace(0, pd.NA)
    out = 100 - 100 / (1 + rs)
    ...
```

**Công thức:**
```
RSI = 100 - (100 / (1 + RS))
RS = Average Gain / Average Loss (trong 14 phiên)
```

**Giải thích intuitive:**
- RSI = 70+: Cổ phiếu đã tăng mạnh liên tục → có thể "quá mua" (overbought), nguy cơ điều chỉnh.
- RSI = 30-: Cổ phiếu giảm liên tục → có thể "quá bán" (oversold), tiềm năng hồi phục.
- RSI = 50-70: Vùng tăng khỏe, chưa quá mua → screener dùng `rsi_min: 50, rsi_max: 70`.

**Tại sao period=14?**
Wilder (người phát minh RSI, 1978) chọn 14 như một heuristic. Ngắn hơn (7) → nhạy hơn nhưng nhiều tín hiệu giả. Dài hơn (21) → ổn định hơn nhưng phản ứng chậm.

---

## Vol Ratio — Khối lượng so với trung bình

```python
if len(vol) >= 20:
    avg20 = vol.iloc[-21:-1].mean()  # trung bình 20 phiên TRƯỚC hôm nay
    res["vol_ratio"] = round(float(vol.iloc[-1]) / avg20, 2)
```

**Tại sao `iloc[-21:-1]` thay vì `iloc[-20:]`?**
- `-21:-1` lấy 20 phiên gần nhất TRƯỚC hôm nay (không tính hôm nay).
- Nếu tính cả hôm nay → circular: vol_ratio của hôm nay phụ thuộc vào chính nó.

**Ý nghĩa:**
- `vol_ratio = 1.5`: Hôm nay giao dịch bằng 1.5 lần bình thường → có sự kiện gì đó.
- `vol_ratio > 2`: Bất thường → digest.py highlight trong bản tin (theo system prompt của Claude).

---

## Screener: Value + Momentum Framework

Screener lọc cổ phiếu theo **hai nhóm tiêu chí kết hợp**:

```
Value criteria            Momentum criteria
─────────────────         ─────────────────
P/E ≤ 15                  Giá > MA50
P/B ≤ 2.5                 RSI 50-70
ROE ≥ 15%                 Return 1 tháng ≥ 0%

Điều kiện: đạt ≥2 value VÀ ≥2 momentum → vào danh sách
```

**Tại sao cần cả hai nhóm?**
- Chỉ value: có thể mua "bẫy giá trị" (value trap) — công ty rẻ nhưng không có catalyst tăng.
- Chỉ momentum: có thể mua đỉnh — cổ phiếu tăng quá mạnh đã rủi ro cao.
- Kết hợp: tìm cổ phiếu có nền tảng tốt VÀ đang có đà tăng.

### Diễn giải từng tiêu chí

**P/E (Price-to-Earnings)**
```
P/E = Giá thị trường / Thu nhập trên mỗi cổ phiếu (EPS)
```
P/E = 10: Bỏ ra 10 đồng để mua 1 đồng thu nhập. P/E thấp = rẻ (tương đối).
Ngưỡng `pe_max: 15` phù hợp với thị trường VN (P/E trung bình VNINDEX thường 12-16).

**P/B (Price-to-Book)**
```
P/B = Giá thị trường / Giá trị sổ sách (Book value) mỗi cổ phiếu
```
P/B = 1: Giá bằng giá trị tài sản ròng trên sổ sách. P/B < 2.5 = không quá đắt.

**ROE (Return on Equity)**
```
ROE = Lợi nhuận ròng / Vốn chủ sở hữu
```
ROE = 15%: Dùng 100 đồng vốn tạo ra 15 đồng lợi nhuận/năm. ≥ 15% là ngưỡng kinh doanh hiệu quả.

### Bạn có thể thay đổi tiêu chí

```yaml
# config/screener.yml — thay đổi theo triết lý đầu tư của bạn

value:
  pe_max: 12     # Khắt khe hơn: chỉ mã thực sự rẻ
  pb_max: 2.0
  roe_min: 0.20  # Chỉ lấy doanh nghiệp hiệu quả cao

momentum:
  rsi_min: 40    # Nới lỏng: chấp nhận mã đang trong vùng phục hồi
  rsi_max: 65
```

---

## Tại sao signals.py là "pure logic" và không có test phức tạp?

```python
def analyze(df):
    if df.empty or "close" not in df.columns:
        return {}
    ...
```

Không cần mock, không cần database, không cần API. Test chỉ là:
```python
def test_analyze_returns_rsi():
    df = pd.DataFrame({"close": [10, 11, 10.5, ...], "volume": [...]})
    result = signals.analyze(df)
    assert "rsi" in result
    assert 0 <= result["rsi"] <= 100
```

Đây là lý do thiết kế "separate concerns" (tách biệt trách nhiệm) có giá trị — module pure logic dễ test nhất.

---

## So sánh: Technical Analysis vs. Fundamental Analysis

| | Technical Analysis | Fundamental Analysis |
|---|---|---|
| Dựa trên | Giá, khối lượng lịch sử | Báo cáo tài chính, ngành |
| Chỉ số | RSI, MA, MACD, Bollinger Bands | P/E, P/B, ROE, EV/EBITDA |
| Horizon | Ngắn-trung hạn (ngày-tháng) | Trung-dài hạn (tháng-năm) |
| Trong repo | `signals.py` (momentum) | `screener.py` (value criteria) |
| Giả thuyết | Giá phản ánh tất cả thông tin, lịch sử lặp lại | Thị trường định giá sai, trả về fair value |

**Screener này kết hợp cả hai** — đây là triết lý GARP (Growth At a Reasonable Price): mua cổ phiếu có nền tảng tốt khi đà tăng đang hỗ trợ.

---

## Từ signals đến pandas — Nền tảng kỹ thuật

Nếu bạn mới làm quen với pandas, đây là các concept cần nắm:

### `.rolling(n).mean()` — Window function
```python
close.rolling(20).mean()
# Với mỗi điểm, tính trung bình 20 điểm gần nhất
# 19 điểm đầu tiên → NaN (chưa đủ 20 điểm)
```

Tương đương SQL:
```sql
AVG(close) OVER (ORDER BY trade_date ROWS 19 PRECEDING)
```

### `.diff()` — Sai phân
```python
close.diff()
# [10, 11, 10.5] → [NaN, +1, -0.5]
```

### `.clip(lower=0)` — Cắt giá trị
```python
delta.clip(lower=0)  # Chỉ giữ giá trị dương (ngày tăng)
(-delta.clip(upper=0))  # Chỉ giữ giá trị âm, đổi dấu (ngày giảm)
```

### `.iloc[-1]` vs `.iloc[-21:-1]`
```python
close.iloc[-1]     # Giá trị cuối cùng
close.iloc[-21:-1] # 20 giá trị, từ vị trí -21 đến -2 (không bao gồm -1)
```
