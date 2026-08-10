"""Admin-only: approving, denying and revoking access.

Every handler here re-checks admin rights against the database rather than
trusting that the button was only ever shown to an admin. Callback data is just
a string the client sends back — anyone who learns the format could send
``acc:ok:<their own id>`` and approve themselves, so the check has to happen on
the way in, not on the way out.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ...core import access, db
from .. import keyboards as kb
from .. import texts_he as T
from .common import guard, safe_edit

log = logging.getLogger(__name__)


async def _require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not await guard(update, context):
        return False

    tg_id = update.effective_user.id
    with db.session_scope() as s:
        if access.is_admin(s, tg_id):
            return True

    log.warning("Non-admin %s attempted an admin action", tg_id)
    if update.callback_query:
        await update.callback_query.answer(T.ADMIN_ONLY, show_alert=True)
    else:
        await update.message.reply_text(T.ADMIN_ONLY)
    return False


def _render_users(s) -> tuple[str, list, list]:
    pending = access.users_by_status(s, access.PENDING)
    approved = access.approved_users(s)

    lines = [T.USERS_TITLE, ""]
    if pending:
        lines.append(f"<b>{T.USERS_PENDING}</b>")
    else:
        lines.append(T.USERS_NONE_PENDING)
    lines += ["", f"<b>{T.USERS_APPROVED}</b> {len(approved)}"]
    return "\n".join(lines), pending, approved


async def cb_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return
    with db.session_scope() as s:
        text, pending, approved = _render_users(s)
        markup = kb.users_menu(pending, approved)
    await update.callback_query.answer()
    await safe_edit(update.callback_query, text, markup)


async def cb_decide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve, deny or revoke. All three share a shape, so they share a handler."""
    if not await _require_admin(update, context):
        return

    _, action, raw_id = update.callback_query.data.split(":")
    target_id = int(raw_id)
    admin_id = update.effective_user.id

    if action == "rev" and target_id == admin_id:
        # Belt and braces: the button is hidden for yourself, but the callback
        # could still be sent by hand.
        await update.callback_query.answer(T.ADMIN_ONLY, show_alert=True)
        return

    new_status = {"ok": access.APPROVED, "no": access.DENIED, "rev": access.DENIED}[action]

    with db.session_scope() as s:
        user = access.set_status(s, target_id, new_status)
        if user is None:
            await update.callback_query.answer(T.USER_NOT_FOUND, show_alert=True)
            return
        name = access.display_name(user)
        # A denied user who later reapplies should reach the admin again.
        if new_status != access.APPROVED:
            user.access_notified = False
        text, pending, approved = _render_users(s)
        markup = kb.users_menu(pending, approved)

    confirmation = {
        "ok": T.ADMIN_APPROVED,
        "no": T.ADMIN_DENIED,
        "rev": T.ADMIN_REVOKED,
    }[action].format(name=name)

    await update.callback_query.answer()
    await safe_edit(update.callback_query, f"{confirmation}\n\n{text}", markup)

    notice = T.ACCESS_GRANTED_NOTICE if action == "ok" else T.ACCESS_REVOKED_NOTICE
    try:
        await context.bot.send_message(target_id, notice, parse_mode=ParseMode.HTML)
    except Exception:
        # They may have blocked the bot; the decision still stands.
        log.exception("Could not notify user %s of the access decision", target_id)


async def cb_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_admin(update, context):
        return

    target_id = int(update.callback_query.data.split(":")[2])
    with db.session_scope() as s:
        user = access.get_by_tg_id(s, target_id)
        if user is None:
            await update.callback_query.answer(T.USER_NOT_FOUND, show_alert=True)
            return
        role = "👑 מנהל" if user.is_admin else "👤 משתמש"
        text = (
            f"{role}\n\n"
            f"‏{access.display_name(user)}\n"
            f"מזהה: <code>{user.tg_user_id}</code>"
        )
        markup = kb.user_detail(target_id, is_self=target_id == update.effective_user.id)

    await update.callback_query.answer()
    await safe_edit(update.callback_query, text, markup)
