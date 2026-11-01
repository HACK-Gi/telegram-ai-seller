"""ចំណុចបញ្ចូល Panel: /start, /menu, /help, /cancel និងការរំកិលមេនុ។"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards
from admin_bot.scope import Scope
from ai_engine import get_engine
from config import settings
from helpers import esc

router = Router()

INTRO = (
    "🛠 <b>Telegram AI Auto-Seller — Admin Panel</b>\n\n"
    "{who}\n"
    f"🧠 AI backend: <code>{esc(get_engine().name)}</code>\n"
    f"🧪 Mode: <code>{'MOCK (មិនប្រើ Telegram ពិត)' if settings.use_mock_bot else 'LIVE'}</code>\n\n"
    "ជ្រើសរើសមេនុខាងក្រោម 🙌\n"
    "ចំណាំ៖ Userbot ឆ្លើយតបអតិថិជន ប៉ុន្តែ Panel នេះគ្រប់គ្រងទាំងអស់។"
)


def intro_text(scope: Scope) -> str:
    """Owner ឃើញ ID របស់គេ; staff ឃើញតែតួនាទី + ចំនួនគណនីរបស់ខ្លួន (មិនបង្ហាញ ID ម្ចាស់ទេ)។"""
    who = (
        f"👤 Owner: <code>{settings.owner_id}</code>"
        if scope.is_owner
        else f"👤 អ្នកគ្រប់គ្រង: <b>{scope.label()}</b> · គណនីរបស់អ្នក: {len(scope.ids or ())}"
    )
    return INTRO.replace("{who}", who)

HELP = """📖 <b>Commands សម្រាប់ម្ចាស់ និង Staff</b>

/start — បើក Panel
/menu — មេនុសំខាន់
/cancel — បោះបង់ការបញ្ចូល ឬការ login គណនីដែលកំពុងដំណើរ
/help — ជំនួយ
/id — បង្ហាញ Telegram ID របស់អ្នក
/stats — មើលចំណូល (តែក្នុងវិសាលភាពរបស់អ្នក)

<b>លក់/ស្តុក</b>
/categories, /addcategory — ប្រភេទអីវ៉ាន់ (ប្ដូរ = តែ Owner)
/products, /addproduct — ផលិតផល
/addstock &lt;code ឬ id&gt; — បញ្ចូល Stock ខ្លឹមសារ (auto code)
/lowstock — ផលិតផល Stock តិច

<b>គណនី Userbot</b>
/addaccount — login គណនីថ្មីក្នុង chat នេះ (លុប OTP/2FA ភ្លាម មិនទុកក្នុង log)
/accounts — បញ្ជីគណនីរបស់អ្នក
/pause &lt;id&gt;, /resume &lt;id&gt; — គណនីដែលអ្នកជាម្ចាស់
/pauseall, /resumeall, /stopbot, /startbot — <i>តែ Owner</i>

<b>វិសាលភាព</b>៖ Staff ឃើញតែគណនី + ផលិតផល + Order + អតិថិជន + QR + Analytics
ដែល derive ពីគណនីរបស់ខ្លួន។ ការកំណត់ទូទៅ/System Prompt/Admins = តែ Owner។"""


@router.message(Command("start", "menu"))
async def cmd_start(message: Message, state: FSMContext, scope: Scope) -> None:
    await state.clear()
    await message.answer(intro_text(scope), reply_markup=keyboards.main_menu(scope.is_owner))


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
        await callback.message.edit_text(intro_text(scope), reply_markup=keyboards.main_menu(scope.is_owner))
    await callback.answer()


@router.callback_query(F.data.startswith("noop"))
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()
