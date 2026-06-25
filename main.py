"""Entry point for the Telegram Cycle & Wellness Tracker Bot."""

import logging
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from handlers.commands import cmd_start, cmd_morning, cmd_evening, cmd_skip, cmd_status, cmd_week, cmd_month, cmd_cancel, cmd_yesterday
from handlers.checkin import (
    start_flow,
    handle_scale_callback,
    handle_tag_callback,
    handle_text_answer,
    STATE,
)
from scheduler import setup_jobs, register_chat, catchup_missed

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def _register_user(update: Update, context):
    """Register chat_id so the scheduler can send reminders."""
    if update.effective_chat:
        register_chat(update.effective_chat.id)


async def _start(update: Update, context):
    await _register_user(update, context)
    await cmd_start(update, context)


async def _morning(update: Update, context):
    await _register_user(update, context)
    await cmd_morning(update, context)


async def _evening(update: Update, context):
    await _register_user(update, context)
    await cmd_evening(update, context)


async def _skip(update: Update, context):
    await _register_user(update, context)
    await cmd_skip(update, context)


async def _status(update: Update, context):
    await _register_user(update, context)
    await cmd_status(update, context)


async def _week(update: Update, context):
    await _register_user(update, context)
    await cmd_week(update, context)


async def _month(update: Update, context):
    await _register_user(update, context)
    await cmd_month(update, context)


async def _cancel(update: Update, context):
    await _register_user(update, context)
    await cmd_cancel(update, context)


async def _yesterday(update: Update, context):
    await _register_user(update, context)
    await cmd_yesterday(update, context)


async def _callback_handler(update: Update, context):
    await _register_user(update, context)
    data = update.callback_query.data or ""
    if data.startswith("start_flow:"):
        flow = data.split(":")[1]
        await update.callback_query.answer()
        await update.callback_query.message.delete()
        await start_flow(update, context, flow)
    elif data.startswith("scale:"):
        await handle_scale_callback(update, context)
    elif data.startswith("tag:"):
        await handle_tag_callback(update, context)


async def _text_handler(update: Update, context):
    await _register_user(update, context)
    handled = await handle_text_answer(update, context)
    if not handled:
        ud = context.user_data
        if ud.get(STATE) == "active":
            await update.message.reply_text(
                "Используй кнопки для ответа."
            )


async def _post_init(app: Application):
    """Runs after the bot is ready — set commands menu and catch up missed reminders."""
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("morning",   "🌅 Утренний check-in"),
        BotCommand("evening",   "🌙 Вечерний check-in"),
        BotCommand("yesterday", "📅 Вечерний за вчера"),
        BotCommand("status",    "📊 Статус за сегодня"),
        BotCommand("week",      "📈 Итоги за 7 дней"),
        BotCommand("month",     "🧭 Итоги месяца"),
        BotCommand("cancel",    "❌ Отменить текущий опрос"),
        BotCommand("start",     "🤖 Перезапустить бота"),
    ])
    await catchup_missed(app.bot)


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",     _start))
    app.add_handler(CommandHandler("morning",   _morning))
    app.add_handler(CommandHandler("evening",   _evening))
    app.add_handler(CommandHandler("yesterday", _yesterday))
    app.add_handler(CommandHandler("cancel",    _cancel))
    app.add_handler(CommandHandler("skip",      _skip))
    app.add_handler(CommandHandler("status",    _status))
    app.add_handler(CommandHandler("week",      _week))
    app.add_handler(CommandHandler("month",     _month))

    app.add_handler(CallbackQueryHandler(_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _text_handler))

    setup_jobs(app)

    logger.info("Bot starting — polling for updates...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
