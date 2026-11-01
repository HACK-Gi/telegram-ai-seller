"""💳 QR Code ទូទាត់ — ABA / Bakong / Wing / ACLEDA **Upload រូបភាពពិតតែប៉ុណ្ណោះ**។

គ្មានការបង្កើត PNG ដោយស្វ័យប្រវត្តិទេ — អតិថិជនបង់ប្រាក់ចូលគណនីធនាគារពិត ដូច្នេះរូប QR
ត្រូវ Download ពី App ធនាគារ រួច Upload ចូល Panel (QR ដែល render ពីអត្ថបទអាចខុសលេខបញ្ជី
→ ប្រាក់ចូលកន្លែងខុស ជាកំហុសលើលុយពិត មិនមែនត្រឹមទិន្នន័យទេ)។
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, media, render
from admin_bot.scope import Scope
from config import QR_MEDIA_DIR
from database import crud, db_session
from database.models import QRCode
from helpers import esc

log = logging.getLogger("admin.qrcodes")

router = Router()
NOT_FOUND = "🚫 រកមិនឃើញ QR នេះក្នុងវិសាលភាពរបស់អ្នក"


class AddQR(StatesGroup):
    name = State()
    provider = State()
    account_info = State()
    image = State()


def target_id(callback: CallbackQuery) -> int:
    return int(callback.data.rsplit(":", 1)[-1])


async def guard_qr(callback: CallbackQuery, qr_id: int, scope: Scope) -> QRCode | None:
    """IDOR guard — QR របស់ admin ផ្សេង មិនអាច មើល/កំណត់ Default/ភ្ជាប់/លុប បានទេ។"""
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id, owner_admin_id=scope.owner_id)
    if qr is None:
        log.warning("IDOR: user=%s qr=%s ក្រៅវិសាលភាព", scope.admin_id, qr_id)
        await callback.answer(NOT_FOUND, show_alert=True)
    return qr


async def show_list(callback: CallbackQuery, scope: Scope) -> None:
    async with db_session() as session:
        qrs = await crud.list_qrcodes(session, owner_admin_id=scope.owner_id)
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


async def show_qr(callback: CallbackQuery, qr_id: int, scope: Scope, toast: str = "") -> None:
    qr = await guard_qr(callback, qr_id, scope)
    if qr is None:
        return
    async with db_session() as session:
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
async def cb_qr_root(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.set_state(None)
    await show_list(callback, scope)


@router.callback_query(F.data == "qr:add")
async def cb_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddQR.name)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "💳 <b>បន័ែម QR ថ្មី</b>\n\n📛 ឈ្មោះ (ឧ. ABA របស់ខ្ញុំ):"
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
        "🔖 <b>Account Info</b> — លេខគណនី/ឈ្មោះដែលអតិថិជនត្រូវប្រើ (ឧ. <code>012 345 678 · ABA · Sok Dara</code>)\n"
        "<i>វាជាអត្ថបទជំនួស ពេលរូបភាព QR មិនទាន់អាចប្រើបាន — មិនមែនជា source សម្រាប់ render PNG ទេ</i>:"
    )


@router.message(AddQR.account_info, F.text)
async def md_account_info(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    async with db_session() as session:
        qr = await crud.create_qrcode(
            session,
            name=data["qr_name"],
            provider=data["qr_provider"],
            account_info=message.text.strip(),
            owner_admin_id=scope.admin_id,
        )
        qr_id, markup = qr.id, keyboards.qr_actions(qr)
    await state.update_data(qr_id=qr_id)

    await state.set_state(AddQR.image)
    await message.answer(
        f"✅ បង្កើត QR <code>#{qr_id}</code>\n\n"
        "🖼 ផ្ញើ<b>រូបភាព QR</b> ដែលបង Download ពី App ធនាគារ (ABA/Bakong/Wing) មកក្នុង chat នេះ\n"
        "(ឬ <code>skip</code> ទុកទទេ — userbot នឹងមិនផ្ញើរូបណាទេ រហូតដល់បង Upload)",
        reply_markup=markup,
    )


@router.message(AddQR.image, F.photo)
async def md_image(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    qr_id = data["qr_id"]
    file_id, path = await media.save_message_photo(message, QR_MEDIA_DIR, f"qr{qr_id}")
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id, owner_admin_id=scope.owner_id)
        if qr is None:
            log.warning("IDOR: user=%s qr=%s image", scope.admin_id, qr_id)
            await message.answer("⛔ រកមិនឃើញ QR")
            await state.set_state(None)
            return
        qr.image_file_id = file_id
        qr.image_path = path
        markup = keyboards.qr_actions(qr)
    await state.set_state(None)
    await message.answer("✅ បានរក្សាទុករូប QR", reply_markup=markup)


@router.message(AddQR.image, F.text)
async def md_image_command(message: Message, state: FSMContext, scope: Scope) -> None:
    data = await state.get_data()
    qr_id = data["qr_id"]
    command = message.text.strip().lower()
    if command in ("skip", "ទុក", "done"):
        await state.set_state(None)
        async with db_session() as session:
            qr = await crud.get_qrcode(session, qr_id, owner_admin_id=scope.owner_id)
            markup = keyboards.qr_actions(qr) if qr is not None else None
            has_image = qr is not None and bool(qr.image_file_id)
        if has_image:
            await message.answer("⏭ ទុករូបភាពដើម", reply_markup=markup)
            return
        await message.answer(
            "⏭ រំលងរូបភាព — <b>userbot នឹងមិនផ្ញើ QR ឱ្យអតិថិជនទេ</b> រហូតដល់បង Upload រូបភាព"
            " (គណនីនេះបាញ់ជូនដំណឹងម្ចាស់ភ្លាមពេលអតិថិជនចង់ទិញ)",
            reply_markup=markup,
        )
        return
    await message.answer("ℹ️ សូម<b>ផ្ញើរូបភាព QR</b> ឬសរសេរ <code>skip</code> ដើម្បីទុកដើម")


# ---------------- សកម្មភាព ----------------

@router.callback_query(F.data.startswith("qr:view:"))
async def cb_view(callback: CallbackQuery, scope: Scope) -> None:
    await show_qr(callback, target_id(callback), scope)


@router.callback_query(F.data.startswith("qr:default:"))
async def cb_default(callback: CallbackQuery, scope: Scope) -> None:
    qr_id = target_id(callback)
    if await guard_qr(callback, qr_id, scope) is None:
        return
    async with db_session() as session:
        await crud.set_default_qrcode(session, qr_id, owner_admin_id=scope.owner_id)
        qrs = await crud.list_qrcodes(session, owner_admin_id=scope.owner_id)
    if callback.message is not None:
        await callback.message.edit_text("⭐ បានកំណត់ QR លំនាំដើម", reply_markup=keyboards.qr_menu(qrs))
    await callback.answer("បានកំណត់ជា Default")


@router.callback_query(F.data.startswith("qr:image:"))
async def cb_change_image(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    """រូប QR ខុស/បាត់ → ផ្ញើរូបថ្មីពី App ធនាគារ (គ្មាន render ខ្លួនឯងទេ)។"""
    qr_id = target_id(callback)
    if await guard_qr(callback, qr_id, scope) is None:
        return
    await state.update_data(qr_id=qr_id)
    await state.set_state(AddQR.image)
    if callback.message is not None:
        await callback.message.edit_text(
            f"🖼 ផ្ញើ<b>រូបភាព QR ថ្មី</b>សម្រាប់ <code>#{qr_id}</code> (រូបដែល Download ពី App ធនាគារ) ឬ <code>skip</code> ទុកដដែល"
        )
    await callback.answer()


@router.callback_query(F.data.startswith("qr:link:"))
async def cb_link(callback: CallbackQuery, scope: Scope) -> None:
    qr_id = target_id(callback)
    if await guard_qr(callback, qr_id, scope) is None:
        return
    async with db_session() as session:
        products, _total = await crud.list_products(session, page=1, per_page=20, owner_admin_id=scope.owner_id)
    rows = [[(f"#{item.id} {esc(item.name)}", f"qr:linkto:{qr_id}:{item.id}")] for item in products]
    rows.append([("⏭ ដកចេញ (គ្មានផលិតផល)", f"qr:linkto:{qr_id}:0"), ("⬅️ ត្រឡប់", f"qr:view:{qr_id}")])
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"📦 ភ្ជាប់ QR <code>#{qr_id}</code> ទៅផលិតផល៖", reply_markup=keyboards.build(rows)
    )
    await callback.answer()


async def _assign_product(callback: CallbackQuery, qr_id: int, product_id: int, scope: Scope) -> None:
    async with db_session() as session:
        qr = await crud.get_qrcode(session, qr_id, owner_admin_id=scope.owner_id)
        if qr is None:
            log.warning("IDOR: user=%s qr=%s assign", scope.admin_id, qr_id)
            await callback.answer(NOT_FOUND, show_alert=True)
            return
        product_name = ""
        if product_id:
            product = await crud.get_product(session, product_id, owner_admin_id=scope.owner_id)
            if product is None:
                log.warning("IDOR: user=%s product=%s via qr=%s", scope.admin_id, product_id, qr_id)
                await callback.answer("🔒 ផលិតផលនេះមិនមែនរបស់អ្នកទេ", show_alert=True)
                return
            product_name = product.name
        qr.product_id = product_id or None
    await callback.answer(f"បានភ្ជាប់ → {product_name}" if product_id else "បានដកការភ្ជាប់")
    if callback.message is not None and callback.data and callback.data.startswith("qr:linkto:"):
        await show_qr(callback, qr_id, scope)


@router.callback_query(F.data.startswith("qr:linkto:"))
async def cb_linkto(callback: CallbackQuery, scope: Scope) -> None:
    parts = callback.data.split(":")
    await _assign_product(callback, int(parts[2]), int(parts[3]), scope)


@router.callback_query(F.data.startswith("qr:assign:"))
async def cb_assign(callback: CallbackQuery, scope: Scope) -> None:
    """ភ្ជាប់ QR ពីផ្នែក 📦 ផលិតផល (products.cb_qrpick)។"""
    parts = callback.data.split(":")
    await _assign_product(callback, int(parts[2]), int(parts[3]), scope)


@router.callback_query(F.data.startswith("qr:askdel:"))
async def cb_ask_delete(callback: CallbackQuery, scope: Scope) -> None:
    qr_id = target_id(callback)
    qr = await guard_qr(callback, qr_id, scope)
    if qr is None or callback.message is None:
        return
    await callback.message.edit_text(
        f"🗑 លុប QR <b>{esc(qr.name)}</b> <code>#{qr.id}</code>?",
        reply_markup=keyboards.confirm_action(f"លុប QR #{qr_id}", f"qr:del:{qr_id}"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("qr:del:"))
async def cb_delete(callback: CallbackQuery, scope: Scope) -> None:
    qr_id = target_id(callback)
    if await guard_qr(callback, qr_id, scope) is None:
        return
    async with db_session() as session:
        await crud.delete_qrcode(session, qr_id, owner_admin_id=scope.owner_id)
    await show_list(callback, scope)
