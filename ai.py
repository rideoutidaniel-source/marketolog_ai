"""AI-консультант: понимает фото, считает цену по прайсу, рисует схему, присылает фото работ."""
import base64
import io
import logging
import os
import random
from pathlib import Path

from aiogram.types import BufferedInputFile, InputMediaPhoto
from PIL import Image

import sketch
from pricing import (
    KITCHEN,
    WARDROBE,
    estimate_kitchen,
    estimate_wardrobe,
    fmt,
    price_summary,
)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "claude-sonnet-5-5")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
# если заданы оба ключа, по умолчанию Gemini (бесплатный); можно принудительно: AI_PROVIDER=claude
PROVIDER = os.getenv("AI_PROVIDER") or ("gemini" if GEMINI_API_KEY else "claude")
enabled = bool(GEMINI_API_KEY if PROVIDER == "gemini" else ANTHROPIC_API_KEY)
PHOTOS_DIR = Path(__file__).parent / "photos"
PHOTO_CATEGORIES = ["kitchen", "wardrobe", "other"]

client = None
if ANTHROPIC_API_KEY and PROVIDER == "claude":
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

history: dict[int, list[dict]] = {}


def system_prompt(shop: dict) -> str:
    return (
        f"Ты — консультант мебельного магазина «{shop['name']}» ({shop['address']}, тел. {shop['phone']}) "
        "в Telegram. Мы делаем кухни и шкафы (корпусная мебель на заказ).\n\n"
        "Правила:\n"
        "1. Отвечай на языке клиента (русский или узбекский), коротко и дружелюбно.\n"
        "2. ЦЕНУ ВСЕГДА считай только инструментами estimate_kitchen и estimate_wardrobe, "
        "сам ничего не умножай и не придумывай цены. Если не хватает данных (материал, длина кухни, "
        "высота потолка, ширина и высота шкафа), сначала задай клиенту вопрос.\n"
        "3. Если клиент прислал фото стены: оцени примерные размеры, опираясь на понятные ориентиры "
        "(дверь около 2.0 м, розетка около 0.3 м от пола и т.п.), честно назови свои допущения и попроси "
        "клиента подтвердить размеры или назвать высоту потолка. Потом вызови draw_sketch и инструмент расчёта.\n"
        "4. Если клиент просит фото шкафов, кухонь или других наших работ, вызови send_photos.\n"
        "5. Всегда говори, что расчёт ориентировочный, а точную цену называет менеджер после замера. "
        "Чертёж — схема, а не точный проект.\n"
        "6. Доставка и установка включены в стоимость. "
        f"Гарантия: {shop['warranty']}\n"
        "7. Когда клиент готов заказать, предложи нажать «Оставить заявку» в меню, менеджер свяжется с ним.\n"
        "8. Не выдумывай материалы, цвета и фурнитуру, которых нет в прайсе. Если не знаешь, скажи, "
        "что уточнит менеджер.\n\n"
        "Прайс:\n" + price_summary()
    )


TOOLS = [
    {
        "name": "estimate_kitchen",
        "description": "Рассчитать ориентировочную стоимость кухни (диапазон от-до) по прайсу.",
        "input_schema": {
            "type": "object",
            "properties": {
                "material": {"type": "string", "enum": list(KITCHEN)},
                "length_m": {"type": "number", "description": "Длина кухни в погонных метрах"},
                "ceiling_m": {"type": "number", "description": "Высота потолка в метрах (по умолчанию 2.8)"},
            },
            "required": ["material", "length_m"],
        },
    },
    {
        "name": "estimate_wardrobe",
        "description": "Рассчитать ориентировочную стоимость шкафа (ширина x высота) по прайсу.",
        "input_schema": {
            "type": "object",
            "properties": {
                "material": {"type": "string", "enum": list(WARDROBE)},
                "width_m": {"type": "number"},
                "height_m": {"type": "number"},
            },
            "required": ["material", "width_m", "height_m"],
        },
    },
    {
        "name": "draw_sketch",
        "description": "Нарисовать схему (вид спереди) кухни или шкафа и отправить её клиенту.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["kitchen", "wardrobe"]},
                "width_m": {"type": "number", "description": "Ширина/длина в метрах"},
                "height_m": {"type": "number", "description": "Высота в метрах"},
                "sections": {"type": "integer", "description": "Количество секций или дверей"},
            },
            "required": ["kind", "width_m", "height_m"],
        },
    },
    {
        "name": "send_photos",
        "description": "Отправить клиенту фото наших работ из галереи.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": PHOTO_CATEGORIES},
                "count": {"type": "integer", "description": "Сколько фото (1-5)"},
            },
            "required": ["category"],
        },
    },
]


def _num(v, lo, hi, name):
    v = float(v)
    if not lo <= v <= hi:
        raise ValueError(f"{name} вне допустимого диапазона {lo}–{hi}")
    return v


async def run_tool(name: str, args: dict, message) -> str:
    try:
        if name == "estimate_kitchen":
            r = estimate_kitchen(
                args["material"],
                _num(args["length_m"], 0.5, 15, "length_m"),
                _num(args.get("ceiling_m", 2.8), 2.0, 4.5, "ceiling_m"),
            )
            note = (
                f" (включая надбавку {fmt(r['extra_per_m'])} сум/пог. м за высоту потолка)"
                if r["steps"]
                else ""
            )
            return (
                f"{r['name']}: {fmt(r['per_m_min'])}–{fmt(r['per_m_max'])} сум за пог. м{note}. "
                f"Итого ориентировочно: от {fmt(r['total_min'])} до {fmt(r['total_max'])} сум."
            )
        if name == "estimate_wardrobe":
            w = _num(args["width_m"], 0.3, 10, "width_m")
            h = _num(args["height_m"], 0.5, 4.5, "height_m")
            r = estimate_wardrobe(args["material"], w, h)
            return (
                f"{r['name']}, площадь {r['area']:.2f} кв. м. "
                f"Итого ориентировочно: от {fmt(r['total_min'])} до {fmt(r['total_max'])} сум."
            )
        if name == "draw_sketch":
            w = _num(args["width_m"], 0.3, 15, "width_m")
            h = _num(args["height_m"], 0.5, 4.5, "height_m")
            png = sketch.draw(args["kind"], w, h, int(args.get("sections", 3)))
            await message.answer_photo(
                BufferedInputFile(png, "sketch.png"),
                caption="Схема ориентировочная (вид спереди). Точный проект делает дизайнер после замера.",
            )
            return "Схема отправлена клиенту."
        if name == "send_photos":
            cat = args["category"]
            folder = PHOTOS_DIR / cat
            files = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
            if not files:
                return "В галерее пока нет фото этой категории. Предложи клиенту, что менеджер пришлёт примеры."
            count = max(1, min(int(args.get("count", 3)), 5, len(files)))
            pick = random.sample(files, count)
            if count == 1:
                await message.answer_photo(BufferedInputFile(pick[0].read_bytes(), pick[0].name))
            else:
                await message.answer_media_group(
                    [InputMediaPhoto(media=BufferedInputFile(p.read_bytes(), p.name)) for p in pick]
                )
            return f"Отправлено фото: {count}."
        return "Неизвестный инструмент."
    except Exception as e:  # возвращаем ошибку модели, чтобы она переспросила
        logging.exception("tool error")
        return f"Ошибка инструмента: {e}"


def prepare_image(data: bytes) -> str:
    """Уменьшаем фото до разумного размера и кодируем в base64 (JPEG)."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((1568, 1568))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.standard_b64encode(buf.getvalue()).decode()


async def _ask_claude(message, shop: dict, text: str, image_b64: str | None = None) -> str:
    uid = message.from_user.id
    stored = history.setdefault(uid, [])
    content: list | str
    if image_b64:
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
            {"type": "text", "text": text or "Клиент прислал фото."},
        ]
    else:
        content = text
    msgs = stored + [{"role": "user", "content": content}]
    final = ""
    for _ in range(6):  # защита от бесконечного цикла инструментов
        resp = await client.messages.create(
            model=AI_MODEL,
            max_tokens=1500,
            system=system_prompt(shop),
            tools=TOOLS,
            messages=msgs,
        )
        if resp.stop_reason == "tool_use":
            msgs.append({"role": "assistant", "content": resp.content})
            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    out = await run_tool(block.name, block.input, message)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            msgs.append({"role": "user", "content": results})
            continue
        final = "".join(b.text for b in resp.content if b.type == "text").strip()
        break
    final = final or "Не удалось подготовить ответ. Попробуйте переформулировать или оставьте заявку."
    # в историю кладём только текст (без картинок и инструментов), помним последние 12 записей
    stored.append({"role": "user", "content": (text or "[фото]") if not image_b64 else f"[фото] {text}".strip()})
    stored.append({"role": "assistant", "content": final})
    del stored[:-12]
    return final


# ---------------- Gemini (Interactions API) ----------------
GEM_TOOLS = [
    {"type": "function", "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
    for t in TOOLS
]
gem_state: dict[int, str] = {}  # id последнего взаимодействия на пользователя (память диалога на стороне Google)


async def _gem_post(payload: dict) -> dict:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            GEMINI_URL, json=payload, headers={"x-goog-api-key": GEMINI_API_KEY}
        ) as resp:
            data = await resp.json(content_type=None)
            if resp.status >= 400:
                raise RuntimeError(f"Gemini HTTP {resp.status}: {str(data)[:300]}")
            return data


def _gem_text(steps: list) -> str:
    out = []
    for st in steps:
        if st.get("type") == "model_output":
            for c in st.get("content", []):
                if c.get("type") == "text":
                    out.append(c.get("text", ""))
    return "".join(out).strip()


async def _ask_gemini(message, shop: dict, text: str, image_b64: str | None = None) -> str:
    uid = message.from_user.id
    prompt = system_prompt(shop)
    if image_b64:
        user_input = [
            {"type": "text", "text": text or "Клиент прислал фото."},
            {"type": "image", "data": image_b64, "mime_type": "image/jpeg"},
        ]
    else:
        user_input = text

    def first_payload(use_prev: bool) -> dict:
        p = {"model": GEMINI_MODEL, "input": user_input, "tools": GEM_TOOLS, "system_instruction": prompt}
        if use_prev and gem_state.get(uid):
            p["previous_interaction_id"] = gem_state[uid]
        return p

    payload = first_payload(True)
    final = ""
    for turn in range(6):  # защита от бесконечного цикла инструментов
        try:
            data = await _gem_post(payload)
        except RuntimeError:
            if turn == 0 and "previous_interaction_id" in payload:
                # память диалога истекла (на бесплатном тарифе хранится сутки), начинаем заново
                gem_state.pop(uid, None)
                payload = first_payload(False)
                data = await _gem_post(payload)
            else:
                raise
        steps = data.get("steps", [])
        calls = [st for st in steps if st.get("type") == "function_call"]
        if calls:
            results = []
            for c in calls:
                out = await run_tool(c.get("name", ""), c.get("arguments") or {}, message)
                results.append(
                    {
                        "type": "function_result",
                        "name": c.get("name", ""),
                        "call_id": c.get("id", ""),
                        "result": [{"type": "text", "text": out}],
                    }
                )
            payload = {
                "model": GEMINI_MODEL,
                "previous_interaction_id": data["id"],
                "input": results,
                "tools": GEM_TOOLS,
                "system_instruction": prompt,
            }
            continue
        if data.get("id"):
            gem_state[uid] = data["id"]
        final = _gem_text(steps)
        break
    return final or "Не удалось подготовить ответ. Попробуйте переформулировать или оставьте заявку."


async def ask(message, shop: dict, text: str, image_b64: str | None = None) -> str:
    if PROVIDER == "gemini":
        return await _ask_gemini(message, shop, text, image_b64)
    return await _ask_claude(message, shop, text, image_b64)
