# salary-tracking

A Telegram bot for logging work hours and tracking earnings against a monthly
tax-exemption ceiling, with Israeli calendar awareness.

You tell it when you started and finished. It prices the shift against your
hourly rate — splitting it at Shabbat, holiday and overtime boundaries — and
tells you how much room is left before you reach the ceiling.

The interface is in Hebrew; the code and docs are in English.

---

## Why the pricing is not `hours × rate`

The same hour is worth a different amount depending on when it falls, so each
shift is cut into segments wherever the rate changes and each piece is priced
separately:

|                     | base | first 2 OT hours | beyond |
| ------------------- | ---- | ---------------- | ------ |
| ordinary day        | 100% | 125%             | 150%   |
| Shabbat / חג        | 150% | 175%             | 200%   |

Rest periods run from **candle lighting to havdalah**, not midnight to midnight,
so a shift starting Friday afternoon is genuinely split across two rates. The
boundary depends on your city — Jerusalem lights 40 minutes before sunset,
Tel Aviv 18 — which is why the city setting is required.

Two classifications that are easy to get wrong and are covered by tests:

- **חול המועד is an ordinary working day** (100%). Only the nine statutory yom
  tov days carry rest-day pay. Treating chol hamoed as a holiday would inflate
  earnings by 50% for a week, twice a year.
- **יום העצמאות is a rest day** for pay purposes even though it is not halachic
  yom tov, so the calendar library does not flag it and it is added explicitly.

Overtime accumulates across the whole shift, not per calendar date: a shift
running 22:00–04:00 is one working day and midnight does not reset the counter.
All arithmetic is done in UTC, so a shift crossing the DST change bills the
real number of hours.

**Overtime is daily only.** It starts after the daily threshold — 8 hours by
default, editable in Settings — and there is no weekly cap: a week may run past
42 hours without any additional premium. This is the arrangement the bot was
built for. If your terms include a weekly overtime rule, this bot does not
model it.

## The menu

```
▶️ התחלת משמרת   /   ⏹ סיום משמרת      ✍️ רישום ידני
📊 מצב החודש
🗓 המשמרות שלי                          📈 דוחות
⚙️ הגדרות                                ❓ עזרה
```

- **📊 מצב החודש** is the headline screen: earned so far, remaining until the
  ceiling, a progress bar, hours split by rate tier, how many more hours you can
  still work, and the date you would cross at the current pace.
- **✍️ רישום ידני** takes a typed line — `16:00 21:30`, `אתמול 16:00 21:30`,
  `12/09 16:00 21:30` — because that is one message where a date picker plus two
  time pickers is a dozen taps. An end earlier than the start is read as an
  overnight shift.
- **📈 דוחות** covers the monthly summary, a breakdown by tier, an annual table,
  a forecast, and a CSV export (one row per priced segment, so it can be checked
  line by line).
- **⚙️ הגדרות** holds the hourly rate, the ceiling, the city, the overtime rules
  and the notification switches.

Every logged shift replies with a breakdown card showing the reasoning rather
than only a total, with **עריכה / מחיקה** on the card itself:

```
✅ נרשמה משמרת — שישי, 18.09.2026
🕐 16:00–21:30 · 5.5 שעות

• 100% · 16:00–18:27 · 2.45 ש׳ · ₪245
• 150% · 18:27–21:30 · 3.05 ש׳ · ₪458  🕯 שבת

💰 סה״כ המשמרת: ₪703

📊 ספטמבר 2026: ₪6,420 מתוך ₪10,113
▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░ 63%
נותרו ₪3,693 ≈ 36.9 שעות רגילות (24.6 שעות שבת)
```

### Commands

`/start` · `/shift` (toggles start/stop) · `/status` · `/add` · `/report` ·
`/settings` · `/undo` · `/help`

## Notifications

Each is independently switchable in Settings:

- a shift left running for more than 12 hours;
- reaching 80% / 90% / 100% of the ceiling — fired once per threshold per month,
  at the moment the hours are logged;
- a summary when the month rolls over and the counter resets.

## Setup

```bash
git clone https://github.com/andreyshindler/salary-tracking.git /opt/salary-tracking
cd /opt/salary-tracking
python3 -m venv .venv
.venv/bin/pip install -e .

cp .env.example .env
$EDITOR .env          # BOT_TOKEN from @BotFather
```

Leave `ALLOWED_USER_IDS` empty at first, run the bot, and send it `/start` — it
refuses the message but replies with your Telegram user ID. Put that in `.env`
and restart.

```bash
.venv/bin/python -m salary_bot.bot.main
```

Then, in the bot: **⚙️ הגדרות** → set your **hourly rate** and your **city**.
The ceiling is pre-seeded at 10,113 ₪/month and can be changed there too.

### Running as a service

```bash
sudo useradd --system --home /opt/salary-tracking salarybot
sudo chown -R salarybot:salarybot /opt/salary-tracking
sudo cp deploy/salary-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now salary-bot
sudo journalctl -u salary-bot -f
```

### Backups

The whole dataset is one SQLite file. `deploy/backup.sh` takes a consistent
snapshot with sqlite3's backup API (a plain `cp` can catch a WAL database
mid-write) and prunes copies older than 30 days:

```
15 3 * * *  /opt/salary-tracking/deploy/backup.sh
```

**⚙️ הגדרות → 💾 גיבוי** sends the same snapshot to you over Telegram on demand.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The test suite covers the pricing engine against golden cases (Friday evening
splits, Saturday-night havdalah, Yom Kippur, chol hamoed, midnight crossings,
the DST change, the overtime tiers), the ceiling arithmetic, the input parser,
the rendering, and an end-to-end pass over every handler with stub Telegram
objects. One test walks every button in every keyboard and asserts it routes to
a registered handler, so a typo in `callback_data` fails the build rather than
producing a button that silently does nothing.

### Layout

```
salary_bot/
├── core/
│   ├── calendar_service.py   # rest blocks: candle lighting -> havdalah
│   ├── pay_engine.py         # shift -> priced segments   (start here)
│   ├── ceiling.py            # monthly totals vs the ceiling
│   ├── repo.py               # data access, versioned rate/ceiling lookups
│   ├── parsing.py            # free-text input
│   └── models.py, db.py, timeutil.py, cities.py
└── bot/
    ├── main.py               # wiring
    ├── texts_he.py           # every Hebrew string
    ├── formatting.py         # cards and tables
    ├── keyboards.py          # menus and callback vocabulary
    └── handlers/
```

### Conventions

- **Money is integer agorot**, never floats — the whole point is comparing a
  running total to a ceiling, and float drift there would be silently wrong.
- **Timestamps are stored as naive UTC** and converted only for display.
- **Rates and ceilings are versioned by effective date** and never updated in
  place, so a raise or an annual ceiling update cannot retroactively restate a
  month you have already been told the total for.
- **Priced segments are stored, not recomputed on read**, so every report is
  auditable and a later change to the calendar library cannot silently rewrite
  history.

## Known limitations

- **Schema changes are applied with `create_all`**, not migrations. For a
  single-user SQLite bot that is enough; adding a column later will need a
  manual `ALTER TABLE` or a move to Alembic.
- Rest-day boundaries use candle lighting and havdalah, which is the customary
  reading of the 36-hour weekly rest. If your employer computes it differently,
  the numbers will differ.
- Recorded shifts are **not** re-priced when you change the rate, the city or
  the overtime rules — by design. Delete and re-enter a shift to re-price it.
- The bot reports **gross** amounts. It does not compute tax withheld.

The ceiling figure and the rate tiers are settings, not tax advice — confirm the
numbers with your accountant.
