"""📦 ប្រភេទអីវ៉ាន់ (Categories) — ម៉ឺនុគ្រប់គ្រង + CRUD + ពាក្យសັ່ងខ្លី។"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards
from admin_bot.owner_gate import OwnerOnly
from admin_bot.scope import Scope
from database import crud, db_session
from database.models import Category
from helpers import esc

router = Router()
log = logging.getLogger("admin.categories")


class AddCategory(StatesGroup):
    code = State()
    name_kh = State()
    name_en = State()
    icon = State()
    prefix = State()
    description = State()


class EditCategory(StatesGroup):
    value = State()


ADD_LABELS = {
    "code": "🔑 <b>code</b> អង់គ្លេសតូច (ឧ. <code>game_acc</code):",
    "name_kh": "📛 <b>ឈ្មោះខ្មែរ</b> (ឧ. គណនីហ្គេម):",
    "name_en": "🇬🇧 <b>ឈ្មោះអង់គ្លេស</b> (<code>-</code> = ទទេ):",
    "icon": "🎨 <b>Icon</b> (ឧ. 🎮):",
    "prefix": "🔤 <b>Prefix</b> សម្រាប់ Code ផលិតផល (ឧ. GAME ឬ <code>-</code> = ស្វ័យប្រវត្តិ):",
    "description": "📝 <b>ការពិពណ៌នា</b> (<code>-</code> = ទទេ):",
}

EDIT_LABELS = {
    "name_kh": "📛 ឈ្មោះខ្មែរថ្មី:",
    "name_en": "🇬🇧 ឈ្មោះអង់គ្លេសថ្មី (<code>-</code> ដើម្បីសម្អាត):",
    "icon": "🎨 Icon ថ្មី (ឧ. 🎮):",
    "prefix": "🔤 Prefix ថ្មី (<code>-</code> = ស្វ័យប្រវត្តិតាម code):",
    "description": "📝 ការពិពណ៌នាថ្មី (<code>-</code> ដើម្បីសម្អាត):",
}

EDIT_STEP_KEYS = list(ADD_LABELS)

ADD_STATES = {
    "code": AddCategory.code,
    "name_kh": AddCategory.name_kh,
    "name_en": AddCategory.name_en,
    "icon": AddCategory.icon,
    "prefix": AddCategory.prefix,
    "description": AddCategory.description,
}


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


def category_card(category: Category, count: int) -> str:
    return "\n".join(
        [
            f"{category.icon} <b>{esc(category.name_kh)}</b>  <code>&lt;{esc(category.code)}&gt;</code>",
            f"🇬🇧 {esc(category.name_en or '—')} · 🔤 prefix <code>{esc(category.product_prefix)}</code>",
            f"📦 ផលិតផល: <b>{count}</b> · {'🟢 បើក' if category.is_active else '⚪ បិទ'} · លំដាប់បង្ហាញ {category.display_order}",
            f"📝 {esc(category.description or '—')}",
        ]
    )


async def show_manager(event: Message | CallbackQuery, scope: Scope) -> None:
    async with db_session() as session:
        categories = await crud.list_all_categories(session)
        counts = await crud.category_product_counts(session, owner_admin_id=scope.owner_id)
    if not scope.is_owner:
        # taxonomy នៅ global ដដែល — staff មើលឃើញតែប្រភេទដែលមានផលិតផលរបស់ខ្លួន
        categories = [item for item in categories if counts.get(item.id)]
    text = "📦 <b>ប្រភេទអីវ៉ាន់</b>\n<i>ជ្រើសរើសដើម្បី កែ/បិទ/លុប ឬ ➕ បន័ែមថ្មី</i>"
    if not categories:
        text = ("📦 <b>ប្រភេទអីវ៉ាន់</b>\n"
                "<i>មិនមានប្រភេទដែលមានផលិតផលរបស់អ្នកទេ — ប្រភេទជាទិន្នន័យរួម "
                "(សូមម្ចាស់បន្ថែម) ប៉ុន្តែអ្នកនៅតែជ្រើសរើសវាពេល ➕ បន័ែមផលិតផលបាន</i>")
    markup = keyboards.category_manager(categories, counts, can_manage=scope.is_owner)
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.edit_text(text, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


# ---------------- ម៉ឺនុ ----------------

@router.callback_query(F.data == "menu:categories")
async def cb_categories_root(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await show_manager(callback, scope)


@router.message(Command("categories"))
async def cmd_categories(message: Message, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await show_manager(message, scope)


@router.callback_query(F.data.startswith("cat:view:"))
async def cb_category_view(callback: CallbackQuery, scope: Scope) -> None:
    category_id = target_id(callback)
    async with db_session() as session:
        category = await crud.get_category(session, category_id)
        if category is None:
            await callback.answer("រកមិនឃើញ", show_alert=True)
            return
        counts = await crud.category_product_counts(session, owner_admin_id=scope.owner_id)
        if not scope.is_owner and not counts.get(category.id):
            log.info("IDOR: user=%s cat=%s ក្រៅវិសាលភាព", scope.admin_id, category_id)
            await callback.answer("🔒 ប្រភេទនេះគ្មានផលិតផលរបស់អ្នកទេ", show_alert=True)
            return
        card = category_card(category, counts.get(category.id, 0))
        markup = keyboards.category_actions(category, counts.get(category.id, 0), can_manage=scope.is_owner)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(card, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:toggle:"), OwnerOnly())
async def cb_category_toggle(callback: CallbackQuery, scope: Scope) -> None:
    category_id = target_id(callback)
    async with db_session() as session:
        category = await crud.get_category(session, category_id)
        if category is None:
            await callback.answer("រកមិនឃើញ", show_alert=True)
            return
        category.is_active = not category.is_active
        active = category.is_active
    await callback.answer("បានបើកប្រភេទ" if active else "បានបិទប្រភេទ")
    await cb_category_view(callback, scope)


# ---------------- បន័ែមថ្មី ----------------

async def _start_add(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddCategory.code)
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.answer(ADD_LABELS["code"])
        await event.answer()
    else:
        await event.answer(ADD_LABELS["code"])


@router.callback_query(F.data == "cat:add", OwnerOnly())
async def cb_category_add(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_add(callback, state)


@router.message(Command("addcategory"), OwnerOnly())
async def cmd_add_category(message: Message, state: FSMContext) -> None:
    await _start_add(message, state)


@router.message(AddCategory.code, F.text, OwnerOnly())
async def md_add_code(message: Message, state: FSMContext) -> None:
    code = message.text.strip().lower().replace(" ", "_")
    if not code or not code.replace("_", "").isalnum():
        await message.answer("⛔ code ត្រូវជាអក្សរអង់គ្លេស/លេខ/underscore (ឧ. <code>game_acc</code>):")
        return
    async with db_session() as session:
        if await crud.get_category_by_code(session, code) is not None:
            await message.answer(f"⛔ code <code>{esc(code)}</code> មានស្រាប់ហើយ — សរសេរថ្មី:")
            return
    await state.update_data(new_code=code)
    await state.set_state(AddCategory.name_kh)
    await message.answer(ADD_LABELS["name_kh"])


@router.message(AddCategory.name_kh, F.text, OwnerOnly())
async def md_add_name_kh(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("⛔ ឈ្មោះខ្មែរមិនអាចទទេ:")
        return
    await state.update_data(new_name_kh=name)
    await state.set_state(AddCategory.name_en)
    await message.answer(ADD_LABELS["name_en"])


async def _add_step(message: Message, state: FSMContext, key: str, value: str) -> None:
    await state.update_data(**{f"new_{key}": value})
    index = EDIT_STEP_KEYS.index(key) + 1
    if index >= len(EDIT_STEP_KEYS):
        await _finish_add(message, state)
        return
    await state.set_state(ADD_STATES[EDIT_STEP_KEYS[index]])
    await message.answer(ADD_LABELS[EDIT_STEP_KEYS[index]])


def _optional(raw: str) -> str:
    return "" if raw in ("-", "ទទេ", "skip") else raw


async def _finish_add(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    async with db_session() as session:
        category, error = await crud.create_category(
            session,
            code=data["new_code"],
            name_kh=data["new_name_kh"],
            name_en=_optional(data.get("new_name_en", "")),
            icon=(data.get("new_icon") or "📦").strip()[:4] or "📦",
            prefix=_optional(data.get("new_prefix", "")).upper()[:5],
            description=_optional(data.get("new_description", "")),
        )
        if category is None:
            await message.answer(f"⛔ បរាជ័យ: {esc(error)}")
            await state.set_state(AddCategory.code)
            return
        card = category_card(category, 0)
    await state.clear()
    await message.answer(
        f"✅ បានបន្ថែមប្រភេទថ្មី\n{card}",
        reply_markup=keyboards.build([[("⬅️ បញ្ជីប្រភេទ", "menu:categories"), ("🏠 មេនុសំខាន់", "menu:main")]]),
    )


@router.message(AddCategory.name_en, F.text, OwnerOnly())
async def md_add_name_en(message: Message, state: FSMContext) -> None:
    await _add_step(message, state, "name_en", message.text.strip())


@router.message(AddCategory.icon, F.text, OwnerOnly())
async def md_add_icon(message: Message, state: FSMContext) -> None:
    await _add_step(message, state, "icon", message.text.strip())


@router.message(AddCategory.prefix, F.text, OwnerOnly())
async def md_add_prefix(message: Message, state: FSMContext) -> None:
    await _add_step(message, state, "prefix", message.text.strip())


@router.message(AddCategory.description, F.text, OwnerOnly())
async def md_add_description(message: Message, state: FSMContext) -> None:
    await _add_step(message, state, "description", message.text.strip())


# ---------------- កែ ----------------

@router.callback_query(F.data.startswith("cat:edit:"), OwnerOnly())
async def cb_category_edit(callback: CallbackQuery, scope: Scope) -> None:
    category_id = target_id(callback)
    async with db_session() as session:
        category = await crud.get_category(session, category_id)
    if category is None or callback.message is None:
        await callback.answer("រកមិនឃើញ" if category is None else "", show_alert=category is None)
        return
    await callback.message.edit_text(
        f"✏️ កែ <b>{esc(category.name_kh)}</b> — ជ្រើសរើសចំណុច (<i>code កែមិនបានទេ</i>):",
        reply_markup=keyboards.category_fields(category),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:f:"), OwnerOnly())
async def cb_category_field(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    field, category_id = parts[2], int(parts[3])
    await state.set_state(EditCategory.value)
    await state.update_data(edit_cat_field=field, edit_cat=category_id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(EDIT_LABELS.get(field, "តម្លៃថ្មី:"))
    await callback.answer()


@router.message(EditCategory.value, F.text, OwnerOnly())
async def md_category_field(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    field = data["edit_cat_field"]
    category_id = data["edit_cat"]
    raw = message.text.strip()

    values: dict[str, object] = {}
    if field == "name_kh":
        if not raw:
            await message.answer("⛔ ឈ្មោះមិនអាចទទេ:")
            return
        values["name_kh"] = raw
    elif field == "icon":
        values["icon"] = raw[:4] or "📦"
    elif field == "prefix":
        values["prefix"] = "" if raw in ("-", "ទទេ") else raw.upper()[:5]
    elif field in ("name_en", "description"):
        values[field] = _optional(raw)
    else:
        await state.set_state(None)
        return

    async with db_session() as session:
        category = await crud.get_category(session, category_id)
        if category is None:
            await message.answer("⛔ រកមិនឃើញប្រភេទ")
            await state.set_state(None)
            return
        await crud.update_category(session, category_id, **values)
        counts = await crud.category_product_counts(session, owner_admin_id=scope.owner_id)
        fresh = await crud.get_category(session, category_id)
        card = category_card(fresh, counts.get(category_id, 0)) if fresh else "⛔ បាត់"
        markup = keyboards.category_actions(fresh, counts.get(category_id, 0), can_manage=scope.is_owner) if fresh else None
    await state.set_state(None)
    await message.answer(f"✅ បានរក្សាទុក\n{card}", reply_markup=markup)


# ---------------- លុប ----------------

@router.callback_query(F.data.startswith("cat:askdel:"), OwnerOnly())
async def cb_category_ask_delete(callback: CallbackQuery, scope: Scope) -> None:
    category_id = target_id(callback)
    async with db_session() as session:
        category = await crud.get_category(session, category_id)
    if category is None or callback.message is None:
        await callback.answer("រកមិនឃើញ" if category is None else "", show_alert=category is None)
        return
    await callback.message.edit_text(
        f"🗑 លុបប្រភេទ <b>{esc(category.name_kh)}</b> <code>&lt;{esc(category.code)}&gt;</code>?\n"
        "<i>បើមានផលិតផលកំពុងប្រើ → លុបមិនបានទេ (មិនប៉ះផលិតផល)។</i>",
        reply_markup=keyboards.confirm_action(f"លុបប្រភេទ #{category_id}", f"cat:del:{category_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:del:"), OwnerOnly())
async def cb_category_delete(callback: CallbackQuery, scope: Scope) -> None:
    category_id = target_id(callback)
    async with db_session() as session:
        result = await crud.delete_category(session, category_id)
    if result == "deleted":
        await callback.answer("បានលុបប្រភេទ")
    elif result == "blocked":
        await callback.answer("មានផលិតផលកំពុងប្រើប្រភេទនេះ — លុប/ផ្លាស់ផលិតផលជាមុនសិន", show_alert=True)
    else:
        await callback.answer("រកមិនឃើញ", show_alert=True)
    await show_manager(callback, scope)


# ---------------- /lowstock ----------------

@router.message(Command("lowstock"))
async def cmd_lowstock(message: Message, scope: Scope) -> None:
    async with db_session() as session:
        threshold = int(await crud.get_setting(session, "stock_alert_threshold") or 5)
        rows = await crud.low_stock_products(session, threshold, owner_admin_id=scope.owner_id)
    if not rows:
        await message.answer(f"✅ គ្មានផលិតផល Stock តិចជាង <b>{threshold}</b> ទេ")
        return
    body = f"⚠️ <b>Stock តិច</b> (<&gt;{threshold})\n" + "\n".join(
        f"· {esc(product.name)}"
        + (f" [<code>{esc(product.product_code)}</code>]" if product.product_code else "")
        + f" — សល់ <b>{count}</b>"
        for product, count in rows
    )
    await message.answer(body, reply_markup=keyboards.build([[("📦 ផលិតផល", "menu:products")]]))
