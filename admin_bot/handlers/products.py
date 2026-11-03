"""📦 ផលិតផល — បន័ែម/កែ/លុប, Stock codes, រូបភាព, ប្រភេទ, Discount។"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, media, render
from admin_bot.scope import Scope
from config import PRODUCT_MEDIA_DIR
from database import crud, db_session
from database.models import Product
from helpers import esc, pagination_pages

router = Router()
log = logging.getLogger("admin.products")
PER_PAGE = 8

NOT_FOUND = "🚫 រកមិនឃើញផលិតផលនេះទេ"


class AddProduct(StatesGroup):
    """បន័ែមផលិតផលថ្មី (រូបភាពទុកក្នុង state រហូតដល់ done)។"""

    name = State()
    description = State()
    price = State()
    category = State()
    images = State()


class EditProduct(StatesGroup):
    value = State()


class UploadStock(StatesGroup):
    codes = State()


class ManageImages(StatesGroup):
    """កែរូបភាពផលិតផលដែលមានស្រាប់ — បង្គត់ទៅ DB ភ្លាមៗ។"""

    managing = State()


class SearchProducts(StatesGroup):
    term = State()


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


async def guard_product(callback: CallbackQuery, product_id: int, scope: Scope) -> Product | None:
    """IDOR guard — អានផលិតផលតាមវិសាលភាព <i>មុន</i> កែ/លុប។ បើមិនក្នុងវិសាលភាព = បដិសេធ។"""
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
    if product is None:
        log.warning("IDOR: user=%s prod=%s", scope.admin_id, product_id)
        await callback.answer(NOT_FOUND, show_alert=True)
    return product


async def show_list(
    event: Message | CallbackQuery, state: FSMContext, scope: Scope, page: int | None = None
) -> None:
    """បង្ហាញបញ្ជី។ page/search/category រក្សាទុកក្នុង FSM data ជំនួស callback_data។"""
    data = await state.get_data()
    current_page = page if page is not None else int(data.get("prod_page", 1))
    search = data.get("prod_search", "")
    category = data.get("prod_category", "")
    category_id = data.get("prod_category_id")
    await state.update_data(prod_page=current_page)

    async with db_session() as session:
        products, total = await crud.list_products(
            session,
            search=search,
            category=category,
            page=current_page,
            per_page=PER_PAGE,
            category_id=category_id,
            owner_admin_id=scope.owner_id,
        )
    pages = pagination_pages(total, PER_PAGE)
    current_page = min(current_page, pages)

    header = f"📦 <b>ផលិតផល</b> — រកឃើញ {total}"
    if search:
        header += f"\n🔍 <code>{esc(search)}</code>"
    if category:
        header += f"\n🏷 <code>{esc(category)}</code>"
    if not products:
        header += "\n\n<i>មិនមានផលិតផលទេ</i>\n<i>ហាងរបស់អ្នកទទេ — ចុច ➕ បន័ែមថ្មី ដើម្បីចាប់ផ្តើមលក់</i>"

    markup = keyboards.products_menu(products, current_page, pages)
    if isinstance(event, CallbackQuery):
        if event.message is None:
            await event.answer()
            return
        await event.message.edit_text(header, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(header, reply_markup=markup)


async def show_product(callback: CallbackQuery, product_id: int, scope: Scope) -> None:
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            log.warning("IDOR: user=%s prod=%s", scope.admin_id, product_id)
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        remaining = await crud.stock_remaining(session, product_id)
        card = render.product_card(product, remaining)
        file_ids = list(product.image_file_ids or [])
        name = product.name
        markup = keyboards.product_actions(product, remaining)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(card, reply_markup=markup)
    for index, file_id in enumerate(file_ids[:5], start=1):
        await media.send_photo_to_admin(callback.bot, callback.from_user.id, file_id, f"{name} · រូប {index}/{len(file_ids)}")
    await callback.answer()


# ---------------- បញ្ជី និង ការរំកិល ----------------

@router.callback_query(F.data == "menu:products")
async def cb_products_root(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await state.update_data(prod_page=1, prod_search="", prod_category="", prod_category_id=None)
    await show_list(callback, state, scope, page=1)


@router.callback_query(F.data == "prod:list:prev")
async def cb_products_prev(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    page = max(1, int((await state.get_data()).get("prod_page", 1)) - 1)
    await show_list(callback, state, scope, page=page)


@router.callback_query(F.data == "prod:list:next")
async def cb_products_next(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    page = int((await state.get_data()).get("prod_page", 1)) + 1
    await show_list(callback, state, scope, page=page)


@router.callback_query(F.data.startswith("prod:view:"))
async def cb_product_view(callback: CallbackQuery, scope: Scope) -> None:
    await show_product(callback, target_id(callback), scope)


@router.callback_query(F.data == "prod:categories")
async def cb_categories(callback: CallbackQuery, scope: Scope) -> None:
    async with db_session() as session:
        categories = await crud.list_all_categories(session, scope.owner_id)
    if not categories:
        await callback.answer("មិនមានប្រភេទនៅឡើយ", show_alert=True)
        return
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        "🏷 <b>ចម្រោះតាមប្រភេទ</b>\n<i>គ្រប់គ្រងប្រភេទ → 📦 ប្រភេទអីវ៉ាន់</i>",
        reply_markup=keyboards.categories_filter_menu(categories),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod:filter:"))
async def cb_filter(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    raw = callback.data.split("prod:filter:", 1)[1]
    if raw.isdigit():
        category_id = int(raw)
        async with db_session() as session:
            category = await crud.get_category(session, category_id, owner_admin_id=scope.owner_id)
        label = category.name_kh if category else ""
        await state.update_data(prod_category_id=category_id, prod_category="", prod_page=1)
    else:
        await state.update_data(prod_category_id=None, prod_category="", prod_page=1)
    await show_list(callback, state, scope, page=1)


@router.callback_query(F.data == "prod:search")
async def cb_search(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchProducts.term)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("🔍 សរសេរពាក្យដែលត្រូវស្វែងរក (ឬ /cancel):")
    await callback.answer()


@router.message(SearchProducts.term, F.text)
async def md_search(message: Message, state: FSMContext, scope: Scope) -> None:
    await state.update_data(prod_search=message.text.strip(), prod_page=1)
    await state.set_state(None)
    await show_list(message, state, scope, page=1)


# ---------------- បន័ែមផលិតផលថ្មី ----------------

@router.callback_query(F.data == "prod:add")
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddProduct.name)
    await state.update_data(new_images=[])
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("📛 សរសេរ<b>ឈ្មោះផលិតផល</b>:")
    await callback.answer()


@router.message(AddProduct.name, F.text)
async def md_add_name(message: Message, state: FSMContext) -> None:
    await state.update_data(new_name=message.text.strip())
    await state.set_state(AddProduct.description)
    await message.answer("📝 <b>ការពិពណ៌នា</b> (សរសេរ <code>-</code> បើមិនមាន):")


@router.message(AddProduct.description, F.text)
async def md_add_description(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    await state.update_data(new_description="" if raw in ("-", "ទទេ") else raw)
    await state.set_state(AddProduct.price)
    await message.answer("💰 <b>តម្លៃ</b> ជាដុល្លារ (ឧ. <code>5</code> ឬ <code>4.99</code>):")


@router.message(AddProduct.price, F.text)
async def md_add_price(message: Message, state: FSMContext) -> None:
    try:
        price = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("⛔ តម្លៃមិនត្រឹមត្រូវ — សរសេរជាលេខ ដូច <code>5</code>:")
        return
    if price < 0:
        await message.answer("⛔ តម្លៃមិនអាចអវិជ្ជមាន — សរសេរម្តងទៀត:")
        return
    await state.update_data(new_price=price)
    await state.set_state(AddProduct.category)
    await message.answer("🏷 <b>ប្រភេទ</b> (ឧ. ហ្គេម, សម្លៀកបំពាក់):")


@router.message(AddProduct.category, F.text)
async def md_add_category(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    async with db_session() as session:
        product = await crud.create_product(
            session,
            name=data["new_name"],
            description=data.get("new_description", ""),
            price=data["new_price"],
            category=message.text.strip(),
            owner_admin_id=scope.admin_id,
        )
        product_id = product.id
    await state.update_data(new_product_id=product_id, new_images=[])
    await state.set_state(AddProduct.images)
    await message.answer(
        f"✅ បង្កើត <code>#{product_id}</code> រួច\n\n"
        "🖼 <b>ផ្ញើរូបភាព</b> (រហូតដល់ ៥) រួចសរសេរ <code>done</code> ដើម្បីបញ្ចប់\n"
        "ឬសរសេរ <code>skip</code> បើមិនចង់បានរូប"
    )


@router.message(AddProduct.images, F.photo)
async def md_add_image(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    product_id = data["new_product_id"]
    images = list(data.get("new_images", []))
    if len(images) >= 5:
        await message.answer("⚠️ ពេញ ៥ រូបហើយ — សរសេរ <code>done</code> ដើម្បីបញ្ចប់")
        return
    file_id, path = await media.save_message_photo(message, PRODUCT_MEDIA_DIR, f"p{product_id}", len(images))
    images.append({"file_id": file_id, "path": path})
    await state.update_data(new_images=images)
    await message.answer(f"✅ បានទទួលរូប {len(images)}/5 — បន្តផ្ញើ ឬសរសេរ <code>done</code>:")


@router.message(AddProduct.images, F.text)
async def md_add_finish(message: Message, state: FSMContext, scope: Scope) -> None:
    if message.text.strip().lower() not in ("done", "skip", "រួច", "បញ្ចប់"):
        await message.answer("ℹ️ សរសេរ <code>done</code> ដើម្បីបញ្ចប់ ឬផ្ញើរូបភាពបន្ថែម")
        return
    data = await state.get_data()
    images = data.get("new_images", [])
    async with db_session() as session:
        product = await crud.get_product(session, data["new_product_id"], owner_admin_id=scope.owner_id)
        if product is None:
            await message.answer("⛔ រកមិនឃើញផលិតផល — សាកល្បងចាប់ផ្តើមម្តងទៀត")
            await state.clear()
            return
        product.image_file_ids = [item["file_id"] for item in images]
        product.image_paths = [item["path"] for item in images]
        name, product_id = product.name, product.id
        remaining = await crud.stock_remaining(session, product_id)
        markup = keyboards.product_actions(product, remaining)
    await state.set_state(None)
    await state.update_data(new_product_id=None, new_images=None)
    await message.answer(f"✅ បានរក្សាទុក <b>{esc(name)}</b> <code>#{product_id}</code>", reply_markup=markup)


# ---------------- កែតម្លៃ ----------------

FIELD_LABELS = {
    "name": "📛 ឈ្មោះថ្មី:",
    "desc": "📝 ការពិពណ៌នាថ្មី (<code>-</code> ដើម្បីសម្អាត):",
    "price": "💰 តម្លៃថ្មី ជាដុល្លារ:",
    "cat": "🏷 ប្រភេទថ្មី:",
    "disc": "💸 Discount ជា % (0-100):",
}

FIELD_ATTRS = {"name": "name", "desc": "description", "price": "price", "cat": "category", "disc": "discount_percent"}


@router.callback_query(F.data.startswith("prod:edit:"))
async def cb_edit(callback: CallbackQuery, scope: Scope) -> None:
    product_id = target_id(callback)
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
    if product is None or callback.message is None:
        await callback.answer("រកមិនឃើញ" if product is None else "", show_alert=product is None)
        return
    await callback.message.edit_text(
        f"✏️ កែ <b>{esc(product.name)}</b> — ជ្រើសរើសចំណុច:", reply_markup=keyboards.product_fields(product)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod:f:"))
async def cb_edit_field(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    parts = callback.data.split(":")
    field, product_id = parts[2], int(parts[3])
    if await guard_product(callback, product_id, scope) is None:
        return
    await state.set_state(EditProduct.value)
    await state.update_data(edit_field=field, edit_product=product_id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(FIELD_LABELS.get(field, "តម្លៃថ្មី:"))
    await callback.answer()


@router.message(EditProduct.value, F.text)
async def md_edit_field(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    field = data["edit_field"]
    product_id = data["edit_product"]
    raw = message.text.strip()
    value: object = raw

    if field == "price":
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            await message.answer("⛔ សរសេរជាលេខ ដូច <code>5</code> ឬ <code>4.99</code>:")
            return
        if float(value) < 0:
            await message.answer("⛔ តម្លៃមិនអាចអវិជ្ជមាន:")
            return
    elif field == "disc":
        try:
            number = int(float(raw.replace("%", "").strip()))
        except ValueError:
            await message.answer("⛔ សរសេរជាលេខ 0-100:")
            return
        value = max(0, min(100, number))
    elif field == "desc" and raw in ("-", "ទទេ"):
        value = ""
    elif field == "name" and not raw:
        await message.answer("⛔ ឈ្មោះមិនអាចទទេ:")
        return

    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await message.answer("⛔ រកមិនឃើញផលិតផល")
            await state.set_state(None)
            return
        setattr(product, FIELD_ATTRS[field], value)
        name = product.name
        remaining = await crud.stock_remaining(session, product_id)
        markup = keyboards.product_actions(product, remaining)
    await state.set_state(None)
    await message.answer(f"✅ បានរក្សាទុក <b>{esc(name)}</b>", reply_markup=markup)


# ---------------- Stock ----------------

@router.callback_query(F.data.startswith("prod:stock:"))
async def cb_stock(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    tail = callback.data.split(":", 2)[2] if callback.data.count(":") >= 2 else ""
    if ":" in tail:  # "prod:stock:12:auto"
        rest, mode = tail.split(":", 1)
        if mode in ("auto", "manual") and rest.isdigit():
            await _stock_input_with_id(callback, state, int(rest), mode, scope)
            return
    product_id = target_id(callback)
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await callback.answer("រកមិនឃើញ", show_alert=True)
            return
        remaining = await crud.stock_remaining(session, product_id)
        sold = await crud.sold_stock_count(session, product_id)
        available = await crud.available_stock(session, product_id)
        name = product.name
        code = product.product_code
        markup = keyboards.stock_mode_menu(product)
    await state.update_data(stock_product=product_id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"🔢 <b>{esc(name)}</b>"
        + (f" <code>{esc(code)}</code>" if code else "")
        + f" — សល់ <b>{remaining}</b> · 🟢អនុញ្ញាតលក់ <b>{available}</b> · បានលក់ <b>{sold}</b>\n\n"
        "📥 ជ្រើសរបៀបបញ្ចូល Stock:",
        reply_markup=markup,
    )
    await callback.answer()


async def _stock_input_with_id(
    callback: CallbackQuery, state: FSMContext, product_id: int, mode: str, scope: Scope
) -> None:
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await callback.answer("រកមិនឃើញ", show_alert=True)
            return
        code = product.product_code or f"P{product.id}"
        remaining = await crud.stock_remaining(session, product_id)
        name = product.name
    await state.set_state(UploadStock.codes)
    await state.update_data(stock_product=product_id, stock_mode=mode)
    if callback.message is None:
        await callback.answer()
        return
    if mode == "auto":
        hint = (
            f"🤖 <b>{esc(name)}</b> <code>{esc(code)}</code> — ផ្ញើ<b>ខ្លឹមសារ</b> បន្ទាត់មួយម្សិល "
            "(username|password ឬ code ពិត) រួច Code នឹងស្វ័យប្រវត្តិ <code>{esc(code)}-S001...</code>\n"
            f"📊 សល់ <b>{remaining}</b>\n\n<i>បន្ទាត់ទទេ/ស្ទួន → រំលង</i>"
        )
    else:
        hint = (
            f"✍️ <b>{esc(name)}</b> — ផ្ញើ <b>គ្រាប់ Code</b> បន្ទាត់មួយម្សិល (bulk បាន)\n"
            f"📊 សល់ <b>{remaining}</b>\n\n"
            "• <code>list</code> — មើល Code ដែលសល់\n"
            "• <code>clear</code> — លុប Code ដែលមិនទាន់លក់ទាំងអស់\n"
            "• /cancel — ចេញ"
        )
    await callback.message.edit_text(hint)
    await callback.answer()


async def _stock_input(callback: CallbackQuery, state: FSMContext, mode: str, scope: Scope) -> None:
    await _stock_input_with_id(callback, state, target_id(callback), mode, scope)


@router.callback_query(F.data.startswith("stock:auto:"))
async def cb_stock_auto(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await _stock_input(callback, state, "auto", scope)


@router.callback_query(F.data.startswith("stock:manual:"))
async def cb_stock_manual(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await _stock_input(callback, state, "manual", scope)


@router.message(UploadStock.codes, F.text)
async def md_stock(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    product_id = data["stock_product"]
    mode = data.get("stock_mode", "manual")
    raw = message.text.strip()
    command = raw.lower()

    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await message.answer("⛔ រកមិនឃើញផលិតផល")
            await state.set_state(None)
            return

        if command == "list":
            codes = await crud.list_stock(session, product_id, only_available=True, limit=25)
            body = "\n".join(
                f"<code>{esc(item.code)}</code>"
                + (f" — {esc(item.content)}" if item.content else "")
                + (f" 🟡({item.status})" if item.status != "available" else "")
                for item in codes
            ) or "<i>អស់</i>"
            await message.answer(
                f"🔢 Code ដែលសល់ (បង្ហាញ ២៥ ខ្ទាត់):\n{body}",
                reply_markup=keyboards.product_actions(product, await crud.stock_remaining(session, product_id)),
            )
            await state.set_state(None)
            return

        if command == "clear":
            removed = await crud.clear_unsold_stock(session, product_id)
            remaining = await crud.stock_remaining(session, product_id)
            await state.set_state(None)
            await message.answer(
                f"🧹 បានលុប <b>{removed}</b> Code\n📊 សល់ <b>{remaining}</b>",
                reply_markup=keyboards.product_actions(product, remaining),
            )
            return

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if mode == "auto":
            created = await crud.add_stock_lines(session, product_id, lines)
            added, samples = len(created), [item.code for item in created[:3]]
        else:
            added = await crud.add_stock(session, product_id, lines)
            samples = []
        remaining = await crud.stock_remaining(session, product_id)
        available = await crud.available_stock(session, product_id)
        name = product.name
        markup = keyboards.product_actions(product, remaining)
    await state.set_state(None)
    detail = f" · ឧទាហរណ៍ <code>{esc(', '.join(samples))}</code>" if samples else ""
    await message.answer(
        f"✅ បានបន័ែម <b>{added}</b> Code ថ្មីសម្រាប់ <b>{esc(name)}</b>{detail}\n"
        f"📊 សល់សរុប <b>{remaining}</b> · 🟢លក់បាន <b>{available}</b>",
        reply_markup=markup,
    )


# ---------------- រូបភាព (ផលិតផលមានស្រាប់) ----------------

@router.callback_query(F.data.startswith("prod:images:"))
async def cb_images(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    product_id = target_id(callback)
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await callback.answer("រកមិនឃើញ", show_alert=True)
            return
        count = len(product.image_file_ids or [])
        name = product.name
        remaining = await crud.stock_remaining(session, product_id)
        markup = keyboards.product_actions(product, remaining)
    await state.set_state(ManageImages.managing)
    await state.update_data(image_product=product_id)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"🖼 <b>{esc(name)}</b> — មាន {count}/5 រូប\n\n"
        "• ផ្ញើរូបភាព → បន័ែមភ្លាមៗ\n"
        "• <code>clear</code> → លុបរូបទាំងអស់\n"
        "• <code>done</code> → ចេញ",
        reply_markup=markup,
    )
    await callback.answer()


@router.message(ManageImages.managing, F.photo)
async def md_image_append(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    product_id = data["image_product"]
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await message.answer("⛔ រកមិនឃើញ")
            await state.set_state(None)
            return
        file_ids = list(product.image_file_ids or [])
        paths = list(product.image_paths or [])
        if len(file_ids) >= 5:
            await message.answer("⚠️ ពេញ ៥ រូបហើយ — សរសេរ <code>clear</code> ដើម្បីចាប់ផ្តើមថ្មី")
            return
        file_id, path = await media.save_message_photo(message, PRODUCT_MEDIA_DIR, f"p{product_id}", len(file_ids))
        file_ids.append(file_id)
        paths.append(path)
        product.image_file_ids = file_ids
        product.image_paths = paths
        name = product.name
        count = len(file_ids)
    await message.answer(f"✅ បានបន័ែម — <b>{esc(name)}</b> មាន {count}/5 រូប")


@router.message(ManageImages.managing, F.text)
async def md_images_command(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    product_id = data["image_product"]
    command = message.text.strip().lower()
    if command not in ("clear", "done", "រួច"):
        await message.answer("ℹ️ ប្រើ <code>clear</code> ឬ <code>done</code> ឬផ្ញើរូបភាព")
        return
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await message.answer("⛔ រកមិនឃើញ")
            await state.set_state(None)
            return
        if command == "clear":
            product.image_file_ids = []
            product.image_paths = []
            await message.answer(f"🧹 បានលុបរូបភាពទាំងអស់របស់ <b>{esc(product.name)}</b>")
        else:
            remaining = await crud.stock_remaining(session, product_id)
            await message.answer(
                "✅ ចេញពីការកែរូបភាព", reply_markup=keyboards.product_actions(product, remaining)
            )
    await state.set_state(None)


# ---------------- បើក/បិទ និង លុប ----------------

@router.callback_query(F.data.startswith("prod:toggle:"))
async def cb_toggle(callback: CallbackQuery, scope: Scope) -> None:
    product_id = target_id(callback)
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
        if product is None:
            await callback.answer("រកមិនឃើញ", show_alert=True)
            return
        product.is_active = not product.is_active
        active = product.is_active
        remaining = await crud.stock_remaining(session, product_id)
        card = render.product_card(product, remaining)
        markup = keyboards.product_actions(product, remaining)
    if callback.message is not None:
        await callback.message.edit_text(card, reply_markup=markup)
    await callback.answer("បានបើកផលិតផល" if active else "បានបិទផលិតផល")


@router.callback_query(F.data.startswith("prod:qrpick:"))
async def cb_qrpick(callback: CallbackQuery, scope: Scope) -> None:
    product_id = target_id(callback)
    async with db_session() as session:
        qrs = await crud.list_qrcodes(session, owner_admin_id=scope.owner_id, account_ids=scope.ids)
    if not qrs:
        await callback.answer("មិនមាន QR ទេ — បន័ែមក្នុង 💳 QR Code", show_alert=True)
        return
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"💳 ជ្រើសរើស QR សម្រាប់ផលិតផល <code>#{product_id}</code>:",
        reply_markup=keyboards.build(
            [[(f"{esc(qr.name)} [{esc(qr.provider)}]", f"qr:assign:{qr.id}:{product_id}")] for qr in qrs]
            + [[("⏭ ដក QR ចេញ", f"qr:assign:0:{product_id}"), ("⬅️ ត្រឡប់", f"prod:view:{product_id}")]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod:askdel:"))
async def cb_ask_delete(callback: CallbackQuery, scope: Scope) -> None:
    product_id = target_id(callback)
    async with db_session() as session:
        product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
    if product is None or callback.message is None:
        await callback.answer("រកមិនឃើញ" if product is None else "", show_alert=product is None)
        return
    await callback.message.edit_text(
        f"🗑 លុប <b>{esc(product.name)}</b> <code>#{product.id}</code> និង Stock ទាំងអស់?\n"
        "<i>Order ដែលបានប្រគល់រួច នៅតែក្នុងប្រវត្តិ។</i>",
        reply_markup=keyboards.confirm_action(f"លុប #{product_id}", f"prod:del:{product_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("prod:del:"))
async def cb_delete(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    product_id = target_id(callback)
    if await guard_product(callback, product_id, scope) is None:
        return
    async with db_session() as session:
        await crud.delete_product(session, product_id)
    await state.update_data(prod_page=1)
    await show_list(callback, state, scope, page=1)


# ---------------- ពាក្យសັ່ងខ្លី (/products /addproduct /addstock) ----------------

@router.message(Command("products"))
async def cmd_products(message: Message, state: FSMContext, scope: Scope) -> None:
    await state.update_data(prod_page=1, prod_search="", prod_category="", prod_category_id=None)
    await show_list(message, state, scope, page=1)


@router.message(Command("addproduct"))
async def cmd_add_product(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddProduct.name)
    await state.update_data(new_images=[])
    await message.answer("📛 សរសេរ<b>ឈ្មោះផលិតផល</b>:")


@router.message(Command("addstock"))
async def cmd_add_stock(message: Message, state: FSMContext, command: CommandObject, scope: Scope) -> None:
    arg = (command.args or "").strip()
    if not arg:
        await message.answer("📥 ប្រើ: <code>/addstock GAME-001</code> ឬ <code>/addstock 1</code>")
        return
    async with db_session() as session:
        product = (
            await crud.get_product_by_code(session, arg, owner_admin_id=scope.owner_id)
            if not arg.isdigit()
            else await crud.get_product(session, int(arg), owner_admin_id=scope.owner_id)
        )
        if product is None:
            await message.answer(f"⛔ រកមិនឃើញផលិតផល <code>{esc(arg)}</code>")
            return
        product_id = product.id
    await state.set_state(UploadStock.codes)
    await state.update_data(stock_product=product_id, stock_mode="auto")
    await message.answer(
        f"🤖 <b>{esc(product.name)}</b> <code>{esc(product.product_code or '')}</code> — "
        "ផ្ញើ<b>ខ្លឹមសារ</b> បន្ទាត់មួយម្សិល → Code ស្វ័យប្រវត្តិ <code>...-S001</code>\n"
        "<i>បើចង់គ្រាប់ code ដោយខ្លួន → 📦 ផលិតផល → 🔢 Stock → ✍️</i>"
    )
