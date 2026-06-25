"""Scheduled jobs: morning (09:00), evening (22:00), weekly report (Sun 21:00), monthly report.

Catch-up logic: on startup the bot checks timestamps of last sent reminders.
If a reminder was due today (in the Lisbon window) and hasn't been sent in
the last 23 hours, it is sent immediately regardless of restart time.
"""

import json
import logging
import datetime
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
MONTHLY_HOUR   = 21
MONTHLY_MINUTE = 30
TELEGRAM_MESSAGE_LIMIT = 3800

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


async def _send_long_message(bot, chat_id: int, text: str):
    for chunk in _split_message(text):
        await bot.send_message(chat_id=chat_id, text=chunk)


# ── Chat ID persistence ────────────────────────────────────────────────────

def _load_chat_ids():
    global _chat_ids
    if _CHAT_IDS_FILE.exists():
        try:
            _chat_ids.update(set(json.loads(_CHAT_IDS_FILE.read_text())))
            logger.info(f"Loaded local chat_ids: {_chat_ids}")
        except Exception as e:
            logger.error(f"Failed to load chat_ids: {e}")
    try:
        import sheets
        sheet_chat_ids = sheets.get_registered_chat_ids()
        if sheet_chat_ids:
            _chat_ids.update(sheet_chat_ids)
            _save_chat_ids()
            logger.info(f"Loaded Google Sheets chat_ids: {_chat_ids}")
    except Exception as e:
        logger.error(f"Failed to load chat_ids from sheets: {e}")


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
    try:
        import sheets
        sheets.save_chat_id(chat_id)
    except Exception as e:
        logger.error(f"Failed to persist chat_id {chat_id} to sheets: {e}")


# ── Helpers ────────────────────────────────────────────────────────────────

def _start_button(flow: str) -> InlineKeyboardMarkup:
    label = "🌅 Начать утренний check-in" if flow == "morning" else "🌙 Начать вечерний check-in"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"start_flow:{flow}")
    ]])


def _now_lisbon() -> datetime.datetime:
    return datetime.datetime.now(tz=TIMEZONE)


def _is_last_day_of_month(now: datetime.datetime) -> bool:
    return (now + datetime.timedelta(days=1)).month != now.month


def _month_key_for_report_window(now: datetime.datetime, monthly_start: datetime.time, window_end: datetime.time) -> str | None:
    current_month_key = f"{now.year}-{now.month:02d}"
    if _is_last_day_of_month(now) and now.time() >= monthly_start:
        return current_month_key
    if now.time() <= window_end:
        previous_day = now - datetime.timedelta(days=1)
        if _is_last_day_of_month(previous_day):
            return f"{previous_day.year}-{previous_day.month:02d}"
    return None


# ── Senders ────────────────────────────────────────────────────────────────

async def _do_send_morning(bot, late: bool = False):
    if not _chat_ids:
        _load_chat_ids()
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
        _load_chat_ids()
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
    if not _chat_ids:
        _load_chat_ids()
    if not _chat_ids:
        logger.warning("No registered chat_ids — skipping weekly report")
        return
    records     = sheets.get_week_data()
    all_records = sheets.get_all_records()
    cycle_block = ""
    try:
        info  = cycle.get_cycle_info(all_records)
        cycle_block = cycle.format_cycle_block(info)
    except Exception:
        pass
    text = weekly_insights.build_weekly_insight(records, cycle_block, all_records)
    if cycle_block:
        text += f"\n\n{cycle_block}"
    if late:
        text = "⏰ Опоздавший отчёт — бот перезапускался\n\n" + text

    now = _now_lisbon()
    iso_week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]}"
    for chat_id in list(_chat_ids):
        try:
            await _send_long_message(bot, chat_id, text)
            logger.info(f"Sent weekly report to {chat_id} (late={late})")
        except Exception as e:
            logger.error(f"Error sending weekly report to {chat_id}: {e}")
    _mark_sent(f"weekly_{iso_week}")


async def _do_send_monthly(bot, late: bool = False, month_key: str | None = None):
    import sheets, cycle, monthly_insights
    if not _chat_ids:
        _load_chat_ids()
    if not _chat_ids:
        logger.warning("No registered chat_ids — skipping monthly report")
        return

    now = _now_lisbon()
    month_key = month_key or f"{now.year}-{now.month:02d}"
    if _hours_since_sent(f"monthly_{month_key}") < 23:
        logger.info("Monthly report already sent for %s", month_key)
        return

    year, month = (int(part) for part in month_key.split("-", 1))
    records     = sheets.get_month_data(year=year, month=month)
    all_records = sheets.get_all_records()
    cycle_block = ""
    try:
        info  = cycle.get_cycle_info(all_records)
        cycle_block = cycle.format_cycle_block(info)
    except Exception:
        pass

    text = monthly_insights.build_monthly_insight(records, cycle_block, all_records)
    if not text:
        logger.warning("No monthly report text generated")
        return
    if cycle_block:
        text += f"\n\n{cycle_block}"
    if late:
        text = "⏰ Опоздавший месячный отчёт — бот перезапускался\n\n" + text

    for chat_id in list(_chat_ids):
        try:
            await _send_long_message(bot, chat_id, text)
            logger.info(f"Sent monthly report to {chat_id} (late={late})")
        except Exception as e:
            logger.error(f"Error sending monthly report to {chat_id}: {e}")
    _mark_sent(f"monthly_{month_key}")


# ── APScheduler callbacks ──────────────────────────────────────────────────

async def _send_morning(context):
    await _do_send_morning(context.bot, late=False)


async def _send_evening(context):
    await _do_send_evening(context.bot, late=False)


async def _send_weekly_report(context):
    await _do_send_weekly(context.bot, late=False)


async def _send_monthly_report(context):
    if _is_last_day_of_month(_now_lisbon()):
        await _do_send_monthly(context.bot, late=False)


# ── Catch-up on startup ────────────────────────────────────────────────────

async def catchup_missed(bot):
    """
    Called once on startup. Sends any reminders missed while the bot was down.

    Uses time windows + a 23-hour cooldown so reminders are never duplicated:
      Morning window : 09:00 – 20:00 Lisbon  →  send if not sent in last 23 h
      Evening window : 22:00 – 02:00 Lisbon  →  send if not sent in last 23 h
      Weekly window  : Sunday 21:00 – 02:00  →  send if not sent this week
      Monthly window : last day 21:30 – 02:00 → send if not sent this month
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
    monthly_start = datetime.time(MONTHLY_HOUR, MONTHLY_MINUTE)

    in_morning_window = morning_start <= t <= morning_end
    in_evening_window = t >= evening_start or t <= evening_end_next
    in_weekly_window  = (weekday == 7) and (t >= weekly_start or t <= evening_end_next)
    monthly_key = _month_key_for_report_window(now, monthly_start, evening_end_next)
    in_monthly_window = monthly_key is not None

    hours_morning = _hours_since_sent("morning")
    hours_evening = _hours_since_sent("evening")

    now_iso  = _now_lisbon()
    iso_week = f"{now_iso.isocalendar()[0]}-W{now_iso.isocalendar()[1]}"
    month_key = monthly_key or f"{now_iso.year}-{now_iso.month:02d}"
    hours_weekly  = _hours_since_sent(f"weekly_{iso_week}")
    hours_monthly = _hours_since_sent(f"monthly_{month_key}")

    logger.info(
        f"Catch-up check | Lisbon time: {t.strftime('%H:%M')} | "
        f"windows: morning={in_morning_window}, evening={in_evening_window}, weekly={in_weekly_window}, monthly={in_monthly_window} | "
        f"hours since last: morning={hours_morning:.1f}h, evening={hours_evening:.1f}h, weekly={hours_weekly:.1f}h, monthly={hours_monthly:.1f}h"
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

    if in_monthly_window and hours_monthly >= 23:
        logger.info("Catch-up: sending missed monthly report")
        await _do_send_monthly(bot, late=True, month_key=month_key)


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
    jq.run_daily(
        _send_monthly_report,
        time=datetime.time(hour=MONTHLY_HOUR, minute=MONTHLY_MINUTE, tzinfo=TIMEZONE),
        name="monthly_report",
    )
    logger.info(
        f"Reminders set: morning {MORNING_HOUR}:{MORNING_MINUTE:02d}, "
        f"evening {EVENING_HOUR}:{EVENING_MINUTE:02d}, "
        f"weekly Sun {WEEKLY_HOUR}:{WEEKLY_MINUTE:02d}, "
        f"monthly last day {MONTHLY_HOUR}:{MONTHLY_MINUTE:02d} Lisbon. "
        f"Chats: {_chat_ids}"
    )
