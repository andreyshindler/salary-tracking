# salary-tracking

A Telegram bot for logging work hours and tracking earnings against a monthly
tax-exemption ceiling, with Israeli calendar awareness.

You tell it when you started and finished. It prices the shift against your
rates — splitting it at every band, Shabbat and holiday boundary — and tells you
how much room is left before you reach the ceiling.

The interface is in Hebrew; the code and docs are in English.

---

## Why the pricing is not `hours × rate`

Both the multiplier **and the base rate** change with the clock, so each shift is
cut into segments wherever either changes and every piece is priced on its own.

Daily bands (they tile a full 24 hours, so every minute is covered exactly once):

| window | multiplier | base rate |
| ------------- | ---- | ----- |
| 08:00 – 22:00 | 100% | day   |
| 22:00 – 05:00 | 100% | night |
| 05:00 – 07:00 | 125% | night |
| 07:00 – 08:00 | 200% | night |

Rest windows, which **override the daily bands entirely** for the hours they
cover:

| window | multiplier | base rate |
| ---------------------------- | ---- | --- |
| Friday 20:00 → Saturday 20:00 | 150% | day |
| ערב חג 20:00 → חג 20:00       | 200% | day |

So Saturday 05:00–07:00 is 150% × day rate, not 125% × night rate. Where Shabbat
and חג overlap — Rosh Hashana falling on a Saturday — the higher multiplier wins.

**Shift length never affects the rate.** A twelve-hour day shift is 100%
throughout; only the clock and the calendar matter.

Because two base rates are in play, the multiplier alone no longer explains an
amount, so every line shows the rate it was priced at:

```
✅ נרשמה משמרת — רביעי, 10.06.2026
🕐 20:00–08:00 (11.06) · 12 שעות

• 100% × ₪37.50 · 20:00–22:00 · 2 ש׳ · ₪75
• 100% × ₪38.50 · 22:00–05:00 · 7 ש׳ · ₪269.50   🌙 לילה
• 125% × ₪38.50 · 05:00–07:00 · 2 ש׳ · ₪96.25    🌙 לפנות בוקר
• 200% × ₪38.50 · 07:00–08:00 · 1 ש׳ · ₪77       🌅 בוקר

💰 סה״כ המשמרת: ₪517.75
```

Two classifications that are easy to get wrong and are covered by tests:

- **חול המועד is an ordinary working day.** Only the statutory yom tov days get
  the chag window. Pricing chol hamoed as chag would double the pay for a week,
  twice a year.
- **יום העצמאות counts as chag**, even though the calendar library does not flag
  it as yom tov, so it is added explicitly.

Rest windows use fixed clock times rather than candle lighting, so they do not
vary by city or season. The Hebrew calendar is still used to decide *which* days
are Shabbat and חג. All arithmetic is in UTC while band edges are built from
Israel local time, so a shift crossing the DST change bills the real number of
hours and 08:00 still means 08:00 on the clock. Midnight is not a rate change.

The rules live in `salary_bot/core/pay_bands.py` — the table there is the single
place to change them. Premiums can also be switched off entirely for a flat-rate
arrangement.

## The menu

```
▶️ התחלת משמרת   /   ⏹ סיום משמרת      ✍️ רישום ידני
🗓 יומן                                  📊 מצב החודש
🗓 המשמרות שלי                          📈 דוחות
⚙️ הגדרות                                ❓ עזרה
```

- **📊 מצב החודש** is the headline screen: earned so far, remaining until the
  ceiling, a progress bar, hours split by rate tier, how many more hours you can
  still work, and the date you would cross at the current pace.
- **🗓 יומן** opens the **Mini App** on the first tap when one is configured: a
  month calendar with two scrolling time wheels, matching the Telegram theme.
  Without a public
  HTTPS address it falls back to an inline month grid — laid out right to left
  with ראשון on the right, marking days that already have hours (`•`), חג (`✡`)
  so the 200% days are visible in advance, and today in brackets.
- **✍️ רישום ידני** takes a typed line — `16:00 21:30`, `אתמול 16:00 21:30`,
  `12/09 16:00 21:30` — the fastest path for a recent day. An end earlier than
  the start is read as an overnight shift.
- **📈 דוחות** covers the monthly summary, a breakdown by tier, an annual table,
  a forecast, and a CSV export (one row per priced segment, so it can be checked
  line by line).
- **⚙️ הגדרות** holds the two base rates, the ceiling, the rate table and the
  notification switches, plus **🔄 חשב מחדש** to re-price every stored shift
  after a rules change.

Every logged shift replies with a breakdown card showing the reasoning rather
than only a total, with **עריכה / מחיקה** on the card itself:

```
✅ נרשמה משמרת — שישי, 18.09.2026
🕐 18:00–23:00 (19.09) · 29 שעות

• 100% × ₪37.50 · 18:00–20:00 · 2 ש׳ · ₪75
• 150% × ₪37.50 · 20:00–20:00 (19.09) · 24 ש׳ · ₪1,350  🕯 שבת
• 100% × ₪37.50 · 20:00–22:00 · 2 ש׳ · ₪75
• 100% × ₪38.50 · 22:00–23:00 · 1 ש׳ · ₪38.50  🌙 לילה

💰 סה״כ המשמרת: ₪1,538.50

📊 ספטמבר 2026: ₪1,538.50 מתוך ₪10,113
▓▓▓░░░░░░░░░░░░░░░░░ 15%
נותרו ₪8,574.50 ≈ 228.65 שעות רגילות
```

### Commands

`/start` · `/shift` (toggles start/stop) · `/status` · `/add` · `/calendar` ·
`/report` · `/settings` · `/undo` · `/help`

## The Mini App

**🗓 יומן** opens a proper calendar inside Telegram on the first tap: pick a
date, spin the hour and minute wheels for start and end, and the shift comes
straight back as a breakdown card. It uses Telegram's own theme colours, so it
matches the client in light and dark.

It is **off unless you configure it**, because Telegram refuses to open a Mini
App over anything but HTTPS with a valid certificate. With `WEBAPP_URL` unset,
🗓 יומן falls back to the inline grid, which needs no infrastructure at all.

To enable it you need a domain pointed at the VPS and a reverse proxy holding
the certificate. The container serves plain HTTP, published on the host at
`127.0.0.1:8096` so nothing is exposed directly. Port 8080 is deliberately
avoided on the host side — it is a common default and is often already taken.

```
WEBAPP_URL=https://bot.example.com
```

Caddy needs one line and obtains the certificate itself:

```
bot.example.com {
    reverse_proxy 127.0.0.1:8096
}
```

**A subpath works too** — `WEBAPP_URL=https://example.com/salary`. The server
answers on any path, so it does not matter whether the proxy strips the prefix
or forwards it. With nginx, alongside other apps on the same host:

```nginx
location = /salary { return 301 /salary/; }

location /salary/ {
    proxy_pass http://127.0.0.1:8096/;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

The `= /salary` redirect matters when a catch-all `location /` exists: without
it, the bare path falls through to whatever that catch-all proxies to. The bot
always generates the trailing-slash form, so this only affects typing the URL
by hand.

Then `docker compose up -d` and open 🗓 יומן.

**How the data comes back.** 🗓 יומן in the main menu is itself a `web_app`
button, so the first tap opens the calendar — there is no intermediate message
with a second button to press. Telegram does not deliver `sendData` from an
inline button, so the page posts its result to the bot's own server instead, at
`api/shift` **relative to the page's own address**: hosted at `/salary`, the
request goes to `/salary/api/shift` and stays inside the proxy's location
block. The server accepts it with or without the prefix.

That POST is the one route into the database that does not arrive through
Telegram, so it authenticates. Telegram signs the launch parameters with a key
derived from the bot token; `salary_bot/core/webauth.py` recomputes the HMAC
and refuses anything unsigned, signed with a different token, tampered with,
timestamped more than 24 hours away, or naming no user. A valid signature only
proves *which* account is posting — access control is applied on top of it, so
an unapproved user is refused exactly as they would be in chat.

The returned JSON is built by a page on your phone, so it is validated rather
than trusted: shape, date format, `HH:MM` times, and a plausible date range are
all checked before anything reaches the pricing engine. Overlap rejection and
the ceiling alert are shared with every other entry path. If the POST cannot
get through, the app says so on screen with the status code rather than closing
as though the shift had been saved.

## Access control

The bot is private. Anyone who messages it who is not yet approved is told that
admin approval is needed, and the admin receives their name and ID with
**✅ אשר / ❌ דחה** buttons — a stranger's first message becomes a request the
admin can act on in one tap, rather than a dead end.

- Approved users are notified and get their **own** rates, ceiling and
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

Then, in the bot: **⚙️ הגדרות → 💰 תעריפים** and send your day and night rates,
e.g. `37.5 38.5`. The ceiling is pre-seeded at 10,113 ₪/month and can be changed
there too.

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
the DST change, every band boundary), the ceiling arithmetic, the input parser,
the rendering, and an end-to-end pass over every handler with stub Telegram
objects. One test walks every button in every keyboard and asserts it routes to
a registered handler, so a typo in `callback_data` fails the build rather than
producing a button that silently does nothing.

### Layout

```
salary_bot/
├── core/
│   ├── pay_bands.py          # the rate rules   (change them here)
│   ├── calendar_service.py   # which days are Shabbat / chag
│   ├── pay_engine.py         # shift -> priced segments   (start here)
│   ├── ceiling.py            # monthly totals vs the ceiling
│   ├── repo.py               # data access, versioned rate/ceiling lookups
│   ├── parsing.py            # free-text input
│   ├── webauth.py            # verifies Telegram's signature on Mini App posts
│   └── models.py, db.py, timeutil.py, cities.py
├── webapp/
│   └── index.html            # the Mini App: calendar + hour wheels
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
- Rest windows use fixed 20:00→20:00 clock times, not candle lighting, so they
  do not follow the season. The chag window is assumed to open on the *eve*,
  mirroring the Shabbat rule.
- Recorded shifts are **not** re-priced automatically when you change the rate,
  the city or the pay rules — stored segments are what makes past reports
  auditable. Use **⚙️ הגדרות → 🌙 שעות לילה → 🔄 חשב מחדש** to apply new rules
  to everything already logged.
- The bot reports **gross** amounts. It does not compute tax withheld.

The ceiling figure and the rate tiers are settings, not tax advice — confirm the
numbers with your accountant.
