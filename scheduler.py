"""Scheduled jobs: morning (09:00), evening (22:00), weekly report (Sun 21:00).

Catch-up logic: on startup the bot checks timestamps of last sent reminders.
If a reminder was due today (in the Lisbon window) and hasn't been sent in
the last 23 hours, it is sent immediately regardless of restart time.
"""

import json
import logging
import datetime
from collections import Counter
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application
from config import TIMEZONE, MORNING_HOUR, MORNING_MINUTE, EVENING_HOUR, EVENING_MINUTE

logger = logging.getLogger(__name__)

_CHAT_IDS_FILE = Path(__file__).parent / "chat_ids.json"
_SENT_FILE     = Path(__file__).parent / "sent_reminders.json"
_chat_ids: set[int] = set()

WEEKLY_HOUR   = 21
WEEKLY_MINUTE = 0

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
    ("morning_energy", "🌅 Энергия утром"),
    ("morning_mood",   "😊 Настроение утром"),
    ("sleep_quality",  "😴 Сон"),
    ("anxiety_level",  "😟 Тревога"),
]


# ── Timestamp-based sent tracking ─────────────────────────────────────────

def _load_sent() -> dict:
    if _SENT_FILE.exists():
        try:
            return json.loads(_SENT_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_sent(data: dict):
    try:
        _SENT_FILE.write_text(json.dumps(data))
    except Exception as e:
        logger.error(f"Failed to save sent_reminders: {e}")


def _mark_sent(key: str):
    """Record the current timestamp for the given reminder key."""
    data = _load_sent()
    data[key] = datetime.datetime.now(tz=TIMEZONE).isoformat()
    _save_sent(data)


def _hours_since_sent(key: str) -> float:
    """Return hours since the reminder was last sent. Returns 999 if never sent."""
    data = _load_sent()
    ts_str = data.get(key)
    if not ts_str:
        return 999.0
    try:
        last = datetime.datetime.fromisoformat(ts_str)
        now  = datetime.datetime.now(tz=TIMEZONE)
        return (now - last).total_seconds() / 3600
    except Exception:
        return 999.0


# ── Chat ID persistence ────────────────────────────────────────────────────

def _load_chat_ids():
    global _chat_ids
    if _CHAT_IDS_FILE.exists():
        try:
            _chat_ids = set(json.loads(_CHAT_IDS_FILE.read_text()))
            logger.info(f"Loaded chat_ids: {_chat_ids}")
        except Exception as e:
            logger.error(f"Failed to load chat_ids: {e}")


def _save_chat_ids():
    try:
        _CHAT_IDS_FILE.write_text(json.dumps(list(_chat_ids)))
    except Exception as e:
        logger.error(f"Failed to save chat_ids: {e}")


def register_chat(chat_id: int):
    if chat_id not in _chat_ids:
        _chat_ids.add(chat_id)
        _save_chat_ids()
        logger.info(f"Registered chat_id {chat_id}")


# ── Helpers ────────────────────────────────────────────────────────────────

def _start_button(flow: str) -> InlineKeyboardMarkup:
    label = "🌅 Начать утренний check-in" if flow == "morning" else "🌙 Начать вечерний check-in"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"start_flow:{flow}")
    ]])


def _bar(value: float, max_val: float = 10) -> str:
    filled = round((value / max_val) * 10)
    return "█" * filled + "░" * (10 - filled)


def _now_lisbon() -> datetime.datetime:
    return datetime.datetime.now(tz=TIMEZONE)


# ── Weekly report builder ──────────────────────────────────────────────────

def _build_weekly_report(records: list, insight: str = "") -> str:
    if not records:
        return "За эту неделю нет данных."

    def avg(field):
        vals = []
        for r in records:
            v = r.get(field)
            if v not in ("", None):
                try:
                    vals.append(float(v))
                except (ValueError, TypeError):
                    pass
        return sum(vals) / len(vals) if vals else None

    lines = []
    if insight:
        lines.append(insight)
        lines.append("")

    lines.extend([
        f"📋 *Итоги недели* — {len(records)} дн. с данными\n",
        "─── Вечерние метрики ───",
    ])
    for field, label in NUMERIC_EVENING:
        a = avg(field)
        if a is not None:
            lines.append(f"{label}\n`{_bar(a)}` {a:.1f}")

    morning_avgs = [(label, avg(field)) for field, label in NUMERIC_MORNING if avg(field) is not None]
    if morning_avgs:
        lines.append("\n─── Утренние метрики ───")
        for label, a in morning_avgs:
            lines.append(f"{label}\n`{_bar(a)}` {a:.1f}")

    scored = [r for r in records if r.get("baseline_day") not in ("", None)]
    if scored:
        try:
            best  = max(scored, key=lambda r: float(r["baseline_day"]))
            worst = min(scored, key=lambda r: float(r["baseline_day"]))
            lines.append(f"\n🏆 Лучший день: {best['date']} — baseline *{best['baseline_day']}*")
            if worst["date"] != best["date"]:
                lines.append(f"💔 Сложный день: {worst['date']} — baseline *{worst['baseline_day']}*")
            bm = best.get("best_moment", "")
            if bm:
                lines.append(f"\n✨ Момент недели:\n_{bm}_")
        except (ValueError, TypeError):
            pass

    all_tags = []
    for r in records:
        t = r.get("tags", "")
        if t:
            all_tags.extend([x.strip() for x in str(t).split(",") if x.strip()])
    if all_tags:
        top = Counter(all_tags).most_common(5)
        lines.append("\n🏷 Частые теги: " + ", ".join(f"{t} ({c})" for t, c in top))

    lines.append("\nХорошей новой недели! 💜")
    return "\n".join(lines)


# ── Senders ────────────────────────────────────────────────────────────────

async def _do_send_morning(bot, late: bool = False):
    if not _chat_ids:
        logger.warning("No registered chat_ids — skipping morning reminder")
        return
    prefix = "⏰ _Опоздавшее напоминание_ — бот перезапускался\n\n" if late else ""
    for chat_id in list(_chat_ids):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"{prefix}☀️ *Доброе утро!*\n\nВремя утреннего check-in — пара минут, и готово 💪",
                parse_mode="Markdown",
                reply_markup=_start_button("morning"),
            )
            logger.info(f"Sent morning reminder to {chat_id} (late={late})")
        except Exception as e:
            logger.error(f"Error sending morning reminder to {chat_id}: {e}")
    _mark_sent("morning")


async def _do_send_evening(bot, late: bool = False):
    if not _chat_ids:
        logger.warning("No registered chat_ids — skipping evening reminder")
        return
    prefix = "⏰ _Опоздавшее напоминание_ — бот перезапускался\n\n" if late else ""
    for chat_id in list(_chat_ids):
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=f"{prefix}🌙 *Добрый вечер!*\n\nКак прошёл день? Заполни вечерний check-in ✨",
                parse_mode="Markdown",
                reply_markup=_start_button("evening"),
            )
            logger.info(f"Sent evening reminder to {chat_id} (late={late})")
        except Exception as e:
            logger.error(f"Error sending evening reminder to {chat_id}: {e}")
    _mark_sent("evening")


async def _do_send_weekly(bot, late: bool = False):
    import sheets, cycle, weekly_insights
    records     = sheets.get_week_data()
    all_records = sheets.get_all_records()
    cycle_block = ""
    try:
        info  = cycle.get_cycle_info(all_records)
        cycle_block = cycle.format_cycle_block(info)
    except Exception:
        pass
    insight = weekly_insights.build_weekly_insight(records, cycle_block)
    text = _build_weekly_report(records, insight)
    if cycle_block:
        text += f"\n\n{cycle_block}"
    if late:
        text = "⏰ _Опоздавший отчёт_ — бот перезапускался\n\n" + text

    now = _now_lisbon()
    iso_week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]}"
    for chat_id in list(_chat_ids):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            logger.info(f"Sent weekly report to {chat_id} (late={late})")
        except Exception as e:
            logger.error(f"Error sending weekly report to {chat_id}: {e}")
    _mark_sent(f"weekly_{iso_week}")


# ── APScheduler callbacks ──────────────────────────────────────────────────

async def _send_morning(context):
    await _do_send_morning(context.bot, late=False)


async def _send_evening(context):
    await _do_send_evening(context.bot, late=False)


async def _send_weekly_report(context):
    await _do_send_weekly(context.bot, late=False)


# ── Catch-up on startup ────────────────────────────────────────────────────

async def catchup_missed(bot):
    """
    Called once on startup. Sends any reminders missed while the bot was down.

    Uses time windows + a 23-hour cooldown so reminders are never duplicated:
      Morning window : 09:00 – 20:00 Lisbon  →  send if not sent in last 23 h
      Evening window : 22:00 – 02:00 Lisbon  →  send if not sent in last 23 h
      Weekly window  : Sunday 21:00 – 02:00  →  send if not sent this week
    """
    now     = _now_lisbon()
    t       = now.time()
    weekday = now.isoweekday()  # 1=Mon … 7=Sun

    morning_start = datetime.time(MORNING_HOUR, MORNING_MINUTE)
    morning_end   = datetime.time(20, 0)
    evening_start = datetime.time(EVENING_HOUR, EVENING_MINUTE)
    # evening end wraps midnight — handled by checking time < 02:00 separately
    evening_end_next = datetime.time(2, 0)
    weekly_start  = datetime.time(WEEKLY_HOUR, WEEKLY_MINUTE)

    in_morning_window = morning_start <= t <= morning_end
    in_evening_window = t >= evening_start or t <= evening_end_next
    in_weekly_window  = (weekday == 7) and (t >= weekly_start or t <= evening_end_next)

    hours_morning = _hours_since_sent("morning")
    hours_evening = _hours_since_sent("evening")

    now_iso  = _now_lisbon()
    iso_week = f"{now_iso.isocalendar()[0]}-W{now_iso.isocalendar()[1]}"
    hours_weekly  = _hours_since_sent(f"weekly_{iso_week}")

    logger.info(
        f"Catch-up check | Lisbon time: {t.strftime('%H:%M')} | "
        f"windows: morning={in_morning_window}, evening={in_evening_window}, weekly={in_weekly_window} | "
        f"hours since last: morning={hours_morning:.1f}h, evening={hours_evening:.1f}h, weekly={hours_weekly:.1f}h"
    )

    if in_morning_window and hours_morning >= 23:
        logger.info("Catch-up: sending missed morning reminder")
        await _do_send_morning(bot, late=True)

    if in_evening_window and hours_evening >= 23:
        logger.info("Catch-up: sending missed evening reminder")
        await _do_send_evening(bot, late=True)

    if in_weekly_window and hours_weekly >= 23:
        logger.info("Catch-up: sending missed weekly report")
        await _do_send_weekly(bot, late=True)


# ── Setup ──────────────────────────────────────────────────────────────────

def setup_jobs(app: Application):
    _load_chat_ids()

    jq = app.job_queue
    jq.run_daily(
        _send_morning,
        time=datetime.time(hour=MORNING_HOUR, minute=MORNING_MINUTE, tzinfo=TIMEZONE),
        name="morning_checkin",
    )
    jq.run_daily(
        _send_evening,
        time=datetime.time(hour=EVENING_HOUR, minute=EVENING_MINUTE, tzinfo=TIMEZONE),
        name="evening_checkin",
    )
    jq.run_daily(
        _send_weekly_report,
        time=datetime.time(hour=WEEKLY_HOUR, minute=WEEKLY_MINUTE, tzinfo=TIMEZONE),
        days=(6,),  # 6 = Sunday
        name="weekly_report",
    )
    logger.info(
        f"Reminders set: morning {MORNING_HOUR}:{MORNING_MINUTE:02d}, "
        f"evening {EVENING_HOUR}:{EVENING_MINUTE:02d}, "
        f"weekly Sun {WEEKLY_HOUR}:{WEEKLY_MINUTE:02d} Lisbon. "
        f"Chats: {_chat_ids}"
    )
