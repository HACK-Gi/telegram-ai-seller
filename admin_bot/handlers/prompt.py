"""🧠 System Prompt Editor — កែ persona, few-shot និងសាកល្បង AI ភ្លាមៗ។"""
from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards, render
from admin_bot.owner_gate import OwnerOnly
from ai_engine import AIAllFailed, AIError, get_engine
from ai_engine.chain import SAFE_REPLY
from ai_engine.prompting import compose_system_prompt, format_catalog
from database import crud, db_session
from helpers import esc
from userbot.safety import describe_error

log = logging.getLogger("admin.prompt")
router = Router()

TEST_CASES = (
    "សួស្តីបង",
    "តម្លៃប៉ុន្មាន?",
    "code 100 prime?",
    "qr បង",
    "ខ្ញុំបាញ់លុយរួចហើយ",
)


def fs_examples(few_shot: str) -> int:
    """រាប់ចំនួនឧទាហរណ៍ few-shot (គ្រប់ខ្សែ «អតិថិជន:»)។"""
    return sum(1 for line in few_shot.splitlines() if line.strip().startswith("អតិថិជន:"))


class EditPrompt(StatesGroup):
    system = State()
    few_shot = State()


class TestPrompt(StatesGroup):
    question = State()


async def current_composed(session) -> str:
    """Prompt ពេញលេញ (persona + catalog + few-shot) ដូចដែល AI នឹងទទួលបាន។"""
    base = await crud.get_setting(session, "system_prompt")
    few_shot = await crud.get_setting(session, "few_shot")
    products, _total = await crud.list_products(session, page=1, per_page=100)
    return compose_system_prompt(base, few_shot, format_catalog(products))


@router.callback_query(F.data == "menu:prompt", OwnerOnly())
async def cb_prompt_root(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    if callback.message is None:
        await callback.answer()
        return
    async with db_session() as session:
        base = await crud.get_setting(session, "system_prompt")
        few_shot = await crud.get_setting(session, "few_shot")
    count = fs_examples(few_shot)
    await callback.message.edit_text(
        "🧠 <b>System Prompt</b>\n\n"
        f"👤 Persona: {len(base)} តួអក្សរ\n"
        f"🎯 Few-shot: {count} ឧទាហរណ៍ · {len(few_shot)} តួអក្សរ"
        + ("\n⚠️ Few-shot ទទេ — ចុច 🎯 រួច «បញ្ចូលឧទាហរណ៍ Default» ដើម្បីឱ្យ AI ឆ្លើយត្រូវស្ទីល" if not count else ""),
        reply_markup=keyboards.prompt_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "prompt:show", OwnerOnly())
async def cb_show(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer()
        return
    async with db_session() as session:
        composed = await current_composed(session)
    await callback.answer()
    await render.send_long(callback.message, f"🧠 <b>Prompt ដែល AI ទទួលបានឥឡូវ</b>\n\n{composed}")


@router.callback_query(F.data == "prompt:edit", OwnerOnly())
async def cb_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditPrompt.system)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "✏️ ផ្ញើ<b>System Prompt ថ្មី</b> (ទាំងមូល)៖\n"
        "<i>សរសេរ <code>default</code> បើចង់ត្រឡប់ទៅ persona លំនាំដើម</i>"
    )
    await callback.answer()


@router.message(EditPrompt.system, F.text, OwnerOnly())
async def md_edit_system(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    value = crud.DEFAULTS["system_prompt"] if raw.lower() == "default" else raw
    async with db_session() as session:
        await crud.set_setting(session, "system_prompt", value)
    await state.set_state(None)
    await message.answer(
        f"✅ បានរក្សាទុក System Prompt ({len(value)} តួអក្សរ)\n🤖 AI នឹងប្រើវាភ្លាមៗសម្រាប់សារបន្ទាប់",
        reply_markup=keyboards.prompt_menu(),
    )


@router.callback_query(F.data == "prompt:fs", OwnerOnly())
async def cb_fs(callback: CallbackQuery) -> None:
    async with db_session() as session:
        few_shot = await crud.get_setting(session, "few_shot")
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"🎯 <b>Few-shot examples</b> — {fs_examples(few_shot)} ឧទាហរណ៍ · {len(few_shot)} តួអក្សរ",
        reply_markup=keyboards.fs_menu(bool(few_shot.strip())),
    )
    await callback.answer()


@router.callback_query(F.data == "prompt:fs:default", OwnerOnly())
async def cb_fs_default(callback: CallbackQuery) -> None:
    async with db_session() as session:
        await crud.set_setting(session, "few_shot", crud.DEFAULT_FEW_SHOT)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        f"✅ បានបញ្ចូលឧទាហរណ៍ Default ({fs_examples(crud.DEFAULT_FEW_SHOT)} ឧទាហរណ៍)\n"
        "🤖 AI នឹងប្រើវាភ្លាមៗសម្រាប់សារបន្ទាប់",
        reply_markup=keyboards.prompt_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "prompt:fs:show", OwnerOnly())
async def cb_fs_show(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer()
        return
    async with db_session() as session:
        few_shot = await crud.get_setting(session, "few_shot")
    await callback.answer()
    await render.send_long(
        callback.message,
        "🎯 <b>Few-shot</b>\n\n" + (few_shot or "<i>ទទេ — ចុច ✏️ សរសេរថ្មី</i>"),
    )


@router.callback_query(F.data == "prompt:fs:edit", OwnerOnly())
async def cb_fs_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(EditPrompt.few_shot)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.answer(
        "✏️ ផ្ញើ Few-shot ថ្មី (ទាំងមូល) ៖\n"
        "<code>អតិថិជន: សួស្តី</code>\n<code>អ្នក: សួស្តីបង! 🙏 មានអ្វីអាចជួយបានទេ?</code>\n\n"
        "<i>សរសេរ <code>append</code> ពីមុខ បើចង់បន្ថែមលើដែលមានស្រាប់</i>"
    )
    await callback.answer()


@router.message(EditPrompt.few_shot, F.text, OwnerOnly())
async def md_edit_few_shot(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    async with db_session() as session:
        if raw.lower().startswith("append"):
            existing = await crud.get_setting(session, "few_shot")
            value = (existing + "\n\n" + raw[6:].strip()).strip()
        else:
            value = "" if raw.lower() in ("default", "-", "ទទេ") else raw
        await crud.set_setting(session, "few_shot", value)
    await state.set_state(None)
    await message.answer(
        f"✅ បានរក្សាទុក Few-shot ({len(value)} តួអក្សរ)", reply_markup=keyboards.prompt_menu()
    )


@router.callback_query(F.data == "prompt:fs:askclear", OwnerOnly())
async def cb_fs_ask_clear(callback: CallbackQuery) -> None:
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        "🗑 សម្អាត Few-shot ទាំងអស់?", reply_markup=keyboards.confirm_action("សម្អាត", "prompt:fs:clear")
    )
    await callback.answer()


@router.callback_query(F.data == "prompt:fs:clear", OwnerOnly())
async def cb_fs_clear(callback: CallbackQuery) -> None:
    async with db_session() as session:
        await crud.set_setting(session, "few_shot", "")
    await callback.message.edit_text("🧹 បានសម្អាត Few-shot", reply_markup=keyboards.prompt_menu())
    await callback.answer()


@router.callback_query(F.data == "prompt:test", OwnerOnly())
async def cb_test(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    if callback.message is None:
        await callback.answer()
        return
    await callback.message.edit_text(
        "🧪 <b>សាកល្បង AI ពិត</b>\n\n"
        "ជ្រើស Test Case ឬសួរដោយខ្លួនឯង៖\n"
        "<i>លទ្ធផលរំពឹងទុក៖ គ្មាន Echo · ឆ្លើយតបធម្មជាតិ · យល់សំណួរស្មុគស្មាញ · ប្រើ Few-shot</i>",
        reply_markup=keyboards.ai_test_menu(TEST_CASES),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ptest:"), OwnerOnly())
async def cb_ptest(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.message is None:
        await callback.answer()
        return
    key = callback.data.split(":", 1)[1]
    if key == "custom":
        await state.set_state(TestPrompt.question)
        await callback.message.answer(
            "✍️ ផ្ញើសារមួយ ដូចអតិថិជននឹងផ្ញើ (ឧ. <i>តម្លៃប៉ុន្មាន?</i>)៖\n"
            "<i>ការសន្ទនានេះមិនត្រូវបានរក្សាទុកក្នុង DB ទេ</i>"
        )
        await callback.answer()
        return
    index = int(key) - 1
    if not 0 <= index < len(TEST_CASES):
        await callback.answer("❌ Test case មិនស្គាល់", show_alert=True)
        return
    question = TEST_CASES[index]
    await callback.message.edit_text(f"⏳ កំពុងសាកល្បង [{index + 1}] «{esc(question)}» …")
    await callback.answer()
    await run_test(callback.message, question)


async def run_test(message: Message, question: str) -> None:
    async with db_session() as session:
        composed = await current_composed(session)
    engine = get_engine()
    started = time.monotonic()
    try:
        reply = await engine.generate(composed, [], question)
    except AIAllFailed as exc:
        await message.answer(
            f"⚠️ <b>AI ទាំងអស់បរាជ័យ!</b>\n\n{esc(describe_error(exc))}\n\n"
            f"អតិថិជននឹងទទួលបានសារសុវត្ថិភាព៖ <i>{esc(SAFE_REPLY)}</i>",
            reply_markup=keyboards.ai_test_menu(TEST_CASES),
        )
        return
    except AIError as exc:
        log.warning("សាកល្បង AI បរាជ័យ: %s", describe_error(exc))
        await message.answer(f"⛔ AI បង្ហាញកំហុស ({engine.name}): {esc(describe_error(exc))}")
        return
    elapsed = time.monotonic() - started
    used = getattr(engine, "last_backend", engine.name)
    badge = f"backend: {used} · {elapsed:.1f}s · Prompt {len(composed)} តួអក្សរ"
    if getattr(engine, "fell_back", False):
        badge += "\n⚠️ Primary បរាជ័យ — កំពុងប្រើ Fallback។ " + " ; ".join(engine.attempts)
    await message.answer(
        f"🤖 <b>{esc(question)}</b>\n\n{esc(reply)}\n\n<i>{esc(badge)}</i>",
        reply_markup=keyboards.prompt_menu(),
    )


@router.message(TestPrompt.question, F.text, OwnerOnly())
async def md_test(message: Message, state: FSMContext) -> None:
    await state.set_state(None)
    await run_test(message, message.text.strip())
