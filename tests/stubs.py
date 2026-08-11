"""Stub Telegram objects for driving handlers without a network.

Shared by the handler and access-control suites.
"""
from __future__ import annotations

TG_ID = 111


class FakeWebAppData:
    def __init__(self, data: str):
        self.data = data
        self.button_text = "open"


class FakeMessage:
    def __init__(self, text: str = "", chat_id: int = TG_ID,
                 web_app_data: str | None = None):
        self.text = text
        self.chat_id = chat_id
        self.web_app_data = FakeWebAppData(web_app_data) if web_app_data else None
        self.replies: list[tuple[str, object]] = []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.replies.append((text, reply_markup))
        return self


class FakeCallbackQuery:
    def __init__(self, data: str, chat_id: int = TG_ID):
        self.data = data
        self.message = FakeMessage(chat_id=chat_id)
        self.answered = False
        self.alerts: list[str] = []
        self.edits: list[tuple[str, object]] = []

    async def answer(self, text=None, show_alert=False, **kwargs):
        self.answered = True
        if text:
            self.alerts.append(text)

    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))


class FakeUser:
    def __init__(self, user_id: int, username: str | None = None,
                 first_name: str | None = None):
        self.id = user_id
        self.username = username or f"user{user_id}"
        self.first_name = first_name or f"Test{user_id}"


class FakeChat:
    def __init__(self, chat_id: int):
        self.id = chat_id


class FakeUpdate:
    def __init__(self, *, text: str | None = None, callback: str | None = None,
                 web_app_data: str | None = None, user_id: int = TG_ID):
        self.effective_user = FakeUser(user_id)
        self.effective_chat = FakeChat(user_id)
        self.message = None
        if web_app_data is not None:
            self.message = FakeMessage(chat_id=user_id, web_app_data=web_app_data)
        elif text is not None:
            self.message = FakeMessage(text, chat_id=user_id)
        self.callback_query = FakeCallbackQuery(callback) if callback is not None else None


class FakeBot:
    def __init__(self):
        self.messages: list[tuple[int, str]] = []
        self.sent: list[dict] = []
        self.documents: list[dict] = []

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.messages.append((chat_id, text))
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})

    async def send_document(self, chat_id, document, caption=None, **kwargs):
        self.documents.append({"chat_id": chat_id, "document": document, "caption": caption})


class FakeContext:
    def __init__(self):
        self.bot = FakeBot()
        self.user_data: dict = {}
        self.bot_data: dict = {}
        self.chat_data: dict = {}


def last_output(update: FakeUpdate) -> str:
    """Whatever the handler last put in front of the user.

    Three destinations, because handlers legitimately use all three: editing the
    message a button lives on, replying beneath it (what the access gate does),
    or replying to a plain text message.
    """
    if update.callback_query:
        if update.callback_query.edits:
            return update.callback_query.edits[-1][0]
        if update.callback_query.message.replies:
            return update.callback_query.message.replies[-1][0]
    if update.message and update.message.replies:
        return update.message.replies[-1][0]
    raise AssertionError("handler produced no output")


def callback_data(markup) -> list[str]:
    """Every callback_data in a keyboard, flattened."""
    if markup is None:
        return []
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
