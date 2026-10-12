"""Схематичные чертежи (вид спереди) через Pillow. Подписи только цифрами, чтобы не зависеть от шрифтов."""
import io

from PIL import Image, ImageDraw, ImageFont

BG = (250, 250, 247)
LINE = (40, 40, 40)
FILL_BASE = (222, 205, 180)
FILL_UPPER = (236, 224, 205)
FILL_DOOR = (214, 200, 182)
DIM = (180, 40, 40)


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _dim_h(d, x1, x2, y, text, font):
    d.line([(x1, y), (x2, y)], fill=DIM, width=2)
    for x in (x1, x2):
        d.line([(x, y - 8), (x, y + 8)], fill=DIM, width=2)
    d.text(((x1 + x2) / 2, y + 10), text, fill=DIM, font=font, anchor="mt")


def _dim_v(d, x, y1, y2, text, font):
    d.line([(x, y1), (x, y2)], fill=DIM, width=2)
    for y in (y1, y2):
        d.line([(x - 8, y), (x + 8, y)], fill=DIM, width=2)
    d.text((x - 12, (y1 + y2) / 2), text, fill=DIM, font=font, anchor="rm")


def draw(kind: str, width_m: float, height_m: float, sections: int = 3) -> bytes:
    W, H, M = 1100, 900, 110
    scale = min((W - 2 * M) / width_m, (H - 2 * M) / height_m)
    pw, ph = width_m * scale, height_m * scale
    x0 = (W - pw) / 2
    y_floor = (H + ph) / 2
    y_top = y_floor - ph

    def Y(m):  # высота в метрах -> координата y
        return y_floor - m * scale

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    f = _font(26)

    # стена
    d.rectangle([x0, y_top, x0 + pw, y_floor], outline=LINE, width=3)
    n = max(1, int(sections))

    if kind == "kitchen":
        base_h = 0.85
        d.rectangle([x0, Y(base_h), x0 + pw, y_floor], fill=FILL_BASE, outline=LINE, width=3)
        step = pw / n
        for i in range(1, n):
            d.line([(x0 + i * step, Y(base_h)), (x0 + i * step, y_floor)], fill=LINE, width=2)
        d.line([(x0, Y(base_h)), (x0 + pw, Y(base_h))], fill=LINE, width=8)  # столешница
        up_bot = 1.4
        up_top = min(2.2, height_m - 0.1)
        if up_top > up_bot + 0.3:
            d.rectangle([x0, Y(up_top), x0 + pw, Y(up_bot)], fill=FILL_UPPER, outline=LINE, width=3)
            for i in range(1, n):
                d.line([(x0 + i * step, Y(up_top)), (x0 + i * step, Y(up_bot))], fill=LINE, width=2)
    else:  # шкаф
        d.rectangle([x0, y_top, x0 + pw, y_floor], fill=FILL_DOOR, outline=LINE, width=4)
        step = pw / n
        for i in range(1, n):
            xx = x0 + i * step
            d.line([(xx, y_top), (xx, y_floor)], fill=LINE, width=3)
        for i in range(n):
            cx = x0 + (i + 0.5) * step
            d.rectangle([cx - 4, Y(1.3), cx + 4, Y(0.9)], fill=LINE)  # ручка

    _dim_h(d, x0, x0 + pw, y_floor + 40, f"{width_m:.2f} m", f)
    _dim_v(d, x0 - 30, y_top, y_floor, f"{height_m:.2f} m", f)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
