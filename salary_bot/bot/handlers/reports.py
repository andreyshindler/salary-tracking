"""Status screen, reports and CSV export."""
from __future__ import annotations

import csv
import io

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...core import ceiling as ceiling_mod
from ...core import db, repo
from ...core import timeutil as tu
from .. import formatting as fmt
from .. import keyboards as kb
from .. import texts_he as T
from .common import get_calendar, guard, safe_edit



async def _reply(update: Update, text: str, markup=None) -> None:
    if update.callback_query:
        await update.callback_query.answer()
        await safe_edit(update.callback_query, text, markup)
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def show_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        status = ceiling_mod.current_month_status(s, user)
        text = fmt.status_card(status)
        if status.hourly_agorot <= 0:
            text += "\n\n" + T.ONBOARD_NEED_RATE
    await _reply(update, text, kb.back_only())


async def cb_reports_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    await _reply(update, "📈 בחר דוח:", kb.reports_menu())


async def cb_month_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        status = ceiling_mod.current_month_status(s, user)
        text = fmt.status_card(status)
    await _reply(update, text, kb.reports_menu())


async def cb_tier_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        status = ceiling_mod.current_month_status(s, user)

        lines = [fmt.rtl(f"🧮 <b>פילוח לפי תעריף — {fmt.fmt_month(status.year, status.month)}</b>"), ""]
        if not status.tiers:
            lines.append(fmt.rtl(T.NO_SHIFTS_YET))
        else:
            for tier in status.tiers:
                label = fmt.kind_label(tier.kind)
                lines.append(
                    fmt.rtl(f"• <b>{fmt.fmt_pct(tier.multiplier)}</b> ({label}) · "
                            f"{fmt.fmt_hours(tier.hours)} שעות · {fmt.fmt_money(tier.agorot)}")
                )
            lines += [
                "",
                fmt.rtl(f"<b>סה״כ: {fmt.fmt_hours(status.total_hours)} שעות · "
                        f"{fmt.fmt_money(status.earned_agorot)}</b>"),
            ]
        text = "\n".join(lines)
    await _reply(update, text, kb.reports_menu())


async def cb_forecast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        status = ceiling_mod.current_month_status(s, user)
        text = fmt.forecast_card(status)
    await _reply(update, text, kb.reports_menu())


async def cb_year_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update, context):
        return
    year = tu.now_local().year
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        rows = []
        for month in range(1, 13):
            status = ceiling_mod.month_status(s, user, year, month)
            if status.shift_count:
                rows.append((month, status.earned_agorot, status.ceiling_agorot, status.total_hours))
        text = fmt.year_summary(rows, year)
    await _reply(update, text, kb.reports_menu())


async def cb_export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """One row per priced segment — the form an accountant can actually check."""
    if not await guard(update, context):
        return
    await update.callback_query.answer()

    year = tu.now_local().year
    with db.session_scope() as s:
        user = db.get_or_create_user(s, update.effective_user.id)
        calendar = get_calendar(user.city)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "מזהה משמרת", "תאריך", "יום", "חג/שבת", "התחלה", "סיום",
            "שעות", "אחוז", "סוג", "סכום (₪)",
        ])

        total_agorot = 0
        total_hours = 0.0
        for month in range(1, 13):
            for shift in repo.shifts_in_month(s, user.id, year, month):
                work_date = tu.to_local(shift.start_utc).date()
                for seg in shift.segments:
                    total_agorot += seg.amount_agorot
                    total_hours += seg.hours
                    writer.writerow([
                        shift.id,
                        work_date.strftime("%d/%m/%Y"),
                        fmt.day_name(work_date),
                        calendar.holiday_label(work_date),
                        tu.to_local(seg.from_utc).strftime("%H:%M"),
                        tu.to_local(seg.to_utc).strftime("%H:%M"),
                        f"{seg.hours:.2f}",
                        fmt.fmt_pct(seg.multiplier),
                        fmt.kind_label(seg.kind),
                        f"{seg.amount_agorot / 100:.2f}",
                    ])
        writer.writerow([])
        writer.writerow(["סה״כ", "", "", "", "", "", f"{total_hours:.2f}", "", "",
                         f"{total_agorot / 100:.2f}"])

    # utf-8-sig: without the BOM, Excel on Windows renders the Hebrew as mojibake.
    data = buffer.getvalue().encode("utf-8-sig")
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=InputFile(io.BytesIO(data), filename=f"shifts-{year}.csv"),
        caption=f"📤 כל המשמרות של {year}",
    )
