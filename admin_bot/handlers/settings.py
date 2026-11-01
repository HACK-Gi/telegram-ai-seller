"""⚙️ ការកំណត់ និង 🔐 Admins — គត់ Owner ប៉ុណ្ណោះដែលកែបាន (Admin ជំនួយមើលបានតែប៉ុណ្ណោះ)។"""
from __future__ import annotations

import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards
from admin_bot.owner_gate import OwnerOnly
from ai_engine import get_engine
from config import BACKUP_DIR, settings
from database import crud, db_session
from helpers import esc, in_working_hours, parse_hours
from services import backup as backup_service

log = logging.getLogger("admin.settings")
router = Router()

OWNER_ONLY = "🔐 គត់ Owner ប៉ុណ្ណោះដែលអាចប្តូរផ្នែកនេះ"


class EditSetting(StatesGroup):
    hours = State()
    off_reply = State()
    threshold = State()
    language = State()


class AddAdmin(StatesGroup):
    details = State()


class RemoveAdmin(StatesGroup):
    target = State()


class RestoreDb(StatesGroup):
    document = State()


def is_owner(event: CallbackQuery | Message) -> bool:
    return event.from_user.id == settings.owner_id


async def overview(callback: CallbackQuery) -> None:
    async with db_session() as session:
        values = await crud.all_settings(session)
        counts = await crud.order_counts_by_status(session)
    hours = values.get("working_hours", "")
    open_now = in_working_hours(hours)
    pending_slips = counts.get("awaiting_verify", 0)
    text = (
        "⚙️ <b>ការកំណត់បច្ចុប្បន្ន</b>\n\n"
        f"🕒 Working hours: <code>{esc(hours)}</code> — {'🟢 កំពុងបើក' if open_now else '⚪ ក្រៅម៉ោង'}\n"
        f"💬 សារក្រៅម៉ោង: {esc(values.get('off_hours_reply', ''))[:80]}\n"
        f"🤖 AI global: <b>{values.get('ai_enabled')}</b>\n"
        f"📱 Userbot: <b>{values.get('userbot_enabled')}</b> (ជំហានទី ២)\n"
        f"📉 Stock alert threshold: <b>{values.get('stock_alert_threshold')}</b>\n"
        f"🌐 ភាសា: <b>{values.get('language')}</b>\n"
        f"🧠 AI backend: <b>{esc(get_engine().name)}</b>\n"
        f"🔑 Fernet key: <b>{'✅ កំណត់រួច' if settings.fernet_key else '❌ មិនទាន់ (ត្រូវការសម្រាប់ ជំហានទី ២)'}</b>\n"
        f"🛒 Order រង់ចាំផ្ទៀងផ្ទាត់: <b>{pending_slips}</b>\n\n"
        + ("👤 <b>Owner</b> — កែបានគ្រប់ផ្នែក" if is_owner(callback) else "👮 <b>Admin ជំនួយ</b> — មើលបានតែប៉ុណ្ណោះ")
    )
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(text, reply_markup=keyboards.settings_menu(is_owner(callback)))
    await callback.answer()


@router.callback_query(F.data == "menu:settings", OwnerOnly())
async def cb_settings_root(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await overview(callback)


@router.callback_query(F.data == "set:hours", OwnerOnly())
async def cb_hours(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    await state.set_state(EditSetting.hours)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("🕒 កំណត់ម៉ោងធ្វើការ ទ្រង់ទ្រាយ <code>HH:MM-HH:MM</code> (ឧ. <code>08:00-23:00</code>)\n<i>សរសេរ <code>24h</code> ដើម្បីបើក ២៤ ម៉ោង:</i>")
    await callback.answer()


@router.message(EditSetting.hours, F.text, OwnerOnly())
async def md_hours(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if raw.lower() not in ("24h", "24") and parse_hours(raw) is None:
        await message.answer("⛔ ទ្រង់ទ្រាយមិនត្រឹមត្រូវ — សាកល្បង <code>08:00-23:00</code> ឬ <code>24h</code>:")
        return
    value = "00:00-24:00" if raw.lower() in ("24h", "24") else raw
    async with db_session() as session:
        await crud.set_setting(session, "working_hours", value)
    await state.set_state(None)
    await message.answer(f"✅ ម៉ោងធ្វើការ: <code>{value}</code>", reply_markup=keyboards.settings_menu(True))


@router.callback_query(F.data == "set:offreply", OwnerOnly())
async def cb_off_reply(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    await state.set_state(EditSetting.off_reply)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("💬 សរសេរសារដែល Userbot ផ្ញើ ពេលក្រៅម៉ោងធ្វើការ:")
    await callback.answer()


@router.message(EditSetting.off_reply, F.text, OwnerOnly())
async def md_off_reply(message: Message, state: FSMContext) -> None:
    async with db_session() as session:
        await crud.set_setting(session, "off_hours_reply", message.text.strip())
    await state.set_state(None)
    await message.answer("✅ បានរក្សាទុកសារក្រៅម៉ោង", reply_markup=keyboards.settings_menu(True))


@router.callback_query(F.data == "set:ai", OwnerOnly())
async def cb_toggle_ai(callback: CallbackQuery) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    async with db_session() as session:
        current = await crud.get_setting(session, "ai_enabled", "on")
        new = "off" if current == "on" else "on"
        await crud.set_setting(session, "ai_enabled", new)
    await overview(callback)
    await callback.answer(f"🤖 AI global → {new}")


@router.callback_query(F.data == "set:userbot", OwnerOnly())
async def cb_toggle_userbot(callback: CallbackQuery) -> None:
    """flag តែមួយដែល Userbot (ជំហានទី ២) នឹងអាន = ដូច /stopbot និង /startbot។"""
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    async with db_session() as session:
        current = await crud.get_setting(session, "userbot_enabled", "on")
        new = "off" if current == "on" else "on"
        await crud.set_setting(session, "userbot_enabled", new)
    await overview(callback)
    await callback.answer(f"📱 Userbot → {new}")


@router.callback_query(F.data == "set:threshold", OwnerOnly())
async def cb_threshold(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    await state.set_state(EditSetting.threshold)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("📉 ចំនួន Stock ទាបបំផុតដែលត្រូវជូនដំណឹង (លេខ ឧ. <code>5</code>):")
    await callback.answer()


@router.message(EditSetting.threshold, F.text, OwnerOnly())
async def md_threshold(message: Message, state: FSMContext) -> None:
    try:
        value = max(0, int(float(message.text.strip())))
    except ValueError:
        await message.answer("⛔ ត្រូវជាលេខ:")
        return
    async with db_session() as session:
        await crud.set_setting(session, "stock_alert_threshold", str(value))
        await crud.set_json_setting(session, "low_stock_alerted", {})
    await state.set_state(None)
    await message.answer(
        f"✅ Threshold = {value} (ជូនដំណឹងពេលសល់តិចជាងនេះ)",
        reply_markup=keyboards.settings_menu(True),
    )


@router.callback_query(F.data == "set:lang", OwnerOnly())
async def cb_lang(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        "🌐 ភាសា Panel (Userbot នឹងប្រើវាជាមួយ AI ក្នុង ជំហានទី ២)",
        reply_markup=keyboards.build(
            [[("🇰🇭 ខ្មែរ", "set:lang:km"), ("🇬🇧 English", "set:lang:en")], [keyboards.BACK_MAIN]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set:lang:"), OwnerOnly())
async def cb_lang_pick(callback: CallbackQuery) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    language = callback.data.split(":")[-1]
    async with db_session() as session:
        await crud.set_setting(session, "language", language)
    await overview(callback)
    await callback.answer(f"🌐 {language}")


# ---------------- Backup / Restore ----------------

@router.callback_query(F.data == "set:backup", OwnerOnly())
async def cb_backup(callback: CallbackQuery) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    await callback.answer("💾 កំពុងបង្កើត backup...")
    try:
        path = await backup_service.create_backup("manual")
    except OSError as exc:
        log.error("backup បរាជ័យ: %s", exc)
        if callback.message is not None:
            await callback.message.answer(f"⛔ Backup បរាជ័យ: {esc(exc)}")
        return
    try:
        await backup_service.send_backup(callback.bot, callback.from_user.id, path)
        if callback.message is not None:
            await callback.message.answer(f"✅ បង្កើត <code>{esc(path.name)}</code> រួច")
    except Exception:  # noqa: BLE001 - បង្ហាញសារទៅ owner ជំនួសឱ្យ Panel ដួល
        log.exception("ផ្ញើ backup បរាជ័យ")
        if callback.message is not None:
            await callback.message.answer(f"⚠️ បានបង្កើត <code>{esc(path.name)}</code> ប៉ុន្តែផ្ញើទៅ Telegram មិនបាន")


@router.callback_query(F.data == "set:restore", OwnerOnly())
async def cb_restore(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    await state.set_state(RestoreDb.document)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "📥 <b>Restore Database</b>\n\n"
        "១. ផ្ញើឯកសារ <code>.db</code> (backup ដែលបានទាញយកពីមុន)\n"
        "២. យើងនឹងត្រួតពិនិត្យ រួចសួរម្តងទៀតមុនជំនួស\n"
        "៣. DB បច្ចុប្បន្នត្រូវបានសន្ចីទុកជា backup ដោយស្វ័យប្រវត្តិ\n\n"
        "ចុច /cancel ដើម្បីបោះបង់"
    )
    await callback.answer()


@router.message(RestoreDb.document, F.document, OwnerOnly())
async def md_restore_document(message: Message, state: FSMContext) -> None:
    pending = BACKUP_DIR / "pending_restore.db"
    await message.bot.download(message.document.file_id, destination=pending)
    reason = backup_service.validate_sqlite(pending)
    if reason:
        pending.unlink(missing_ok=True)
        await state.set_state(None)
        await message.answer(f"⛔ បដិសេធសម្រាប់ restore: {esc(reason)}")
        return
    await state.update_data(restore_path=str(pending))
    await message.answer(
        f"✅ ឯកសារត្រឹមត្រូវ ({pending.stat().st_size // 1024} KB)\n\n"
        "⚠️ ជំនួស DB ទាំងមូល (ផលិតផល, Order, អតិថិជន, Prompt, គណនី) ដោយឯកសារនេះ?\n"
        "<i>សកម្មភាពនេះមិនអាចត្រឡប់ក្រោយបានទេ — ប៉ុន្តែ DB ចាស់ត្រូវបានសន្ចីទុក។</i>",
        reply_markup=keyboards.confirm_action("ជំនួស DB", "set:restore:apply"),
    )


@router.callback_query(F.data == "set:restore:apply", OwnerOnly())
async def cb_restore_apply(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    data = await state.get_data()
    pending = data.get("restore_path")
    if not pending:
        await callback.answer("រំលងអស់ពេល — សូមចាប់ផ្តើមម្តងទៀត", show_alert=True)
        return
    try:
        safety = await backup_service.apply_restore(Path(pending))
    except (OSError, ValueError) as exc:
        log.error("restore បរាជ័យ: %s", exc)
        await state.set_state(None)
        if callback.message is not None:
            await callback.message.edit_text(f"⛔ Restore បរាជ័យ: {esc(exc)}")
        return
    await state.set_state(None)
    if callback.message is None:
        await callback.answer("restore រួចរាល់")
        return
    await callback.message.edit_text(
        "✅ <b>បាន Restore DB</b>\n"
        f"🛟 DB ចាស់សន្ចីនៅ <code>{esc(safety.name)}</code>\n\n"
        "🔁 សូមសរសេរ <code>/start</code> ដើម្បីឃើញទិន្នន័យថ្មី "
        "(និងស្ទុក Panel ឡើងវិញ)។ បើដំណើរការ Userbot សូម /stopbot រួច /startbot។"
    )
    await callback.answer("restore រួចរាល់")


# ---------------- Admins ----------------

@router.callback_query(F.data == "menu:admins", OwnerOnly())
async def cb_admins_root(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    async with db_session() as session:
        admins = await crud.list_admins(session)
    if callback.message is None:
        await callback.answer()
        return
    body = f"🔐 <b>Admins</b>\n\n👑 Owner: <code>{settings.owner_id}</code> (មិនអាចលុប)\n"
    body += "\n".join(f"👮 <code>{item.telegram_id}</code> — {esc(item.name or '—')}" for item in admins)
    if not admins:
        body += "\n<i>មិនមាន Admin ជំនួយទេ</i>"
    await callback.message.edit_text(body, reply_markup=keyboards.admins_menu(admins))
    await callback.answer()


@router.callback_query(F.data == "adm:add", OwnerOnly())
async def cb_admin_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    await state.set_state(AddAdmin.details)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("➕ ផ្ញើ <code>TelegramID ឈ្មោះ</code> (ឧ. <code>987654321 Sokha</code>):")
    await callback.answer()


@router.message(AddAdmin.details, F.text, OwnerOnly())
async def md_admin_add(message: Message, state: FSMContext) -> None:
    parts = message.text.split(maxsplit=1)
    try:
        telegram_id = int(parts[0])
    except (ValueError, IndexError):
        await message.answer("⛔ ទ្រង់ទ្រាយ: <code>ID ឈ្មោះ</code>")
        return
    name = parts[1].strip() if len(parts) > 1 else ""
    async with db_session() as session:
        if telegram_id == settings.owner_id:
            await state.set_state(None)
            await message.answer("ℹ️ ID នេះជា Owner ហើយ — មិនចាំបាច់បន្ថែម")
            return
        added = await crud.add_admin(session, telegram_id, name)
        admins = await crud.list_admins(session)
    await state.set_state(None)
    await message.answer(
        f"{'✅ បានបន័ែម' if added else '⚠️ Admin នេះមានស្រាប់'} <code>{telegram_id}</code> {esc(name)}\n"
        "⚠️ Admin ជំនួយមិនអាចកែ Settings, Admins ឬ Restore បានទេ",
        reply_markup=keyboards.admins_menu(admins),
    )


@router.callback_query(F.data == "adm:remove", OwnerOnly())
async def cb_admin_remove(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_owner(callback):
        await callback.answer(OWNER_ONLY, show_alert=True)
        return
    await state.set_state(RemoveAdmin.target)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer("🗑 ផ្ញើ <code>TelegramID</code> ដែលត្រូវលុបចេញពី Admin:")
    await callback.answer()


@router.message(RemoveAdmin.target, F.text, OwnerOnly())
async def md_admin_remove(message: Message, state: FSMContext) -> None:
    try:
        telegram_id = int(message.text.split()[0])
    except (ValueError, IndexError):
        await message.answer("⛔ ត្រូវជាលេខ ID:")
        return
    if telegram_id == settings.owner_id:
        await message.answer("⛔ មិនអាចលុប Owner បានទេ")
        await state.set_state(None)
        return
    async with db_session() as session:
        await crud.remove_admin(session, telegram_id)
        admins = await crud.list_admins(session)
    await state.set_state(None)
    await message.answer(f"✅ បានលុប <code>{telegram_id}</code>", reply_markup=keyboards.admins_menu(admins))


@router.message(Command("addadmin"), OwnerOnly())
async def cmd_add_admin(message: Message, command: CommandObject) -> None:
    if not is_owner(message):
        await message.answer(OWNER_ONLY)
        return
    if not command.args:
        await message.answer("ℹ️ ប្រើ: <code>/addadmin 987654321 ឈ្មោះ</code>")
        return
    parts = command.args.split(maxsplit=1)
    try:
        telegram_id = int(parts[0])
    except ValueError:
        await message.answer("⛔ ID ត្រូវជាលេខ")
        return
    async with db_session() as session:
        added = await crud.add_admin(session, telegram_id, parts[1].strip() if len(parts) > 1 else "")
    await message.answer(f"{'✅ បានបន័ែម' if added else '⚠️ មានស្រាប់'} <code>{telegram_id}</code>")


@router.message(Command("deladmin"), OwnerOnly())
async def cmd_del_admin(message: Message, command: CommandObject) -> None:
    if not is_owner(message):
        await message.answer(OWNER_ONLY)
        return
    if not command.args:
        await message.answer("ℹ️ ប្រើ: <code>/deladmin 987654321</code>")
        return
    try:
        telegram_id = int(command.args.split()[0])
    except ValueError:
        await message.answer("⛔ ID ត្រូវជាលេខ")
        return
    async with db_session() as session:
        await crud.remove_admin(session, telegram_id)
    await message.answer(f"✅ បានលុប <code>{telegram_id}</code> (បើមិនមែន Owner)")
