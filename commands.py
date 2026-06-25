"""Command handlers: /start, /morning, /evening, /status, /week, /month, /cancel, /yesterday"""

from datetime import date, timedelta
from telegram import Update
from telegram.ext import ContextTypes

import sheets
import cycle
import weekly_insights
import monthly_insights
from config import MORNING_QUESTIONS, EVENING_QUESTIONS
from handlers.checkin import start_flow, cancel_flow, handle_skip as checkin_skip, STATE

TELEGRAM_MESSAGE_LIMIT = 3800


def _split_message(text: str) -> list[str]:
    if len(text) <= TELEGRAM_MESSAGE_LIMIT:
        return [text]

    chunks = []
    current = ""
    for paragraph in text.split("\n\n"):
        addition = paragraph if not current else f"\n\n{paragraph}"
        if len(current) + len(addition) <= TELEGRAM_MESSAGE_LIMIT:
            current += addition
            continue
        if current:
            chunks.append(current)
        current = paragraph
    if current:
        chunks.append(current)
    return chunks


async def _reply_long(update: Update, text: str):
    for chunk in _split_message(text):
        await update.message.reply_text(chunk)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой Cycle & Wellness Tracker.\n\n"
        "Команды:\n"
        "  /morning — утренний check-in\n"
        "  /evening — вечерний check-in\n"
        "  /status  — прогресс за сегодня\n"
        "  /week    — сводка за последние 7 дней\n\n"
        "  /month   — итоги месяца\n\n"
        "Напоминания: 09:00 и 22:00 (Лиссабон) 🕐"
    )


async def cmd_morning(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_flow(update, context, "morning")


async def cmd_evening(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_flow(update, context, "evening")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cancel_flow(update, context)


async def cmd_yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start evening check-in for yesterday's date."""
    yesterday = str(date.today() - timedelta(days=1))
    await update.message.reply_text(
        f"📅 Запускаю *вечерний check-in за {yesterday}* — данные сохранятся на вчерашнюю дату.",
        parse_mode="Markdown",
    )
    await start_flow(update, context, "evening", for_date=yesterday)


async def cmd_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await checkin_skip(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = str(date.today())
    data = sheets.get_today_data()

    morning_fields = [q[0] for q in MORNING_QUESTIONS]
    evening_fields = [q[0] for q in EVENING_QUESTIONS]

    morning_done = sum(1 for f in morning_fields if data.get(f))
    evening_done = sum(1 for f in evening_fields if data.get(f))

    lines = [f"📊 Статус на {today}:\n"]
    lines.append(f"🌅 Утренний check-in: {morning_done}/{len(morning_fields)} вопросов")
    lines.append(f"🌙 Вечерний check-in: {evening_done}/{len(evening_fields)} вопросов")

    if morning_done > 0:
        lines.append("\n🌅 Утро:")
        for field, label in MORNING_QUESTIONS:
            val = data.get(field, "")
            if val:
                lines.append(f"  {label.split('(')[0].strip()}: {val}")

    if evening_done > 0:
        lines.append("\n🌙 Вечер:")
        for field, label in EVENING_QUESTIONS:
            val = data.get(field, "")
            if val:
                lines.append(f"  {label.split('(')[0].strip()}: {val}")

    if morning_done == 0 and evening_done == 0:
        lines.append("\nПока нет данных на сегодня.")

    # Cycle info
    try:
        info = cycle.get_cycle_info(sheets.get_all_records())
        block = cycle.format_cycle_block(info)
        if block:
            lines.append(f"\n{block}")
    except Exception:
        pass

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = sheets.get_week_data()
    all_records = sheets.get_all_records()

    if not records:
        await update.message.reply_text("Нет данных за последние 7 дней.")
        return

    try:
        cycle_info = cycle.get_cycle_info(all_records)
        cycle_block = cycle.format_cycle_block(cycle_info)
    except Exception:
        cycle_block = ""

    lines = [weekly_insights.build_weekly_insight(records, cycle_block, all_records)]
    if cycle_block:
        lines.append(f"\n{cycle_block}")

    await _reply_long(update, "\n".join(line for line in lines if line))


async def cmd_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    records = sheets.get_month_data()
    all_records = sheets.get_all_records()

    if not records:
        await update.message.reply_text("Нет данных за этот месяц.")
        return

    try:
        cycle_info = cycle.get_cycle_info(all_records)
        cycle_block = cycle.format_cycle_block(cycle_info)
    except Exception:
        cycle_block = ""

    lines = [monthly_insights.build_monthly_insight(records, cycle_block, all_records)]
    if cycle_block:
        lines.append(f"\n{cycle_block}")

    await _reply_long(update, "\n".join(line for line in lines if line))
