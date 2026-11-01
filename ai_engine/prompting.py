"""រៀប System Prompt ដែល AI ទទួលបាន៖ persona + few-shot + Catalog ផលិតផល។"""
from __future__ import annotations

from database.models import Product
from helpers import money


def format_catalog(products: list[Product]) -> str:
    """បញ្ជីផលិតផលសង្ខេប ដើម្បី AI ឆ្លើយពីតម្លៃ/stock បានត្រឹមត្រូវ។"""
    active = [item for item in products if item.is_active]
    if not active:
        return "(មិនមានផលិតផលសកម្មទេ)"
    lines = []
    for item in active:
        remaining = item.remaining
        note = "អស់ស្តុក" if remaining <= 0 else f"សល់ {remaining}"
        price = f"{money(item.final_price)}"
        if item.discount_percent:
            price += f" (កាត់បន័យ {item.discount_percent}% ពី {money(item.price)})"
        lines.append(
            (f"{item.product_code} | " if item.product_code else "")
            + f"- {item.name} | {price} | ប្រភេទ: {item.category} | {note}"
            + (f" | {item.description[:120]}" if item.description else "")
        )
    return "\n".join(lines)


def compose_system_prompt(base: str, few_shot: str, catalog: str) -> str:
    """Prompt ចុងក្រោយដែលផ្ញើទៅ AI Engine រៀងរាល់សារ។"""
    blocks = [base.strip(), "បញ្ជីផលិតផល (Catalog)៖\n" + catalog]
    if few_shot.strip():
        blocks.append("ឧទាហរណ៍ការឆ្លើយតប (Few-shot)៖\n" + few_shot.strip())
    blocks.append(
        "ច្បាប់សំខាន់៖ ប្រើតែទិន្នន័យក្នុង Catalog។ កុំប្រឌិតតម្លៃ ឬ stock។ "
        "កុំផ្ញើ Code ទេ — ម្ចាស់ជាអ្នកបញ្ជាក់ការទូទាត់។ ឆ្លើយខ្លី ជាភាសាខ្មែរ។ "
        "បើគេចង់រកអីវ៉ាន់ → ណែនាំវាយ «menu» ជ្រើសប្រភេទតាមប៊ូតុង។ "
        "Voice/Video note យើងស្តាប់មិនបានទេ — សុំវាយជាអក្សរ។"
    )
    return "\n\n".join(block for block in blocks if block)
