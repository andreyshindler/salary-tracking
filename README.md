# salary-tracking

A Telegram bot for logging work hours and tracking earnings against a monthly
tax-exemption ceiling, with Israeli calendar awareness.

You tell it when you started and finished. It prices the shift against your
hourly rate — splitting it at night, Shabbat and holiday boundaries — and
tells you how much room is left before you reach the ceiling.

The interface is in Hebrew; the code and docs are in English.

---

## Why the pricing is not `hours × rate`

The same hour is worth a different amount depending on when it falls, so each
shift is cut into segments wherever the rate changes and each piece is priced
separately. There are exactly two rates:

| | |
| ---- | ------------------------------------------------- |
| 150% | night (22:00–08:00 by default), Shabbat, and חג     |
| 100% | everything else                                     |

**Shift length never changes the rate.** A twelve-hour day shift is 100%
throughout — only the clock and the calendar matter, never hours worked.

**Premiums do not stack.** An hour that is both night *and* Shabbat is 150%, not
200%. 150% is the highest rate that can ever apply.

Rest periods run from **candle lighting to havdalah**, not midnight to midnight,
so a shift starting Friday afternoon is genuinely split across two rates. The
boundary depends on your city — Jerusalem lights 40 minutes before sunset,
Tel Aviv 18 — which is why the city setting is required.

A Saturday evening shift can therefore carry three rates in a row:

```
• 150% · 18:00–19:20 · 1.33 ש׳ · ₪200     🕯 שבת
• 100% · 19:20–22:00 · 2.67 ש׳ · ₪266.67
• 150% · 22:00–23:00 · 1 ש׳ · ₪150        🌙 לילה
```

Two classifications that are easy to get wrong and are covered by tests:

- **חול המועד is an ordinary working day** (100%). Only the nine statutory yom
  tov days carry rest-day pay. Treating chol hamoed as a holiday would inflate
  earnings by 50% for a week, twice a year.
- **יום העצמאות is a rest day** for pay purposes even though it is not halachic
  yom tov, so the calendar library does not flag it and it is added explicitly.

The night window is evaluated in Israel local time, so 22:00 means 22:00 on the
clock. All other arithmetic is done in UTC, so a shift crossing the DST change
bills the real number of hours. Midnight is not a rate change: 22:00–04:00 is a
single 150% stretch, not two.

The night hours are configurable in **⚙️ הגדרות → 🌙 שעות לילה** — they are an
employment term, not a law. Premiums can also be switched off entirely for a
flat-rate arrangement.

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
- **⚙️ הגדרות** holds the hourly rate, the ceiling, the city, the night hours
  and the notification switches, plus **🔄 חשב מחדש** to re-price every stored shift
  after a rules change.

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

## Access control

The bot is private. Anyone who messages it who is not yet approved is told that
admin approval is needed, and the admin receives their name and ID with
**✅ אשר / ❌ דחה** buttons — a stranger's first message becomes a request the
admin can act on in one tap, rather than a dead end.

- Approved users are notified and get their **own** rate, ceiling, city and
  shifts. Nothing is shared between accounts.
- Denied users are told once and cannot reach any feature.
- The admin manages everyone from **⚙️ הגדרות → 👥 משתמשים**, which shows the
  number of waiting requests and allows revoking access later.

`ALLOWED_USER_IDS` has exactly one job: **bootstrapping**. Anyone listed there
becomes an approved admin on first contact, which solves the chicken-and-egg
problem of needing an admin before anyone can be approved. Everything after that
lives in the database, because an admin tapping a button cannot rewrite `.env` —
and even if it could, environment variables are fixed when a container is
created.

Adding an ID back to `ALLOWED_USER_IDS` and restarting is also the recovery
route if an admin ever loses access.

Access is re-checked against the database on every action. Callback data is just
a string the client sends back, so hiding an admin button is not a control —
`acc:ok:<id>` could be sent by hand. The tests assert that an approved
non-admin forging that callback cannot approve anyone.

## Notifications

Each is independently switchable in Settings:

- a shift left running for more than 12 hours;
- reaching 80% / 90% / 100% of the ceiling — fired once per threshold per month,
  at the moment the hours are logged;
- a summary when the month rolls over and the counter resets.

## Setup with Docker

```bash
git clone https://github.com/andreyshindler/salary-tracking.git /home/komodo/projects/salary-tracking
cd /home/komodo/projects/salary-tracking

cp .env.example .env
$EDITOR .env          # BOT_TOKEN from @BotFather

# The container runs as uid 10001. A host directory owned by root gives SQLite
# a permission error on the first write, so set the ownership before starting.
mkdir -p data && sudo chown -R 10001:10001 data

docker compose up -d --build
docker compose logs -f
```

Leave `ALLOWED_USER_IDS` empty at first and send the bot `/start` — it refuses
the message but replies with your Telegram user ID. Put that in `.env`, then
`docker compose up -d` to pick it up.

Then, in the bot: **⚙️ הגדרות** → set your **hourly rate** and your **city**.
The ceiling is pre-seeded at 10,113 ₪/month and can be changed there too.

Day to day:

```bash
docker compose logs -f            # follow the log
docker compose up -d              # after editing .env
docker compose up -d --build      # after git pull
docker compose down               # stop
```

Note `up -d` rather than `restart` after editing `.env`. Environment variables
are fixed when a container is created, so `docker compose restart` starts the
same container with the same stale values and your edit appears to do nothing.
`up -d` notices the changed config and recreates the container.

The database lives at `./data/salary.db` on the host, bind-mounted to `/data` in
the container. It survives rebuilds; `docker compose down` does not touch it.
Container logs are capped at 3 × 10 MB so a long-running poller cannot fill the
disk.

### Managing it with Komodo

The compose file sits at the repository root, so pointing a Komodo stack at this
repo works as-is: `build: .` and the `./data` bind mount both resolve relative to
the cloned stack directory.

Two things Komodo will not do for you:

- **The data directory ownership.** The container runs as uid 10001, so run
  `mkdir -p data && sudo chown -R 10001:10001 data` in the stack directory once,
  or the first SQLite write fails with a permission error.
- **The environment.** `docker-compose.yml` reads `env_file: .env`, so the
  variables must reach the stack as a `.env` file in that directory. Compose
  refuses to start if it is missing, which is deliberate — a bot with no
  `BOT_TOKEN` should fail loudly rather than crash-loop.

## Setup without Docker

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env && $EDITOR .env
.venv/bin/python -m salary_bot.bot.main
```

To run it as a systemd service instead of a container:

```bash
sudo useradd --system --home /home/komodo/projects/salary-tracking salarybot
sudo chown -R salarybot:salarybot /home/komodo/projects/salary-tracking
sudo cp deploy/salary-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now salary-bot
sudo journalctl -u salary-bot -f
```

## Backups

The whole dataset is one SQLite file. `deploy/backup.sh` takes a consistent
snapshot with sqlite3's backup API (a plain `cp` can catch a WAL database
mid-write) and prunes copies older than 30 days:

```
15 3 * * *  /home/komodo/projects/salary-tracking/deploy/backup.sh
```

It runs on the host against the bind-mounted file and needs no access to the
container. Override `DB` if your paths differ:

```bash
DB=/home/komodo/projects/salary-tracking/data/salary.db deploy/backup.sh
```

**⚙️ הגדרות → 💾 גיבוי** sends the same snapshot to you over Telegram on demand.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The test suite covers the pricing engine against golden cases (Friday evening
splits, Saturday-night havdalah, Yom Kippur, chol hamoed, midnight crossings,
the DST change, the night window), the ceiling arithmetic, the input parser,
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

- **Schema changes use `create_all` plus a small additive migration** in
  `core/db.py` (`_ADDED_COLUMNS`), not Alembic. It adds missing columns on
  startup and is idempotent, but it only ever *adds* — renaming or retyping a
  column would still need doing by hand.
- Rest-day boundaries use candle lighting and havdalah, which is the customary
  reading of the 36-hour weekly rest. If your employer computes it differently,
  the numbers will differ.
- Recorded shifts are **not** re-priced automatically when you change the rate,
  the city or the pay rules — stored segments are what makes past reports
  auditable. Use **⚙️ הגדרות → 🌙 שעות לילה → 🔄 חשב מחדש** to apply new rules
  to everything already logged.
- The bot reports **gross** amounts. It does not compute tax withheld.

The ceiling figure and the rate tiers are settings, not tax advice — confirm the
numbers with your accountant.
