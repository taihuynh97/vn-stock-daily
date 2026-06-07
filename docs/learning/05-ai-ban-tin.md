# 05 — AI Bản tin (Claude API + Prompt Engineering)

## Files liên quan
- `src/digest.py` — gọi Claude API, xây dựng prompt, nhận bản tin
- `src/notify.py` — gửi Telegram
- `src/storage.py` — lưu bản tin, dedup tin tức

---

## Kiến trúc AI trong pipeline này

Điều quan trọng cần hiểu: **AI không tính toán số liệu**. Tất cả số đã được tính trước.

```
Tính toán (deterministic)        AI (language model)
────────────────────────         ────────────────────
signals.analyze() → RSI=62      digest.build() → "RSI 62, tiếp cận
screener.run() → [VNM, FPT]      vùng quá mua cần lưu ý"
ingest.fetch_news() → ["tin1"]
         │
         └── JSON data ──────────────► Claude API ──► Bản tin tiếng Việt
```

**Tại sao thiết kế vậy?**
- LLM (Large Language Model) giỏi ngôn ngữ tự nhiên, nhưng **hay "hallucinate" (bịa) số liệu**.
- Cung cấp số liệu chính xác qua prompt → LLM chỉ làm nhiệm vụ diễn giải và viết văn.
- Kết quả: bản tin có ngôn ngữ tự nhiên nhưng số liệu chính xác.

---

## Prompt Engineering — Kỹ thuật viết prompt

### Cấu trúc prompt trong repo

```python
# Hai phần: system prompt và user prompt

SYSTEM = """Bạn là biên tập viên bản tin chứng khoán...
Quy tắc bắt buộc:
- Chỉ dùng số liệu được cung cấp. TUYỆT ĐỐI không bịa...
- KHÔNG khuyên mua/bán...
"""

TEMPLATE = """Viết bản tin ngày {run_date} từ dữ liệu JSON...
THỊ TRƯỜNG: {market}
DANH MỤC: {portfolio}
...
Trình bày ĐÚNG bố cục...
"""
```

### Vai trò của System Prompt vs. User Prompt

| | System Prompt | User Prompt |
|---|---|---|
| Mục đích | Định nghĩa vai trò, constraint, phong cách | Dữ liệu + yêu cầu cụ thể |
| Khi nào thay đổi | Hiếm (khi muốn đổi phong cách bản tin) | Mỗi lần chạy |
| Ví dụ | "Bạn là biên tập viên..." | "Viết bản tin ngày 2026-06-07..." |

### Các kỹ thuật prompt dùng trong file

**1. Role prompting** — Gán vai trò cụ thể
```
"Bạn là biên tập viên bản tin chứng khoán, viết cho nhà đầu tư cá nhân bận rộn..."
```
Vai trò rõ ràng → LLM hiểu tone, style, audience.

**2. Constraint chaining** — Liệt kê ràng buộc rõ ràng
```
"TUYỆT ĐỐI không bịa con số"
"KHÔNG khuyên mua/bán"
"Giới hạn: toàn bản tin ~150 từ"
```

**3. Format specification** — Chỉ định format output
```
"📊 Bản tin {run_date}
📈 THỊ TRƯỜNG
[1 dòng: VNINDEX ...]
💼 DANH MỤC — ...
• MÃ (ngành) giá ±% | lãi/lỗ ..."
```
Chỉ định cấu trúc cụ thể → output nhất quán, dễ đọc trên Telegram.

**4. Cung cấp dữ liệu dạng JSON**
```python
portfolio=json.dumps(portfolio_rows, ensure_ascii=False, indent=1)
```
JSON có cấu trúc rõ ràng → LLM dễ parse hơn free-form text.

**5. Highlight exception** — Chỉ nói ra khi bất thường
```
"Làm nổi cái BẤT THƯỜNG: lãi/lỗ lớn, biến động mạnh, RSI>70, khối lượng gấp >1.5 lần. 
Cái gì bình thường thì lướt nhanh."
```
Tránh bản tin dài dòng liệt kê mọi thứ — chỉ alert khi cần.

---

## Anthropic SDK — Gọi API Claude

```python
import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

msg = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1200,
    system=SYSTEM,
    messages=[{"role": "user", "content": prompt}],
)
return "".join(b.text for b in msg.content if b.type == "text").strip()
```

**`msg.content`**: Anthropic trả về list các "content blocks". Với text response thông thường, sẽ có 1 block với `type="text"`. Join để an toàn.

**`max_tokens=1200`**: Giới hạn độ dài output (~900 từ). Với bản tin 150 từ, 1200 token là thừa — nhưng đặt cao hơn một chút để không bị cắt giữa chừng.

### So sánh các model Claude

| Model | ID | Phù hợp |
|---|---|---|
| Opus 4 | `claude-opus-4-8` | Phức tạp nhất, tốn nhất |
| Sonnet 4 | `claude-sonnet-4-6` (đang dùng) | Cân bằng chất lượng/chi phí |
| Haiku 4 | `claude-haiku-4-5-20251001` | Nhanh nhất, rẻ nhất, cho task đơn giản |

Với bản tin ~150 từ, Haiku cũng đủ tốt và rẻ hơn. Sonnet được dùng vì độ tin cậy cao hơn với multi-step reasoning.

---

## Telegram Bot API

```python
# src/notify.py
API = "https://api.telegram.org/bot{token}/sendMessage"
LIMIT = 4000  # Telegram giới hạn 4096 ký tự/tin nhắn

def send(text: str):
    chunks = [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)]
    for chunk in chunks:
        r = requests.post(url, data={
            "chat_id": chat_id,
            "text": chunk,
            "disable_web_page_preview": True,
        }, timeout=30)
```

**Chunking**: Nếu bản tin dài hơn 4000 ký tự → tự động chia thành nhiều tin nhắn.
**`disable_web_page_preview`**: Tắt preview URL để bản tin gọn hơn.

### Tại sao Telegram?

| Kênh | Setup | Chi phí | Mobile-friendly |
|---|---|---|---|
| **Telegram Bot** (đang dùng) | API token + chat_id | Free | Tốt nhất |
| Email | SMTP config | Free | Trung bình |
| Slack | Workspace + webhook | Free tier | Tốt |
| Discord | Server + webhook | Free | Tốt |
| LINE | Business account | Có phí | Tốt |

---

## Dedup tin tức (Seen News Pattern)

```python
# src/storage.py
def filter_new_news(news_items):
    fresh = []
    with _conn() as c:
        for n in news_items:
            nid = str(n.get("id") or n.get("title"))
            cur = c.execute("SELECT 1 FROM seen_news WHERE news_id=?", (nid,))
            if cur.fetchone() is None:
                fresh.append(n)
                c.execute("INSERT OR IGNORE INTO seen_news VALUES (...)")
    return fresh
```

**Vấn đề**: Cùng một tin xuất hiện nhiều ngày liên tiếp → bản tin lặp tin.

**Giải pháp**: Lưu `news_id` (hoặc title nếu không có id) vào `seen_news`. Lần sau skip.

**`INSERT OR IGNORE`**: Nếu đã có → bỏ qua, không raise error. Đảm bảo không lặp trong trường hợp race condition.

---

## Toàn bộ flow từ số liệu đến bản tin

```python
# Đầu vào cho Claude (JSON):
{
  "market": {"index": "VNINDEX", "close": 1285.4, "change_pct": 0.32},
  "portfolio": [
    {"symbol": "VNM", "close": 85000, "change_pct": -0.5,
     "pnl_pct": 12.3, "rsi": 68.2, "vol_ratio": 1.8, "industry": "Hàng tiêu dùng"}
  ],
  "screener": [
    {"symbol": "FPT", "score": 5.0, "reason": "P/E 12.5≤15 | ROE 21%≥15% | giá>MA50 | RSI 55"}
  ]
}

# Output Claude:
📊 Bản tin 2026-06-07

📈 THỊ TRƯỜNG
VNINDEX +0.32% (1,285.4), phiên tích cực nhẹ, đà ngắn hạn trung tính.

💼 DANH MỤC — đa số ổn, VNM cần lưu ý
• VNM (Tiêu dùng) 85k -0.5% | lãi +12.3% | RSI 68.2 ⚠️ khối lượng cao 1.8x, RSI tiệm cận quá mua

🔍 ĐÁNG CHÚ Ý
FPT — P/E hợp lý, ROE cao, đà tăng vững trên MA50

ℹ️ Tham khảo, không phải khuyến nghị đầu tư.
```
