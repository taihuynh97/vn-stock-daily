"""Dùng Claude API để DIỄN GIẢI dữ liệu đã tính sẵn thành bản tin tiếng Việt.

Nguyên tắc quan trọng:
  - Mọi CON SỐ do các module signals/screener tính, không để mô hình tự bịa.
  - Bản tin là tổng hợp THÔNG TIN, không phải khuyến nghị mua/bán cá nhân hoá.
"""
import os
import json
import anthropic

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

SYSTEM = """Bạn là biên tập viên bản tin chứng khoán, viết cho một nhà đầu tư cá nhân bận rộn \
đọc lướt trên điện thoại sau phiên. Phong cách: NGẮN, SẮC, mỗi dòng đáng giá — không lan man, \
không sáo rỗng, không nhắc lại số liệu thừa.

Quy tắc bắt buộc:
- Chỉ dùng số liệu được cung cấp. TUYỆT ĐỐI không bịa con số, tin tức hay nhận định vô căn cứ.
- KHÔNG khuyên mua/bán. Chỉ nêu tín hiệu và bối cảnh trung lập để người đọc tự quyết.
- ĐẶT BỐI CẢNH: so sánh %thay đổi của mỗi mã với VNINDEX để biết mã ĐANG VƯỢT hay KÉM thị trường — \
chỉ nói ra khi chênh lệch đáng kể, đừng máy móc.
- Làm nổi cái BẤT THƯỜNG: lãi/lỗ lớn, biến động mạnh, RSI>70 (quá mua) / <30 (quá bán), \
khối lượng gấp >1.5 lần. Cái gì bình thường thì lướt nhanh.
- Mỗi mã 1 dòng duy nhất. Emoji làm mỏ neo (🟢/🔴/⚠️) nhưng tiết chế.
- Tiếng Việt tự nhiên, văn bản thuần (không markdown) vì gửi qua Telegram."""

TEMPLATE = """Viết bản tin ngày {run_date} từ dữ liệu JSON dưới đây.

THỊ TRƯỜNG (VNINDEX): {market}

DANH MỤC (mỗi mã có thêm trường industry = ngành):
{portfolio}

SCREENER (value + momentum):
{screener}

TIN MỚI:
{news}

Trình bày ĐÚNG bố cục, giữ tiêu đề, mỗi mục thật gọn:

📊 Bản tin {run_date}

📈 THỊ TRƯỜNG
[1 dòng: VNINDEX ±% phiên (+ xu hướng 5 phiên nếu đáng nói), sắc thái chung tăng/giảm/giằng co.]

💼 DANH MỤC — [cụm ngắn: tổng lãi/lỗ & mã nổi bật nhất]
• MÃ (ngành) giá ±% | lãi/lỗ ±% | RSI [⚠️ + lý do nếu bất thường; vượt/kém TT nếu rõ rệt]
[... mỗi mã 1 dòng ...]

🔍 ĐÁNG CHÚ Ý
[Mỗi mã screener 1 dòng: MÃ — lý do lọt lưới (theo trường reason). KHÔNG nói "nên mua". Rỗng → "Không có mã mới."]

📰 TIN
[Tối đa 3 tin quan trọng, mỗi tin 1 dòng kèm mã. Bỏ tin PR/nhiễu. Nếu rỗng, BỎ HẲN mục này.]

ℹ️ Tham khảo, không phải khuyến nghị đầu tư.

Giới hạn: toàn bản tin ~150 từ. Không thêm gì ngoài bố cục trên."""


def build(run_date, market, portfolio_rows, screener_rows, news_items) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = TEMPLATE.format(
        run_date=run_date,
        market=json.dumps(market, ensure_ascii=False) or "(không lấy được)",
        portfolio=json.dumps(portfolio_rows, ensure_ascii=False, indent=1),
        screener=json.dumps(screener_rows, ensure_ascii=False, indent=1) or "(rỗng)",
        news=json.dumps(news_items, ensure_ascii=False, indent=1) or "(rỗng)",
    )

    msg = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()
