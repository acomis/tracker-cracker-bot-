"""
Core check-in flow handler.
Manages both morning and evening flows using user_data for state.
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

import sheets
from config import MORNING_QUESTIONS, EVENING_QUESTIONS
from keyboards import scale_keyboard, tags_keyboard

logger = logging.getLogger(__name__)

# State keys
STATE = "checkin_state"
FLOW = "checkin_flow"
ANSWERS = "checkin_answers"
STEP = "checkin_step"
TAGS_SELECTED = "tags_selected"
WAITING_TEXT = "waiting_text"


def _questions(flow: str):
    return MORNING_QUESTIONS if flow == "morning" else EVENING_QUESTIONS


async def start_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    flow: str,
    for_date: str | None = None,
):
    """Start a morning or evening check-in flow.

    for_date: ISO date string (e.g. '2026-05-30') to save data for a specific
    date instead of today. Used for back-filling missed check-ins.
    """
    ud = context.user_data
    ud[FLOW] = flow
    ud[STEP] = 0
    ud[ANSWERS] = {"date": for_date} if for_date else {}
    ud[TAGS_SELECTED] = []
    ud[STATE] = "active"
    ud[WAITING_TEXT] = False

    label = "🌅 Утренний" if flow == "morning" else "🌙 Вечерний"
    date_note = f" (за {for_date})" if for_date else ""
    msg = update.message or (update.callback_query and update.callback_query.message)
    if msg:
        await msg.reply_text(
            f"{label} check-in{date_note} начался!\nОтвечай на вопросы по очереди. "
            f"Используй /skip чтобы пропустить необязательный вопрос."
        )
    await _ask_current(update, context)


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the active check-in flow."""
    ud = context.user_data
    ud[STATE] = "idle"
    ud[WAITING_TEXT] = False
    ud[ANSWERS] = {}
    ud[STEP] = 0
    msg = update.message or (update.callback_query and update.callback_query.message)
    if msg:
        await msg.reply_text(
            "❌ Check-in отменён. Данные не сохранены.\n"
            "Используй /morning или /evening чтобы начать заново."
        )


async def _ask_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    flow = ud.get(FLOW)
    step = ud.get(STEP, 0)
    questions = _questions(flow)

    if step >= len(questions):
        await _finish_flow(update, context)
        return

    field, prompt = questions[step]
    msg = update.message or (update.callback_query and update.callback_query.message)

    if field == "tags":
        ud[WAITING_TEXT] = False
        await msg.reply_text(prompt, reply_markup=tags_keyboard(ud.get(TAGS_SELECTED, [])))
    elif field in ("morning_notes", "evening_notes"):
        ud[WAITING_TEXT] = True
        await msg.reply_text(prompt)
    elif field in ("best_moment", "worst_moment"):
        ud[WAITING_TEXT] = True
        await msg.reply_text(prompt)
    else:
        ud[WAITING_TEXT] = False
        await msg.reply_text(prompt, reply_markup=scale_keyboard())


async def handle_scale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 1–10 scale button press."""
    query = update.callback_query
    await query.answer()

    ud = context.user_data
    if ud.get(STATE) != "active":
        await query.edit_message_text("Нет активного check-in. Используй /morning или /evening.")
        return

    value = query.data.split(":")[1]
    flow = ud.get(FLOW)
    step = ud.get(STEP, 0)
    questions = _questions(flow)
    field, _ = questions[step]

    ud[ANSWERS][field] = int(value)
    await query.edit_message_text(f"✅ Записано: {value}")

    ud[STEP] = step + 1
    await _ask_current(update, context)


async def handle_tag_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle tag multi-select."""
    query = update.callback_query
    await query.answer()

    ud = context.user_data
    tag_value = query.data.split(":", 1)[1]

    if tag_value == "done":
        selected = ud.get(TAGS_SELECTED, [])
        ud[ANSWERS]["tags"] = ", ".join(selected) if selected else ""
        await query.edit_message_text(f"✅ Теги: {', '.join(selected) if selected else 'нет'}")
        ud[STEP] = ud.get(STEP, 0) + 1
        await _ask_current(update, context)
    else:
        selected = ud.get(TAGS_SELECTED, [])
        if tag_value in selected:
            selected.remove(tag_value)
        else:
            selected.append(tag_value)
        ud[TAGS_SELECTED] = selected
        await query.edit_message_reply_markup(reply_markup=tags_keyboard(selected))


async def handle_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text answers."""
    ud = context.user_data
    if ud.get(STATE) != "active" or not ud.get(WAITING_TEXT):
        return False

    flow = ud.get(FLOW)
    step = ud.get(STEP, 0)
    questions = _questions(flow)
    field, _ = questions[step]

    ud[ANSWERS][field] = update.message.text
    await update.message.reply_text("✅ Записано!")

    ud[STEP] = step + 1
    ud[WAITING_TEXT] = False
    await _ask_current(update, context)
    return True


async def handle_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip optional text question."""
    ud = context.user_data
    if ud.get(STATE) != "active":
        await update.message.reply_text("Нет активного check-in.")
        return

    flow = ud.get(FLOW)
    step = ud.get(STEP, 0)
    questions = _questions(flow)
    field, _ = questions[step]

    if field in ("morning_notes", "evening_notes"):
        ud[ANSWERS][field] = ""
        await update.message.reply_text("⏭ Пропущено.")
        ud[STEP] = step + 1
        ud[WAITING_TEXT] = False
        await _ask_current(update, context)
    else:
        await update.message.reply_text("Этот вопрос нельзя пропустить.")


async def _finish_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize the flow and save to sheets."""
    import cycle
    import daily_insights
    ud = context.user_data
    flow = ud.get(FLOW)
    answers = ud.get(ANSWERS, {})

    ud[STATE] = "idle"
    ud[WAITING_TEXT] = False

    label = "🌅 Утренний" if flow == "morning" else "🌙 Вечерний"
    msg = update.message or (update.callback_query and update.callback_query.message)

    ok = sheets.save_data(answers)

    if ok:
        text = f"✅ {label} check-in завершён."
    else:
        text = (
            f"⚠️ {label} check-in завершён, но сохранить данные не удалось. "
            "Проверь настройки Google Sheets."
        )

    # Append cycle info for evening check-in
    if ok and flow == "evening":
        try:
            all_records = sheets.get_all_records()
            week_records = sheets.get_week_data()
            info = cycle.get_cycle_info(all_records)
            cycle_block = cycle.format_cycle_block(info)
            today_data = sheets.get_today_data()
            if answers.get("date"):
                today_data = {**today_data, **answers}
            insight = daily_insights.build_tomorrow_decision_report(
                today_data,
                week_records,
                all_records,
                cycle_block,
            )
            if insight:
                text += f"\n\n{insight}"
            if cycle_block:
                text += f"\n\n{cycle_block}"
        except Exception:
            pass

    await msg.reply_text(text)
