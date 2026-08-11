"""Every user-facing Hebrew string.

Kept in one file so the wording can be revised without going near the handlers,
and so nothing gets hardcoded inline where it is hard to find later.
"""

# Right-to-left mark. Prefixing a line forces the paragraph direction to RTL, so
# a line beginning with a digit ("16:00 - 18:27 ...") still lays out correctly
# instead of being reordered as an LTR paragraph with the Hebrew pushed around.
RLM = "‏"

# ------------------------------------------------------------------ menu labels

BTN_START_SHIFT = "▶️ התחלת משמרת"
BTN_STOP_SHIFT = "⏹ סיום משמרת"
BTN_START_EARLIER = "🕗 התחלתי קודם"
BTN_CANCEL_SHIFT = "🗑 ביטול המשמרת הפתוחה"
BTN_MANUAL = "✍️ רישום ידני"
BTN_MY_SHIFTS = "🗓 המשמרות שלי"
BTN_STATUS = "📊 מצב החודש"
BTN_REPORTS = "📈 דוחות"
BTN_SETTINGS = "⚙️ הגדרות"
BTN_HELP = "❓ עזרה"
BTN_BACK = "⬅️ חזרה"
BTN_EDIT = "✏️ עריכה"
BTN_DELETE = "🗑 מחיקה"
BTN_CONFIRM_DELETE = "✅ כן, למחוק"
BTN_CANCEL = "❌ ביטול"

BTN_REP_MONTH = "📅 סיכום חודשי"
BTN_REP_TIERS = "🧮 פילוח לפי תעריף"
BTN_REP_YEAR = "🗂 סיכום שנתי"
BTN_REP_FORECAST = "🔮 תחזית"
BTN_REP_CSV = "📤 ייצוא CSV"

BTN_SET_RATE = "💰 תעריפים"
BTN_SET_CEILING = "🎯 תקרת הפטור"
BTN_SET_CITY = "🕯 עיר לזמני שבת"
BTN_SET_OT = "⏱ טבלת התעריפים"
BTN_RECALC = "🔄 חשב מחדש את כל המשמרות"
BTN_SET_NOTIF = "🔔 התראות"
BTN_SET_BACKUP = "💾 גיבוי"

# ---------------------------------------------------------------------- screens

WELCOME = (
    "שלום! 👋\n\n"
    "הבוט הזה רושם את שעות העבודה שלך, מחשב כמה הרווחת לפי התעריף השעתי — "
    "כולל תוספות לילה, שבת וחג — ומראה כמה נשאר לך עד תקרת הפטור החודשית.\n\n"
    "כדי להתחיל, צריך להגדיר שני דברים:"
)

ONBOARD_NEED_RATE = (
    "⚠️ עדיין לא הגדרת תעריף שעתי, אז אי אפשר לחשב שכר.\n"
    "היכנס ל‑⚙️ הגדרות ← 💰 תעריף שעתי."
)

ONBOARD_NEED_CITY = (
    "🕯 בחר עיר לחישוב זמני כניסת ויציאת שבת.\n"
    "בלי זה אי אפשר לדעת מתי מתחיל התעריף של 150%."
)

MAIN_MENU_TITLE = "מה תרצה לעשות?"

ASK_RATE = (
    "💰 מה התעריפים שלך בשקלים לשעה?\n\n"
    "שלח <b>תעריף יום</b> ואז <b>תעריף לילה</b>, למשל:\n"
    "<code>37.5 38.5</code>\n\n"
    "אם יש לך תעריף אחד בלבד, שלח מספר אחד."
)
ASK_CEILING = (
    "🎯 מה תקרת הפטור החודשית שלך בשקלים?\n"
    "שלח מספר, למשל: 10113"
)
ASK_MANUAL = (
    "✍️ שלח את המשמרת בשורה אחת:\n\n"
    "‏• <code>16:00 21:30</code> — היום\n"
    "‏• <code>אתמול 16:00 21:30</code>\n"
    "‏• <code>12/09 16:00 21:30</code> — תאריך מסוים\n\n"
    "אם שעת הסיום מוקדמת מההתחלה, אניח שהמשמרת חצתה חצות."
)
ASK_START_TIME = "🕗 באיזו שעה התחלת? שלח בפורמט HH:MM, למשל: 08:30"

SHIFT_ALREADY_OPEN = "⚠️ כבר יש לך משמרת פתוחה שהתחילה ב‑{start}.\nסיים אותה לפני שתתחיל חדשה."
SHIFT_NONE_OPEN = "אין כרגע משמרת פתוחה."
SHIFT_STARTED = "▶️ המשמרת התחילה ב‑{start}\nתעריף נוכחי: {tier}"
SHIFT_CANCELLED = "🗑 המשמרת הפתוחה בוטלה ולא נרשמה."
SHIFT_DELETED = "🗑 המשמרת נמחקה."
SHIFT_TOO_LONG = "⚠️ המשמרת ארוכה מ‑24 שעות. בדוק את השעות ונסה שוב."
SHIFT_OVERLAP = "⚠️ כבר רשומה משמרת שחופפת לשעות האלה ({start}–{end}).\nלא רשמתי, כדי שהסכום החודשי לא ייספר פעמיים."
SHIFT_START_IN_FUTURE = "⚠️ שעת ההתחלה שנתת היא בעתיד. שלח שעה שכבר עברה."

NO_SHIFTS_YET = "עדיין לא רשמת משמרות בחודש הזה."
NO_SHIFTS_AT_ALL = "עדיין אין משמרות רשומות."

CONFIRM_DELETE = "למחוק את המשמרת הזו?\n\n{summary}"

HELP = (
    "<b>איך זה עובד</b>\n\n"
    "<b>רישום שעות</b>\n"
    "‏• ▶️ מתחיל משמרת עכשיו, ⏹ מסיים אותה.\n"
    "‏• ✍️ רישום ידני — למשמרת ששכחת לרשום בזמן אמת.\n\n"
    "<b>איך מחושב השכר</b>\n"
    "כל משמרת נחתכת בנקודות שבהן התעריף משתנה, וכל חלק מתומחר בנפרד:\n\n"
    "{bands}\n\n"
    "‏<b>שבת וחג גוברים על שעות היום</b> — כל החלון מחושב בתעריף המנוחה, "
    "והפילוח היומי חוזר רק אחרי שהחלון נסגר.\n\n"
    "‏<b>חול המועד נחשב יום עבודה רגיל</b>, כמו בחוק. "
    "יום העצמאות נחשב חג.\n\n"
    "<b>תקרת הפטור</b>\n"
    "כל חודש מתחיל מחדש ב‑1 בחודש. הבוט סופר רק הכנסה מעבודה שרשמת כאן, "
    "ומראה כמה שקלים — וכמה שעות — נשארו עד התקרה.\n\n"
    "<b>פקודות</b>\n"
    "/shift — התחלה או סיום משמרת\n"
    "/status — מצב החודש\n"
    "/add — רישום ידני\n"
    "/report — דוחות\n"
    "/settings — הגדרות\n"
    "/undo — מחיקת הרישום האחרון\n"
)

BANDS_TITLE = "⏱ <b>טבלת התעריפים</b>"

SETTINGS_TITLE = "⚙️ הגדרות"
SETTINGS_SUMMARY = (
    "💰 תעריף יום: <b>{rate}</b>\n"
    "🌙 תעריף לילה: <b>{night_rate}</b>\n"
    "🎯 תקרה חודשית: <b>{ceiling}</b>\n"
    "⏱ תוספות: <b>{ot}</b>\n"
)
OT_ON = "לפי טבלת התעריפים"
OT_OFF = "כבויות (הכול בתעריף יום)"

RATE_SAVED = (
    "✅ התעריפים עודכנו:\n"
    "‏• יום: <b>{day}</b> לשעה\n"
    "‏• לילה: <b>{night}</b> לשעה\n\n"
    "{hint}"
)
CEILING_SAVED = "✅ התקרה החודשית עודכנה ל‑{ceiling}."
CITY_SAVED = "✅ העיר עודכנה ל‑{city}."
OT_TOGGLED_ON = "✅ חישוב התוספות מופעל."
OT_TOGGLED_OFF = "✅ חישוב התוספות כבוי — הכול יחושב בתעריף רגיל."
RECALC_DONE = (
    "🔄 חושבו מחדש {count} משמרות לפי הכללים הנוכחיים.\n\n{ceiling}"
)
RECALC_NONE = "אין משמרות לחישוב מחדש."
RECALC_HINT = (
    "משמרות שכבר נרשמו שומרות על החישוב הישן. "
    "אפשר לעדכן אותן ב‑🔄 חשב מחדש את כל המשמרות."
)
NOTIF_TITLE = "🔔 אילו התראות לשלוח?"
BACKUP_CAPTION = "💾 גיבוי מלא של הנתונים. שמור את הקובץ במקום בטוח."

NOTIF_OPEN_SHIFT = "משמרת שנשארה פתוחה"
NOTIF_CEILING = "התקרבות לתקרה"
NOTIF_MONTH = "סיכום בסוף החודש"

ALERT_CEILING = (
    "🔔 <b>שים לב</b>\n"
    "הגעת ל‑{pct}% מהתקרה החודשית.\n"
    "נותרו {remaining} ≈ {hours} שעות רגילות."
)
ALERT_OVER_CEILING = (
    "🔴 <b>עברת את התקרה החודשית</b>\n"
    "הרווחת {earned} מתוך תקרה של {ceiling} — חריגה של {over}."
)
ALERT_WILL_CROSS = (
    "⚠️ המשמרת הזו תעבור את התקרה החודשית.\n"
    "נותרו רק {hours} שעות עד התקרה."
)
ALERT_OPEN_SHIFT = (
    "🕐 המשמרת שהתחילה ב‑{start} עדיין פתוחה ({hours} שעות).\n"
    "שכחת לסיים אותה?"
)
MONTH_RESET = (
    "🗓 <b>חודש חדש</b>\n\n"
    "סיכום {month}:\n"
    "‏• סה״כ: {earned} מתוך {ceiling}\n"
    "‏• שעות: {hours}\n"
    "‏• משמרות: {count}\n\n"
    "המונה מתחיל מחדש."
)

ERROR_GENERIC = "משהו השתבש. נסה שוב."
NOT_AUTHORISED = "הבוט הזה פרטי."

# ------------------------------------------------------------- access control

ACCESS_REQUESTED = (
    "🔒 הבוט הזה פרטי ודורש אישור של המנהל.\n\n"
    "שלחתי את הבקשה שלך. תקבל הודעה ברגע שהיא תאושר.\n\n"
    "המזהה שלך: <code>{id}</code>"
)
ACCESS_PENDING = (
    "⏳ הבקשה שלך כבר נשלחה וממתינה לאישור המנהל.\n\n"
    "המזהה שלך: <code>{id}</code>"
)
ACCESS_DENIED = "🚫 אין לך גישה לבוט הזה."
ACCESS_GRANTED_NOTICE = (
    "✅ <b>קיבלת גישה!</b>\n\n"
    "שלח /start כדי להתחיל.\n"
    "אל תשכח להגדיר תעריף שעתי ועיר ב‑⚙️ הגדרות."
)
ACCESS_REVOKED_NOTICE = "🚫 הגישה שלך לבוט בוטלה."

ADMIN_ACCESS_REQUEST = (
    "🔔 <b>בקשת גישה חדשה</b>\n\n"
    "‏{name}\n"
    "מזהה: <code>{id}</code>"
)
ADMIN_APPROVED = "✅ {name} אושר וקיבל גישה."
ADMIN_DENIED = "🚫 הבקשה של {name} נדחתה."
ADMIN_REVOKED = "🚫 הגישה של {name} בוטלה."
ADMIN_ONLY = "הפעולה הזו זמינה למנהל בלבד."

BTN_USERS = "👥 משתמשים"
BTN_APPROVE = "✅ אשר"
BTN_DENY = "❌ דחה"
BTN_REVOKE = "🚫 בטל גישה"

USERS_TITLE = "👥 <b>ניהול משתמשים</b>"
USERS_PENDING = "ממתינים לאישור:"
USERS_APPROVED = "מאושרים:"
USERS_NONE_PENDING = "אין בקשות ממתינות."
USER_NOT_FOUND = "המשתמש לא נמצא."
