"""Command handlers: /start, /morning, /evening, /status, /skip, /week, /cancel, /yesterday"""

import logging
from datetime import date, timedelta
from telegram import Update
from telegram.ext import ContextTypes

import sheets
import cycle
import weekly_insights
from config import MORNING_QUESTIONS, EVENING_QUESTIONS
from handlers.checkin import start_flow, cancel_flow, handle_skip as checkin_skip, STATE

logger = logging.getLogger(__name__)

NUMERIC_EVENING = [
    ("baseline_day",           "📊 Базовый день"),
    ("evening_energy",         "⚡ Энергия"),
    ("irritability",           "😤 Раздражительность"),
    ("social_battery",         "🔋 Соц. заряд"),
    ("confidence_beauty",      "✨ Уверенность"),
    ("physical_state_evening", "💪 Физ. состояние"),
    ("productivity_focus",     "🎯 Продуктивность"),
    ("leo_day",                "🦁 День с Лео"),
    ("intimacy_desire",        "❤️ Нежность / контакт"),
]

NUMERIC_MORNING = [
    ("morning_energy",         "🌅 Энергия утром"),
    ("morning_mood",           "😊 Настроение"),
    ("sleep_quality",          "😴 Сон"),
    ("anxiety_level",          "😟 Тревога"),
]


def _bar(value: float, max_val: float = 10) -> str:
    """Mini bar chart using blocks, 10 chars wide."""
    filled = round((value / max_val) * 10)
    return "█" * filled + "░" * (10 - filled)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой Cycle & Wellness Tracker.\n\n"
        "Команды:\n"
        "  /morning — утренний check-in\n"
        "  /evening — вечерний check-in\n"
        "  /status  — прогресс за сегодня\n"
        "  /week    — сводка за последние 7 дней\n"
        "  /skip    — пропустить необязательный вопрос\n\n"
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

    # Compute averages for each numeric field
    def avg(field):
        vals = []
        for r in records:
            v = r.get(field, "")
            try:
                vals.append(float(v))
            except (ValueError, TypeError):
                pass
        return sum(vals) / len(vals) if vals else None

    try:
        cycle_info = cycle.get_cycle_info(all_records)
        cycle_block = cycle.format_cycle_block(cycle_info)
    except Exception:
        cycle_block = ""

    insight = weekly_insights.build_weekly_insight(records, cycle_block)

    lines = []
    if insight:
        lines.append(insight)
        lines.append("")

    lines.append(f"📅 Последние 7 дней ({len(records)} дн. с данными)\n")

    lines.append("── Вечерние метрики ──")
    for field, label in NUMERIC_EVENING:
        a = avg(field)
        if a is not None:
            lines.append(f"{label}\n  {_bar(a)}  {a:.1f}")

    morning_avgs = [(l, avg(f)) for f, l in NUMERIC_MORNING if avg(f) is not None]
    if morning_avgs:
        lines.append("\n── Утренние метрики ──")
        for label, a in morning_avgs:
            lines.append(f"{label}\n  {_bar(a)}  {a:.1f}")

    # Best day
    best = max(records, key=lambda r: float(r.get("baseline_day") or 0), default=None)
    worst = min(
        [r for r in records if r.get("baseline_day")],
        key=lambda r: float(r.get("baseline_day") or 10),
        default=None,
    )
    if best:
        lines.append(f"\n🏆 Лучший день: {best['date']} (baseline {best.get('baseline_day')})")
    if worst:
        lines.append(f"💔 Сложный день: {worst['date']} (baseline {worst.get('baseline_day')})")

    # Tags summary
    all_tags = []
    for r in records:
        t = r.get("tags", "")
        if t:
            all_tags.extend([x.strip() for x in t.split(",") if x.strip()])
    if all_tags:
        from collections import Counter
        top = Counter(all_tags).most_common(5)
        lines.append("\n🏷 Частые теги: " + ", ".join(f"{t}({c})" for t, c in top))

    if cycle_block:
        lines.append(f"\n{cycle_block}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
