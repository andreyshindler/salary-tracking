"""Application wiring: build the bot, register handlers, run polling."""
from __future__ import annotations

import logging

from telegram import BotCommand
from telegram.ext import (
    Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    MessageHandler, filters,
)

from ..config import load_config
from ..core import db
from . import notifications
from .handlers import common, manual, reports, settings, shift, text_input

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand("start", "תפריט ראשי"),
    BotCommand("shift", "התחלה או סיום משמרת"),
    BotCommand("status", "מצב החודש"),
    BotCommand("add", "רישום ידני של משמרת"),
    BotCommand("report", "דוחות"),
    BotCommand("settings", "הגדרות"),
    BotCommand("undo", "מחיקת הרישום האחרון"),
    BotCommand("help", "עזרה"),
]


async def _post_init(app: Application) -> None:
    await app.bot.set_my_commands(COMMANDS)
    me = await app.bot.get_me()
    log.info("Bot @%s is up", me.username)


def build_application(config) -> Application:
    app = ApplicationBuilder().token(config.bot_token).post_init(_post_init).build()

    # ---- commands
    app.add_handler(CommandHandler("start", common.cmd_start))
    app.add_handler(CommandHandler("help", common.cmd_help))
    app.add_handler(CommandHandler("shift", shift.cmd_shift))
    app.add_handler(CommandHandler("status", reports.show_status))
    app.add_handler(CommandHandler("add", manual.cmd_add))
    app.add_handler(CommandHandler("report", reports.cb_reports_menu))
    app.add_handler(CommandHandler("settings", settings.show_menu))
    app.add_handler(CommandHandler("undo", shift.cmd_undo))
    app.add_handler(CommandHandler("cancel", common.cb_main))

    # ---- navigation
    app.add_handler(CallbackQueryHandler(common.cb_main, pattern=r"^m:main$"))
    app.add_handler(CallbackQueryHandler(common.cmd_help, pattern=r"^help$"))

    # ---- shifts
    app.add_handler(CallbackQueryHandler(shift.cb_start, pattern=r"^sh:start$"))
    app.add_handler(CallbackQueryHandler(shift.cb_start_earlier, pattern=r"^sh:earlier$"))
    app.add_handler(CallbackQueryHandler(shift.cb_stop, pattern=r"^sh:stop$"))
    app.add_handler(CallbackQueryHandler(shift.cb_cancel_open, pattern=r"^sh:cancel$"))
    app.add_handler(CallbackQueryHandler(manual.cb_new, pattern=r"^man:new$"))

    # ---- browsing
    app.add_handler(CallbackQueryHandler(shift.cb_month_list, pattern=r"^ls:menu$"))
    app.add_handler(CallbackQueryHandler(shift.cb_shifts_of_month, pattern=r"^ls:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(shift.cb_shift_detail, pattern=r"^sd:\d+$"))
    app.add_handler(CallbackQueryHandler(shift.cb_delete_prompt, pattern=r"^del:\d+$"))
    app.add_handler(CallbackQueryHandler(shift.cb_delete_confirm, pattern=r"^delok:\d+$"))

    # ---- status & reports
    app.add_handler(CallbackQueryHandler(reports.show_status, pattern=r"^st:cur$"))
    app.add_handler(CallbackQueryHandler(reports.cb_reports_menu, pattern=r"^rep:menu$"))
    app.add_handler(CallbackQueryHandler(reports.cb_month_report, pattern=r"^rep:month$"))
    app.add_handler(CallbackQueryHandler(reports.cb_tier_report, pattern=r"^rep:tiers$"))
    app.add_handler(CallbackQueryHandler(reports.cb_forecast, pattern=r"^rep:fc$"))
    app.add_handler(CallbackQueryHandler(reports.cb_year_report, pattern=r"^rep:year$"))
    app.add_handler(CallbackQueryHandler(reports.cb_export_csv, pattern=r"^rep:csv$"))

    # ---- settings
    app.add_handler(CallbackQueryHandler(settings.show_menu, pattern=r"^set:menu$"))
    app.add_handler(CallbackQueryHandler(settings.cb_ask_rate, pattern=r"^set:rate$"))
    app.add_handler(CallbackQueryHandler(settings.cb_ask_ceiling, pattern=r"^set:ceil$"))
    app.add_handler(CallbackQueryHandler(settings.cb_city_picker, pattern=r"^set:city$"))
    app.add_handler(CallbackQueryHandler(settings.cb_set_city, pattern=r"^setcity:"))
    app.add_handler(CallbackQueryHandler(settings.cb_overtime_menu, pattern=r"^set:ot$"))
    app.add_handler(CallbackQueryHandler(settings.cb_toggle_overtime, pattern=r"^set:ottoggle$"))
    app.add_handler(CallbackQueryHandler(settings.cb_ask_ot_threshold, pattern=r"^set:otthr$"))
    app.add_handler(CallbackQueryHandler(settings.cb_notifications, pattern=r"^set:notif$"))
    app.add_handler(CallbackQueryHandler(settings.cb_toggle_notification, pattern=r"^notif:"))
    app.add_handler(CallbackQueryHandler(settings.cb_backup, pattern=r"^set:backup$"))

    # ---- free text, last so it never shadows a command
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input.route))

    app.add_error_handler(common.on_error)

    if app.job_queue is not None:
        notifications.register(app.job_queue)
    else:  # pragma: no cover - only when the job-queue extra is missing
        log.warning("JobQueue unavailable; scheduled reminders are disabled")

    return app


def run() -> None:
    config = load_config()
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    db.init_engine(config.db_url)
    common.set_config(config)

    if not config.allowed_user_ids:
        log.warning(
            "ALLOWED_USER_IDS is empty — every request will be refused. "
            "Send /start to the bot and it will reply with your Telegram ID."
        )

    app = build_application(config)
    log.info("Starting polling (database: %s)", config.db_path)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
