# vn-stock-daily

Job tự động chạy mỗi ngày sau giờ đóng cửa, tổng hợp tình hình **danh mục đang giữ** + lọc **mã tiềm năng** (value + momentum), nhờ Claude diễn giải thành bản tin tiếng Việt và đẩy qua **Telegram**.

> ⚠️ **Miễn trừ trách nhiệm:** đây là công cụ tổng hợp thông tin và phát tín hiệu để tham khảo, **không phải lời khuyên đầu tư**. Mọi quyết định mua/bán là của bạn. Dữ liệu vnstock là cuối phiên/có độ trễ, không dùng cho giao dịch trong ngày.

## Kiến trúc

Hai nhánh độc lập, dùng chung một warehouse trên MotherDuck:

```
INGESTION (Python)                WAREHOUSE            CONSUMERS
build_warehouse.py --mode         raw_* (immutable)    ├─ MCP server (hội thoại)
  daily   → giá EOD + chỉ số        ↓ dbt              ├─ main.py (bản tin Telegram)
  weekly  → tỷ số + sự kiện DN    stg_* → int_*        └─ SQL ad-hoc
  monthly → hồ sơ DN + sở hữu       ↓
                                  mart_* ← nơi mọi phân tích query vào
```

- `transforms/` — dbt project (staging → intermediate → marts)
- `src/scoring.py` + `config/scoring_profiles.yml` — bộ chấm điểm, đổi "gu" đầu tư ở đây
- `mcp_server/` — 13 tool read-only cho luồng hội thoại

### Bật/tắt luồng hội thoại

Xoá khai báo trong `.mcp.json` là tắt hoàn toàn MCP server. Warehouse, dbt và
bản tin Telegram không bị ảnh hưởng.

### Chạy screener bằng dòng lệnh

```bash
export WAREHOUSE_DB=md:vn_market
python -c "
from src import warehouse, scoring
con = warehouse.get_conn()
print(scoring.screen(con, 'bluechip_dividend', limit=20).to_string())
"
```

## Cấu hình

- `config/portfolio.yml` — các mã bạn giữ, giá vốn, số lượng.
- `config/screener.yml` — tiêu chí value/momentum. **Chỉnh ở đây để khớp triết lý đầu tư của bạn.**

## Chạy thử ở máy (WSL)

```bash
pip install -r requirements.txt
cp .env.example .env   # điền key vào
python main.py
```

## Lập lịch bằng GitHub Actions

File `.github/workflows/daily.yml` đã set cron **08:30 UTC (15:30 giờ VN), T2–T6**. Cần khai báo secrets trong repo (Settings → Secrets and variables → Actions):

| Secret | Lấy ở đâu |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | nhắn **@BotFather** → `/newbot` |
| `TELEGRAM_CHAT_ID` | nhắn cho bot 1 tin, rồi mở `https://api.telegram.org/bot<token>/getUpdates` lấy `chat.id` |
| `VNSTOCK_API_KEY` | (tuỳ chọn) đăng ký miễn phí ở vnstocks.com nếu nguồn dữ liệu yêu cầu |

Bấm **Run workflow** ở tab Actions để chạy tay kiểm tra trước khi để chạy tự động.

## Những điểm cần biết

- **Nguồn hợp lệ:** giá, báo cáo TC, chỉ số, tin doanh nghiệp đều qua API vnstock. Job **không** scrape báo cáo phân tích có bản quyền của các CTCK.
- **vnstock đổi API:** mọi lời gọi vnstock gói trong `src/ingest.py`; thư viện cập nhật thì chỉ sửa 1 file. Một số nguồn dữ liệu/mã có thể cần API key vnstock miễn phí.
- **Chi phí:** mỗi lần chạy gọi Claude API 1 lần (~vài nghìn token), rất nhỏ. GitHub Actions miễn phí trong hạn mức repo cá nhân.
- **Cron GHA** chạy theo UTC và đôi khi trễ vài phút lúc cao điểm — không sao với job cuối phiên.
