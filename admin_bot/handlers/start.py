"""ចំណុចបញ្ចូល Panel: /start, /menu, /help, /cancel និងការរំកិលមេនុ។"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, render
from admin_bot.scope import Scope
from ai_engine import get_engine
from config import settings
from helpers import esc

router = Router()

INTRO = (
    "🎉 <b>Telegram AI Auto-Seller</b> — ហាងរបស់អ្នក\n\n"
    "<i>Bot ឆ្លើយតបអតិថិជនដោយ AI ជំនួសអ្នក លើគណនី Telegram របស់អ្នក (Userbot) គ្រប់ម៉ោង</i>\n\n"
    "{who}\n"
    f"🧠 AI backend: <code>{esc(get_engine().name)}</code>\n"
    f"🧪 Mode: <code>{'MOCK (មិនប្រើ Telegram ពិត)' if settings.use_mock_bot else 'LIVE'}</code>\n\n"
    "<b>ចាប់ផ្តើម ៣ ជំហាន</b>\n"
    "១. ➕ <b>បន័ែមគណនី</b> — វាយ <code>/addsession</code> (បានគ្មានកំណត់)\n"
    "២. 📦 <b>បន្ថែមផលិតផល + Stock</b>\n"
    "៣. 💳 <b>ដាក់ QR Code</b> របស់អ្នក\n\n"
    "ជ្រើសរើសមេនុខាងក្រោម 🙌\n"
    "🔒 <b>ទិន្នន័យរបស់អ្នក គឺរបស់អ្នក</b> — គ្មានម្ចាស់ហាងណាម្នាក់ (សូម្បីតែ Owner ដើម) "
    "ឃើញ គណនី ផលិតផល Order ឬអតិថិជនរបស់អ្នកទេ។"
)


async def intro_text(scope: Scope) -> str:
    """សេចក្តីផ្តើមរបស់ <b>ម្ចាស់ហាងម្នាក់ៗ</b> — រាប់តែទិន្នន័យក្នុងវិសាលភាពរបស់ខ្លួនឯង។

    Owner ដើមក៏ជា tenant ធម្មតាផងដែរ (`is_owner` សល់តែសិទ្ធិ global: ⚙️ Settings/System Prompt)។
    """
    from database import crud, db_session

    async with db_session() as session:
        # idempotent: ហាងចាស់ដែលបង្កើតមុនជំហានទី ៥ (គ្មានប្រភេទផ្ទាល់ខ្លួន) បាន ៨ ទៅតាម /start
        await crud.seed_default_categories(session, scope.owner_id)
        accounts = await crud.list_accounts(session, owner_admin_id=scope.owner_id)
        products = await crud.count_products_by_owner(session, scope.owner_id)
        orders = await crud.count_orders_by_owner(session, scope.ids)
    active = sum(1 for item in accounts if item.status == "active")
    shop = "👑 <b>Owner</b>" if scope.is_owner else "🏪 <b>ម្ចាស់ហាង</b>"
    who = (
        f"{shop} · <code>{scope.admin_id}</code>\n"
        f"📱 គណនី <b>{len(accounts)}</b> (🟢 {active}) · 📦 ផលិតផល <b>{products}</b> · 🛒 Order <b>{orders}</b>"
    )
    if not accounts and not products:
        # ហាងថ្មីសុទ្ធសាធ — auto-register បានបន្ថែមប្រភេទលំនាំដើម ៨ ឱ្យរួច ទើបប្រាប់ជំហានចាប់ផ្តើម
        who = (
            "🎉 <b>អ្នកគឺជាម្ចាស់ហាងផ្ទាល់ខ្លួនហើយ!</b> គ្មាន «Add Admin» ទៀតទេ — "
            "គ្រប់រូបជា Tenant របស់ខ្លួនឯងភ្លាមពេលចុច <code>/start</code>\n\n"
            "<b>ជំហានចាប់ផ្តើម</b>\n"
            "១️⃣ បន្ថែមគណនី Telegram ដោយ <code>/addsession</code>\n"
            "២️⃣ បន្ថែមផលិតផល (🏷 ប្រភេទអីវ៉ាន់ ៨ របស់ហាងអ្នកមានស្រាប់)\n"
            "៣️⃣ បន្ថែម QR ទូទាត់របស់អ្នក\n"
        )
    elif not accounts:
        who += "\n⚠️ <i>ហាងរបស់អ្នកទំនេរ — ចុច ➕ បន័ែមគណនី ឬវាយ <code>/addsession</code> ដើម្បីចាប់ផ្តើម</i>"
    return INTRO.replace("{who}", who)

HELP = """📖 <b>Commands សម្រាប់ម្ចាស់ហាង</b>

/start — បើក Panel ហាងរបស់អ្នក
/menu — មេនុសំខាន់
/cancel — បោះបង់ការបញ្ចូល ឬការ login គណនីដែលកំពុងដំណើរ
/help — ជំនួយ
/id — បង្ហាញ Telegram ID របស់អ្នក
/stats — មើលចំណូល (តែក្នុងវិសាលភាពរបស់អ្នក)

<b>លក់/ស្តុក</b>
/categories — ប្រភេទអីវ៉ាន់<b>របស់ហាងអ្នក</b> (មើល/បន្ថែម/កែ/លុប = អ្នកខ្លួនឯង)
/products, /addproduct — ផលិតផលរបស់អ្នក
/addstock &lt;code ឬ id&gt; — បញ្ចូល Stock ខ្លឹមសារ (auto code តាមហាង)
/lowstock — ផលិតផល Stock តិច

<b>គណនី Userbot (បានគ្មានកំណត់)</b>
/addsession — បន័ែមគណនីថ្មីដោយ Session String (លុបសារភ្លាម ហើយ Encrypt ក្នុង DB)
/accounts — បញ្ជីគណនីរបស់អ្នកជា «កាតលេខ»
/pause &lt;id&gt;, /resume &lt;id&gt; — គណនី/អតិថិជនដែលអ្នកជាម្ចាស់
/pauseall, /resumeall — បិទ/បើក AI <b>តែគណនីរបស់អ្នក</b>
/stopbot, /startbot — <i>តែ Owner (global)</i>
⚠️ OTP login ត្រូវបានបិទ — ប្រើតែ Session String ប៉ុណ្ណោះ

<b>Multi-tenant</b>៖ គ្រប់អ្នកប្រើដែលចុច <code>/start</code> ក្លាយជា <b>ម្ចាស់ហាង</b> ភ្លាម
(មិនចាំបាច់មាន «Add Admin» មុន — មុខងារនោះត្រូវលុបចេញទាំងស្រុងហើយ)។ ហាងនីមួយៗ មាន
គណនី / ប្រភេទ / ផលិតផល / QR / Order / អតិថិជន / Analytics របស់ខ្លួនឯង ហើយគ្មាននរណាម្នាក់
ឃើញទិន្នន័យហាងផ្សេងទេ — សូម្បីតែ Owner ដើម។ ការកំណត់ទូទៅ · System Prompt · backup
= តែ Owner ប៉ុណ្ណោះ។"""


@router.message(Command("start", "menu"))
async def cmd_start(message: Message, state: FSMContext, scope: Scope) -> None:
    await state.clear()
    await message.answer(await intro_text(scope), reply_markup=keyboards.main_menu(scope.is_owner))


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"🆔 ID របស់អ្នក: <code>{message.from_user.id}</code>\n"
        f"👤 ឈ្មោះ: {esc(message.from_user.full_name)}\n"
        f"@{esc(message.from_user.username or '—')}"
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, scope: Scope) -> None:
    # login គណនីដែលកំពុងដំណើរ ត្រូវបោះបង់ផង (client ត្រូវ disconnect មិនទុក pending ទេ)
    from userbot.chat_login import get_coordinator

    dropped = await get_coordinator().cancel_for_user(scope.admin_id)
    if await state.get_state() is None and not dropped:
        await message.answer("ℹ️ មិនមានការបញ្ចូលទិន្នន័យកំពុងដំណើរទេ")
        return
    await state.clear()
    note = " · បានបោះបង់ការ login គណនី" if dropped else ""
    await message.answer(
        f"✅ បានបោះបង់{note}", reply_markup=keyboards.main_menu(scope.is_owner)
    )


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, scope: Scope) -> None:
    await state.clear()
    if callback.message:
        await render.safe_edit(callback.message, await intro_text(scope), keyboards.main_menu(scope.is_owner))
    await callback.answer()


@router.callback_query(F.data.startswith("noop"))
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
