"""💳 QR Code ទូទាត់ — ABA / Bakong / Wing / ACLEDA រួមទាំងការបង្កើត PNG ស្វ័យប្រវត្តិ។"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, media, render
from config import QR_MEDIA_DIR
from database import crud, db_session
from helpers import esc

log = logging.getLogger("admin.qrcodes")

router = Router()


class AddQR(StatesGroup):
    name = State()
    provider = State()
    account_info = State()
    image = State()


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


async def show_list(callback: CallbackQuery) -> None:
    async with db_session() as session:
        qrs = await crud.list_qrcodes(session)
    if callback.message is None:
        await callback.answer()
        return
    header = "💳 <b>QR Code ទូទាត់</b>\n"
    if not qrs:
        header += "\n<i>មិនមាន QR ទេ — ចុច ➕ បន័ែម QR</i>"
    else:
        header += f"\n⭐ = QR លំនាំដើម · សរុប {len(qrs)}"
    await callback.message.edit_text(header, reply_markup=keyboards.qr_menu(qrs))
    await callback.answer()


async def show_qr(callback: CallbackQuery, qr_id: int, toast: str = "") -> None:
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id)
        if qr is None:
            await callback.answer("រកមិនឃើញ QR", show_alert=True)
            return
        card = render.qrcode_card(qr)
        markup = keyboards.qr_actions(qr)
        file_id, name = qr.image_file_id, qr.name
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(card, reply_markup=markup)
    if file_id:
        await media.send_photo_to_admin(callback.bot, callback.from_user.id, file_id, name)
    await callback.answer(toast)


# ---------------- បន័ែម ----------------

@router.callback_query(F.data == "menu:qr")
async def cb_qr_root(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await show_list(callback)


@router.callback_query(F.data == "qr:add")
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddQR.name)
    await state.update_data(qr_auto_gen=False)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "💳 <b>បន័ែម QR ថ្មី</b>\n\n📛 ឈ្មោះ (ឧ. ABA របស់ខ្ញុំ):"
    )
    await callback.answer()


@router.callback_query(F.data == "qr:newgen")
async def cb_add_autogen(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddQR.name)
    await state.update_data(qr_auto_gen=True)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "🧩 <b>បង្កើត QR ស្វ័យប្រវត្តិ</b> (PNG ពីអត្ថបទ Account Info)\n\n📛 ឈ្មោះ:"
    )
    await callback.answer()


@router.message(AddQR.name, F.text)
async def md_name(message: Message, state: FSMContext) -> None:
    await state.update_data(qr_name=message.text.strip())
    await state.set_state(AddQR.provider)
    await message.answer("🏦 <b>អ្នកផ្តល់សេវា</b> (ABA / Bakong / Wing / ACLEDA):")


@router.message(AddQR.provider, F.text)
async def md_provider(message: Message, state: FSMContext) -> None:
    await state.update_data(qr_provider=message.text.strip().upper())
    await state.set_state(AddQR.account_info)
    await message.answer(
        "🔖 <b>Account Info</b> — អត្ថបទដែល QR ត្រូវផ្ទុក (ឧ. payment URL ពី ABA ឬលេខបញ្ជី Bank)\n"
        "<i>អត្ថបទនេះត្រូវ render ជា QR PNG ពេលចុច 🧩 បង្កើតឡើងវិញ</i>:"
    )


@router.message(AddQR.account_info, F.text)
async def md_account_info(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    async with db_session() as session:
        qr = await crud.create_qrcode(
            session, name=data["qr_name"], provider=data["qr_provider"], account_info=message.text.strip()
        )
        qr_id, markup = qr.id, keyboards.qr_actions(qr)
    await state.update_data(qr_id=qr_id)

    if data.get("qr_auto_gen"):
        await generate_qr_image(message.bot, message.chat.id, qr_id)
        await state.set_state(None)
        await message.answer(f"✅ បង្កើត QR <code>#{qr_id}</code> រួច", reply_markup=markup)
        return

    await state.set_state(AddQR.image)
    await message.answer(
        f"✅ បង្កើត QR <code>#{qr_id}</code>\n\n"
        "🖼 ផ្ញើ<b>រូបភាព QR</b> របស់អ្នក ឬសរសេរ <code>gen</code> ដើម្បីបង្កើត PNG ពី Account Info\n"
        "(ឬ <code>skip</code> ទុកទទេ)",
        reply_markup=markup,
    )


async def generate_qr_image(bot, chat_id: int, qr_id: int) -> bool:
    """បង្កើត PNG ពី account_info → upload ទៅ Telegram → រក្សាទុក file_id + path។"""
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id)
        if qr is None or not qr.account_info:
            return False
        payload = qr.account_info
        name = qr.name
    destination = QR_MEDIA_DIR / f"qr{qr_id}.png"
    media.render_qr_png(payload, destination)
    try:
        file_id, path = await media.upload_local_photo(bot, chat_id, str(destination), f"🧾 {name}")
    except Exception as exc:  # noqa: BLE001 - កុំឱ្យ Panel ដួលពេល upload បរាជ័យ
        log.exception("បង្កើត QR PNG បរាជ័យ")
        return False
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id)
        if qr is None:
            return False
        qr.image_file_id = file_id
        qr.image_path = path
    return True


@router.message(AddQR.image, F.photo)
async def md_image(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    qr_id = data["qr_id"]
    file_id, path = await media.save_message_photo(message, QR_MEDIA_DIR, f"qr{qr_id}")
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id)
        if qr is None:
            await message.answer("⛔ រកមិនឃើញ QR")
            await state.set_state(None)
            return
        qr.image_file_id = file_id
        qr.image_path = path
        markup = keyboards.qr_actions(qr)
    await state.set_state(None)
    await message.answer("✅ បានរក្សាទុករូប QR", reply_markup=markup)


@router.message(AddQR.image, F.text)
async def md_image_command(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    qr_id = data["qr_id"]
    command = message.text.strip().lower()
    if command == "gen":
        ok = await generate_qr_image(message.bot, message.chat.id, qr_id)
        await state.set_state(None)
        async with db_session() as session:
            qr = await crud.get_qrcode(session, qr_id)
            markup = keyboards.qr_actions(qr) if qr is not None else None
        await message.answer("✅ បានបង្កើត QR PNG" if ok else "⛔ បង្កើតមិនបាន — Account Info ទទេ ឬ upload បរាជ័យ", reply_markup=markup)
        return
    if command in ("skip", "ទុក", "done"):
        await state.set_state(None)
        async with db_session() as session:
            qr = await crud.get_qrcode(session, qr_id)
            markup = keyboards.qr_actions(qr) if qr is not None else None
        await message.answer("⏭ រំលងរូបភាព (តាម <code>🔁 បង្កើតឡើងវិញ</code> ពេលក្រោយបាន)", reply_markup=markup)
        return
    await message.answer("ℹ️ ផ្ញើរូបភាព ឬសរសេរ <code>gen</code> / <code>skip</code>")


# ---------------- សកម្មភាព ----------------

@router.callback_query(F.data.startswith("qr:view:"))
async def cb_view(callback: CallbackQuery) -> None:
    await show_qr(callback, target_id(callback))


@router.callback_query(F.data.startswith("qr:default:"))
async def cb_default(callback: CallbackQuery) -> None:
    qr_id = target_id(callback)
    async with db_session() as session:
        await crud.set_default_qrcode(session, qr_id)
        qrs = await crud.list_qrcodes(session)
    if callback.message is not None:
        await callback.message.edit_text("⭐ បានកំណត់ QR លំនាំដើម", reply_markup=keyboards.qr_menu(qrs))
    await callback.answer("បានកំណត់ជា Default")


@router.callback_query(F.data.startswith("qr:regen:"))
async def cb_regen(callback: CallbackQuery) -> None:
    qr_id = target_id(callback)
    ok = await generate_qr_image(callback.bot, callback.from_user.id, qr_id)
    await show_qr(
        callback,
        qr_id,
        toast="បានបង្កើត QR PNG ឡើងវិញ" if ok else "⛔ Account Info ទទេ ឬ upload បរាជ័យ",
    )


@router.callback_query(F.data.startswith("qr:link:"))
async def cb_link(callback: CallbackQuery) -> None:
    qr_id = target_id(callback)
    async with db_session() as session:
        products, _total = await crud.list_products(session, page=1, per_page=20)
    rows = [[(f"#{item.id} {esc(item.name)}", f"qr:linkto:{qr_id}:{item.id}")] for item in products]
    rows.append([("⏭ ដកចេញ (គ្មានផលិតផល)", f"qr:linkto:{qr_id}:0"), ("⬅️ ត្រឡប់", f"qr:view:{qr_id}")])
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"📦 ភ្ជាប់ QR <code>#{qr_id}</code> ទៅផលិតផល៖", reply_markup=keyboards.build(rows)
    )
    await callback.answer()


async def _assign_product(callback: CallbackQuery, qr_id: int, product_id: int) -> None:
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id)
        if qr is None:
            await callback.answer("រកមិនឃើញ QR", show_alert=True)
            return
        qr.product_id = product_id or None
        product_name = ""
        if product_id:
            product = await crud.get_product(session, product_id)
            product_name = product.name if product else ""
    await callback.answer(f"បានភ្ជាប់ → {product_name}" if product_id else "បានដកការភ្ជាប់")
    if callback.message is not None and callback.data and callback.data.startswith("qr:linkto:"):
        await show_qr(callback, qr_id)


@router.callback_query(F.data.startswith("qr:linkto:"))
async def cb_linkto(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    await _assign_product(callback, int(parts[2]), int(parts[3]))


@router.callback_query(F.data.startswith("qr:assign:"))
async def cb_assign(callback: CallbackQuery) -> None:
    """ភ្ជាប់ QR ពីផ្នែក 📦 ផលិតផល (products.cb_qrpick)។"""
    parts = callback.data.split(":")
    await _assign_product(callback, int(parts[2]), int(parts[3]))


@router.callback_query(F.data.startswith("qr:askdel:"))
async def cb_ask_delete(callback: CallbackQuery) -> None:
    qr_id = target_id(callback)
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id)
    if qr is None or callback.message is None:
        await callback.answer("រកមិនឃើញ" if qr is None else "", show_alert=qr is None)
        return
    await callback.message.edit_text(
        f"🗑 លុប QR <b>{esc(qr.name)}</b> <code>#{qr.id}</code>?",
        reply_markup=keyboards.confirm_action(f"លុប QR #{qr_id}", f"qr:del:{qr_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qr:del:"))
async def cb_delete(callback: CallbackQuery) -> None:
    qr_id = target_id(callback)
    async with db_session() as session:
        await crud.delete_qrcode(session, qr_id)
    await show_list(callback)
