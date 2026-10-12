"""Прайс и расчёт. Все цены в сумах. Меняйте значения здесь."""
import math

BASE_CEILING = 2.8  # высота потолка, для которой действует базовая цена

# цена за погонный метр кухни: от / до / надбавка за каждые +0.1 м потолка (за пог. м)
KITCHEN = {
    "ldsp": {"name": "ЛДСП (ламинат)", "min": 2_000_000, "max": 3_800_000, "step": 100_000},
    "acrylic_1": {"name": "Акрил односторонний", "min": 3_000_000, "max": 4_500_000, "step": 200_000},
    "acrylic_2": {"name": "Акрил двухсторонний", "min": 4_500_000, "max": 7_000_000, "step": 400_000},
    "classic": {"name": "Классика без камня", "min": 6_500_000, "max": 8_000_000, "step": 600_000},
}

# цена за квадратный метр шкафа (ширина x высота)
WARDROBE = {
    "ldsp": {"name": "ЛДСП (ламинат)", "min": 750_000, "max": 950_000},
    "mdf": {"name": "МДФ", "min": 950_000, "max": 1_150_000},
}


def fmt(n: float) -> str:
    return f"{round(n):,}".replace(",", " ")


def estimate_kitchen(material: str, length_m: float, ceiling_m: float = BASE_CEILING) -> dict:
    m = KITCHEN[material]
    steps = max(0, math.ceil(round((ceiling_m - BASE_CEILING) / 0.1, 6)))
    extra = steps * m["step"]
    per_min, per_max = m["min"] + extra, m["max"] + extra
    return {
        "name": m["name"],
        "steps": steps,
        "extra_per_m": extra,
        "per_m_min": per_min,
        "per_m_max": per_max,
        "total_min": per_min * length_m,
        "total_max": per_max * length_m,
    }


def estimate_wardrobe(material: str, width_m: float, height_m: float) -> dict:
    m = WARDROBE[material]
    area = width_m * height_m
    return {
        "name": m["name"],
        "area": area,
        "total_min": m["min"] * area,
        "total_max": m["max"] * area,
    }


def price_summary() -> str:
    lines = ["Кухня, цена за погонный метр (потолок %.1f м):" % BASE_CEILING]
    for m in KITCHEN.values():
        lines.append(
            f"- {m['name']}: {fmt(m['min'])}–{fmt(m['max'])} сум; "
            f"каждые +0.1 м потолка выше {BASE_CEILING} м: +{fmt(m['step'])} сум за пог. м"
        )
    lines.append("Шкаф, цена за кв. м (ширина x высота):")
    for m in WARDROBE.values():
        lines.append(f"- {m['name']}: {fmt(m['min'])}–{fmt(m['max'])} сум")
    return "\n".join(lines)
