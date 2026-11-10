# Panel build brief (lane L3)

Build brief for `factory/panel/`. Written 2026-11-10 against `factory-l1` at `3a44b5c`. It
condenses `docs/design/factory.md` §11, §13.3 and §14 into what to build per tab. Where this
brief and the design differ, this brief wins, and §1.2 lists every such change.

## 1. Requirement and what governs

### 1.1 Originating requirement

The operator wrote on 2026-11-10, in chat with the orchestrator (close paraphrase; the
verbatim words stay in the lane's pinned specification because this repository is public):
copy the interface of the program shown in the video, bring that content factory's idea
into this media factory, and follow the video's example. In the decision form of the same
day the operator chose a local web panel styled like the video, built right after lane L1,
and no direct-message assistant for now (Dialogs is a disabled placeholder).

The video's layout and dark style are copied. Its brand, logo, names, accounts, texts and
images are not.

### 1.2 Changes to the design, and why

| Design says | This brief | Reason |
|---|---|---|
| Named widths 1280, 1600, 1920; mobile layout deferred (§11.2, §18) | Named widths **1440** and **390**, plus **900** between them. 1280, 1600 and 1920 stay in the visual check (§13.3) | The lane's acceptance requires screenshots of every tab at 1440 and 390 |
| Rules row: one line at a container width of 1380 px or more (§11.6) | One line at a viewport of **1414 px** or more, with narrower tracks (§3.4) | Measured: the design's tracks need 1414 px of container, which a 1440 window (16 px margins) does not have |
| No horizontal page scroll at 1280 (§14) | No horizontal page scroll at any width from 390 to 1920 | Follows from the 390 requirement |
| Sticky tab bar (§11.2) | Sticky from 900 px; below that it scrolls with the page | At 390 the bar wraps to 3 rows (182 px measured), too tall to pin |

Nothing else in §11, §13.3 or §14 changes. Read them alongside this brief.

## 2. Files

**Create:**

```
factory/panel/__init__.py
factory/panel/server.py     ThreadingHTTPServer, routes, Host/CSRF/Origin checks, /img, static
factory/panel/model.py      snapshot: one read of the inputs plus the plans -> plain view data
factory/panel/actions.py    POST handlers: rules edits, start/stop, new rule, new folder
factory/panel/views.py      HTML per tab (f-strings + html.escape), shared shell
factory/panel/strings.py    every UI string, Russian (§11.11), plus Russian date formatting
factory/panel/static/panel.css
factory/panel/static/panel.js     ≤ 150 lines: dialogs, toggles, #today, bell strip
factory/panel/static/probe.js     loaded only with ?probe=1 (§13.3 item 4)
tools/visual_check.py
tests/panel_fixture.py      the §13.3 fixture builder, shared by tests and visual_check
tests/test_panel_*.py
```

**Change, and only this much:**

- `factory/cli.py`: add the `panel [--port 8770]` subcommand (§12). It builds `App` as the
  other commands do and calls `panel.server.serve(app, port)`. No other line changes.
- `README.md`: one Russian paragraph: how to start the panel, the URL, Ctrl+C to stop.

**Do not touch:** `poster/**`; the L1 modules `factory/{stock,ruleset,planner,runner,journal,
checks,attention,inputs,paths}.py`; `tests/base.py`, `tests/factory_base.py` and every
existing test (import from them, do not edit them); `KEYS.md` (the panel adds no variable);
`.gitignore`; `docs/design/factory.md`. Do not create `factory/stats.py` or anything else from
lane L2. If a core function proves wrong for the panel, stop and report it; do not patch it.

## 3. Shared parts

### 3.1 Server and snapshot

- `python3 -m factory panel` binds `127.0.0.1` (§11.1). Tests and the visual check bind port 0
  and read the port back.
- **Snapshot** (`model.py`), one object, owned by the server, behind one lock. Its key is the
  §11.1 stat walk plus the current minute. On a key change it rebuilds:
  - `finputs.load(paths, clock, redactor)`;
  - the calendar plan: `planner.plan(..., days=<to the end of the 3rd month after this>,
    back_days=<since the 1st of the previous month, machine zone>)`;
  - one `planner.plan(..., days=0, extra_active=<id>)` per draft rule (its runway, §6.3);
  - `checks.basic_problems(inputs, rule, now)` per rule;
  - `attention.items(inputs, plan, fjournal.read_heartbeat(paths.state), now)`;
  - `stats/latest.json` and `stats/collect.json` from the factory state dir, when present
    (§3.3).
  A request that arrives during a rebuild waits for it; the accept loop never does. The build
  logs its duration as `snapshot_ms` to stderr. The visual check prints it for the §13.3
  fixture, with a budget of 1000 ms. This is the first build, so it claims no speed-up.
- **Routes:** `GET /` redirects to `/connection`. Pages: `/connection`, `/files[?folder=F]`,
  `/rules`, `/calendar[?day=YYYY-MM-DD&net=N&more=K]`, `/reach[?sort=S&net=N]`,
  `/followers[?period=P]` and `/dialogs`. `?attention=1` opens the bell strip without JS, and
  `?probe=1` adds `probe.js`. Also `/img?folder&file&ref`, plus `/static/<name>` for the three
  fixed file names only (a lookup table, never a path join). Writes:
  `POST /rules/{day,hour,zone,start,stop,new}` and `POST /files/new-folder`.
- **Checks** (§11.1, kept as written): `Host` gives 421; `csrf` or a foreign `Origin` gives
  403. In addition:
  - a POST that is not `application/x-www-form-urlencoded` gets 415, and a body over 16 KB
    gets 413;
  - `/img` also requires that `ref` is one of that package's variant image refs in the
    snapshot, before the `realpath` and `sniff` checks;
  - every response carries `Content-Security-Policy: default-src 'self'; img-src 'self';
    style-src 'self'; script-src 'self'; frame-ancestors 'none'`, plus
    `Referrer-Policy: no-referrer`. Pages also carry `Cache-Control: no-store`.
- **Writes** (`actions.py`): the panel reuses the core and duplicates no checks.
  - The handler reads the rules with `fruleset.load`, applies the change and builds the rule
    with `fruleset.parse_rule`.
  - For start, and for an edit of an active rule, it runs `checks.activation_problems`.
  - It saves with `fruleset.write(path, rs, <form revision>)`, so a stale form raises
    `RevisionMismatch` under the lock.
  - Start sets `status="active"` and `active_since=config.iso_utc(now)`. Stop sets `draft`
    and clears `active_since`, which is the same thing `cmd_rule_start` and `cmd_rule_stop`
    do.
  - Success answers 303 to `/rules#rule-<id>`. A refusal answers **409** with the Rules page
    rendered and the problems in that rule's `role="alert"` block, and the file stays
    unchanged.
  - "+ new folder" validates the name with `stock.NAME_RE` and the lane with `stock.LANES`.
    It creates `stock/<name>/` (0700) and writes `folder.json` (0600) with `O_EXCL`. It
    refuses an existing name.
- **Secrets:** pages show variable names only, plus the date from
  `LINKEDIN_TOKEN_EXPIRES_AT`. Every string that comes from records, journals, stats or core
  messages passes through the snapshot's `Redactor` before it reaches HTML.
- **Core messages** (`checks.*`, `attention.items`, record `error`) are English. The panel shows
  them as they are, in mono, after a Russian label ("Проблема:", "Внимание:"). Translating
  them would copy core logic (§5).

### 3.2 Page states (all tabs)

The server renders every page in full, so there is no client-side **loading** state, spinner
or skeleton. The first request after start waits for the first snapshot (the `snapshot_ms`
budget above).

| State | Trigger | What the page shows (defining text, first screen) |
|---|---|---|
| error: env file | `config.ConfigError` | Shell plus a red block "Нет файла ключей: <message>" on every tab except Dialogs |
| error: rules | `fruleset.RulesError` | Rules, Files and Calendar show "Файл правил с ошибкой" and the problem list. Connection, Reach and Followers render normally |
| error: stats file | `latest.json` or `collect.json` is unreadable or malformed | Reach and Followers show "Статистика не читается: <file>". The other tabs render |
| error: other | any other exception | HTTP 500, a shell with "Ошибка панели: <type>: <redacted message>" |
| empty / data | per tab, §4 | per tab |

### 3.3 Contract with lane L2

L2 has not landed and no open lane touches it. The panel reads only the two files below. Each
is absent until L2's first run; the panel treats a missing file as empty, never as an error.
L2 writes these shapes, and any change to them updates this section.

```json
latest.json  {"schema": 1, "collected_at": "2026-11-10T06:01:00Z",
              "posts": [{"target": "fb:main", "network": "facebook", "post_id": "…", "date": "2026-11-09",
                         "views": 120, "likes": 4, "comments": 1, "saves": 0, "shares": 0, "reposts": 0}],
              "followers": {"fb:main": [["2026-11-09", 1520], ["2026-11-10", 1523]]}}
collect.json {"ts": "…Z", "results": {"fb:main": "ok", "ig:main": "no-permission instagram_manage_insights",
              "x": "off", "linkedin": "not built"}}
```

A metric key that is absent means "not provided" and renders as "—" (§10.1).

### 3.4 Style: palette, fonts, spacing

**Palette.** Use the §11.2 tokens exactly; the network monogram colours are listed under that
table in §11.2. A spot check on 2026-11-10 sampled the median of a 7×7 patch in the frames
with the cached headless Chromium. It confirmed the tokens within ±5 per channel:

| Token | Value | Frame sample |
|---|---|---|
| `--page` | `#000000` | `#000000` outside the app (`frame-05m33s.png`) |
| `--app` | `#080808` | `#09090b` canvas (`frame-05m33s.png`, `frame-05m50s.png`) |
| `--surface` | `#141414` | `#151515` tab bar, `#141416` folder card |
| `--surface-2` | `#18181c` | design value (zebra rows, chips) |
| `--head` | `#202028` | design value (table header, monogram disc) |
| `--tab-active` | `#38383c` | `#3a3a3a` active tab |
| `--text` | `#f0f0f4` | design value |
| `--muted` | `#8e8e93` | lightened from the video's `#6c6c70` to pass 4.5:1 |
| `--green` | `#54ac5c` | `#4dae57` ring arc |
| `--on-green` | `#0a0a0a` | text on green buttons |
| `--red` | `#ff4d4f` | run-out date |
| `--day-on` | bg `#142818`, text `#98d8a4` | weekday on |
| `--hour-on` | bg `#182830`, border `#74a4e0` | hour on |
| `--lane-photo` / `--lane-text` | `#e8c47c` / `#74a4e0` | 3 px top edge of lane cards |

**Fonts:** system stacks only.
- Sans: `ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif`.
- Mono: `ui-monospace, "Cascadia Mono", "JetBrains Mono", Consolas, monospace`.
- Sizes: body 13 px / 1.4; meta and labels 11–12 px `--muted`; tab label 13 px; folder
  count, follower number and ring centre in mono at 22 / 28 / 48 px; Reach views in mono at
  20 px in `--green`.
- All numbers, dates, times and target ids are set in mono, as the video does
  (`frame-06m17s.png`).

**Spacing**, measured from the frames: the video is a 3840 px capture of a 1920 CSS px
window, so 1 CSS px = 2 frame px. Where the design gives a value, it wins.

| Element | Frame (CSS px) | Use |
|---|---|---|
| App container | radius ≈ 12, page margin ≈ 16 | `max-width: 1440px`, `width: calc(100% - 32px)`, margin 16 auto, radius 12; below 900: margin 0, radius 0 |
| Inner padding | ≈ 14–16 | 16 |
| Tab pill | ≈ 31 tall, 4–5 apart, radius ≈ 8 | 34 tall (§11.2), gap 4, padding 0 12, radius 8 |
| Sub-header line under the tabs | ≈ 29 | 32, mono 11 px `--muted` |
| Folder card | ≈ 208 × 167, gap ≈ 10, radius ≈ 8 | 220 wide (§11.5), gap 12, radius 8, padding 12; preview tiles 48 × 72 |
| Lane section gap | ≈ 32 | 32; lane header 24 above the cards |
| Calendar day cell | ≈ 181 × 96, gap ≈ 5 | `1fr` × min 96, gap 4, radius 8 |
| Day dialog | ≈ 573 wide, rows ≈ 58 | width `min(600px, 100vw - 16px)`, rows min 56 |
| Connection ring | node discs ≈ 54, orbit radius ≈ 193, progress ring radius ≈ 100 | SVG `viewBox="0 0 420 420"`: nodes 48, orbit r 180, ring r 96, stroke 6 |
| Spacing scale | — | 4 · 8 · 12 · 16 · 24 · 32 only |

### 3.5 Shell at each width

The shell follows `frame-05m33s.png`.

- **1440** (measured in a probe page at 1440 × 900: container 1408 px): one bar row. The tabs
  take 680 px, and the right block (bell, X meter, "LinkedIn: 41 дн.", "таймер: 2 мин
  назад") takes 585 px. The bar is sticky, and the sub-header line sits under it.
- **900–1413:** the right block wraps under the tabs (bar 80 px tall, measured at 1280). The
  bar stays sticky.
- **390:** the app is full-bleed. The tabs wrap to 3 rows and the right block to a 4th; the
  whole bar is 182 px, measured. The bar is not sticky. Диалоги stays a `<span
  aria-disabled="true">` "Диалоги · выкл".
- The bell's attention strip pushes content down (§11.3). Each item links to its tab and row.

## 4. Tabs

Each tab lists what it reads, its states, its layout at 1440 and at 390, the frame it
follows, and what it must not do. 900 renders the 1440 layout with the narrower grids named.

### 4.1 Подключение (`/connection`)

The tab follows `frame-05m33s.png`, `crop-05m44s-ring.png` and `crop-05m46s-ring.png`.

- **Reads:**
  - `config.derived_targets(inputs.env)`, `Target.missing(env)` and
    `linkedin.token_problems(env, now)`;
  - `LINKEDIN_TOKEN_EXPIRES_AT`;
  - from `inputs.records`, the latest row per target (time, `url`, `status`, `error`);
  - `collect.json` results.
  The targets of `config.PROFILES[cli.DEFAULT_PROFILE]` form the group "основной профиль".
  Read them at runtime; never spell them out in code or tests.
- **State per target**, first match wins:
  1. `нет ключей` (variables missing);
  2. `нужен вход` (LinkedIn token missing or expired);
  3. `ошибка токена` (the latest record row is `failed` with `HTTP 401` or `code 190` in its
     error, or `collect.json` says `token rejected`);
  4. `подключено`.
- **States:**
  - Empty: no target has its variables. The ring reads "0 из 4", every node is labelled
    `нет ключей`, and the details card says how to fill the env file (names from `KEYS.md`).
  - Data: as below.
  - Error: env file (§3.2).
- **1440:** a left column of 320 px headed "АККАУНТЫ" holds the profile rows with their
  monograms. Right of it is the 420 px ring, centred in the remaining space. The centre
  reads "N из 4" in mono 48 px with "сети постера" under it, and the arc is filled N/4 in
  `--green`. The 5 nodes that are not built are drawn at 40 % opacity and labelled "не
  построено". Hover or focus shows a tooltip with the name; selecting a node (`?net=`) shows
  the details card under the ring.
- **390:** the accounts list comes first at full width. The ring follows, scaled to 300 px by
  its `viewBox`, then the details card at full width.
- **Must not:** offer any write action, any one-click aggregator button (§18), or any value
  from the env file.

### 4.2 Файлы (`/files`, `/files?folder=F`)

The tab follows `frame-05m50s.png`.

- **Reads:**
  - `inputs.stock` (folders, `Folder.lane`, `title` and `entries`);
  - `plan.folders` (`FolderSummary.counts`, `readers`, `runway_days` and `until`);
  - `plan.states` per entry (§6.2), and the variant text and image refs from each `Entry`;
  - the targets of the rules that read each folder;
  - the folder view also takes the planned slot per package from `plan.slots`, and
    publications from the record (`url`).
- **States:**
  - Empty (no stock folder): "Папок пока нет", then the two dashed "+ новая папка" cards, one
    per lane.
  - Data.
  - Error: env or rules (§3.2).
  - A folder with problems shows red text "нужно исправить: K" or "не одобрено: K" on its
    card.
- **1440:** the sub-header reads "N папок". Each lane has a header such as "Фото-посты · 2
  папки · 31 пакет" over a thin rule. The 220 px cards sit in a wrapping grid with
  `repeat(auto-fill, 220px)` and a gap of 12, with a 3 px lane-colour top edge. Each card
  holds:
  - the title;
  - 3 preview tiles plus "+N";
  - "N пакетов";
  - the runway bar with "N из 90 дней", "N дней ✓" or "никто не берёт · расход 0";
  - target monograms.
  The last card in each lane is the dashed "+ new folder" card. The folder view is a list of
  packages in publish order, with the per-target states of §11.5.
- **390:** the cards go to one column at full width (326 px). Tiles stay 48 × 72. In the
  folder view each package becomes a stacked block: the file and theme, then one line per
  variant, then one line per target state.
- **Must not:** write package files, reorder, approve or upload anything (§18). "+ new folder"
  writes `folder.json` only.

### 4.3 Правила (`/rules`)

The tab follows `frame-06m00s.png` (draft rows), `frame-06m05s.png` and
`crop-06m05s-rules.png` (running rows).

- **Reads:**
  - `inputs.ruleset` (the rules, `revision` and `limit(net)`);
  - per rule, `checks.basic_problems`;
  - per draft, the runway from its `extra_active` plan;
  - per active rule, the runway from `plan.runout`;
  - `inputs.stock` for the source card;
  - `zoneinfo.available_timezones()` for the datalist;
  - the X cost per week from the planned X slots' `x_cost`;
  - the limit basis text from `strings.py`: the Russian version of `ruleset.LIMIT_BASIS`.
- **States:**
  - Empty: no rules. "Правил пока нет" and the "+ Новое правило" form, open.
  - Data.
  - Row error: problems in `role="alert"` under the row. This covers the basic problems, and,
    after a refused start, the problems in the 409 response.
  - Stale: the 409 page says "Правила изменились в другом месте — обновите страницу".
  - Error: env or rules (§3.2).
- **1440** (viewport 1414 px or more): one grid line per rule. The tracks are **96 / 140 / 250
  / 150 / 250 / 276 / 140** px with a gap of 8; the probe measured the row as one line in the
  1408 px container. Weekday toggles are 30 × 28 with a gap of 4. The hour grid is 6 × 3
  cells of 40 × 28 with a gap of 4. The header row is `--head`, and rows alternate
  `--surface` and `--surface-2`. The network chips with counts sit above the table.
- **900–1413:** two lines per rule through `grid-template-areas`: "start account source
  target" over "start days hours tz".
- **390:** each rule is one stacked card at full width. The header row is hidden, and each
  cell carries its own column label in `--muted`. The order is Пуск, Аккаунт, Откуда, Куда,
  Дни, Время, Пояс. The days and hours grids keep their cell sizes (hours 260 px wide).
- **Must not:**
  - write without `csrf` and the revision;
  - change any field but the one acted on;
  - edit `limits`;
  - publish, retry or resolve (§18; these stay in the CLI).

### 4.4 Календарь (`/calendar`)

The tab follows `frame-06m09s.png`, `frame-06m14s.png` and `crop-06m09s-calendar.png` for the
grid and header, and `frame-06m11s.png` for the day window.

- **Reads:**
  - the calendar plan's `slots` (`state`, `entry`, `targets`, `skipped`, `reason`, `log`),
    `publications_7d`, `active`, `drafts` and `first_runout()`, plus `plan.manual` for
    "опубликован (вручную)";
  - each slot's rule zone, for the time and its abbreviation;
  - the machine zone (`cli.machine_zone`) for day boundaries.
- **States:**
  - Empty: no rules and no records. The grid renders with empty cells. The header reads "0
    публикаций в неделю · 0 правил в работе", and the run-out stat reads "нет активных
    правил".
  - Data.
  - Day open (`?day=` or the dialog).
  - Error: env or rules (§3.2).
  Every row state in the day list has its own words (§11.7): опубликован, ошибка,
  неизвестно, пропущен: …, X пропущен: бюджет, planned "folder → targets", нет контента,
  правило не запущено.
- **1440:** a header row with "сегодня", the month title and three stats on the right; the
  run-out date is in `--red`. Network chips sit under it. Each month is a 7-column grid. A
  cell holds the day number, the total in the top-right corner, and up to 4 chips "IG 2"
  then "+N". Past days are at 60 % opacity, and today has a `--green` outline and the word
  "сегодня". The day dialog is a native `<dialog>` opened with `showModal()`, 600 px wide.
- **390:** the stats stack under the title. Cells are about 43 px wide and show the day
  number and the total only (today's cell also keeps the word "сегодня", since colour never stands
  alone, and its accessible name ends with it); the chips are hidden, because the dialog lists the
  networks.
  Tapping a cell opens the dialog at `100vw − 16px`. Each dialog row becomes 2 lines: time,
  monogram and target on the first; state text on the second.
- **Must not:** repeat the X spend (it lives in the top bar, §14), or offer any write action.

### 4.5 Охваты (`/reach`)

The tab follows `frame-06m17s.png` (Popular), `frame-06m25s.png` and `crop-06m25s-reach.png`
(Weak), and `frame-06m31s.png` (open).

- **Reads:**
  - `inputs.records`: `published` rows not later `deleted`, with `package`, `target`,
    `post_id`, `url` and `ts`;
  - joined on (target, post_id) with `latest.json` `posts`;
  - the text and image of each package from `inputs.stock` when the package is still there,
    and otherwise its id;
  - `collect.json` for per-network "нет доступа".
- **States:**
  - Empty: no `latest.json`. One block reads "Статистика ещё не собиралась —
    `python3 -m factory stats collect`" (this is the state until L2 lands). With no
    published posts at all: "Публикаций пока нет".
  - Data.
  - Partial: a chip for a network with `no-permission …` reads "Нет доступа: <permission>".
  - Error: a stats file is unreadable (§3.2).
- **1440:** the totals line comes first, then the network chips, with the sort buttons on the
  right (the active one is `--green` with `--on-green` text). Rows sit in a centred 860 px
  column. Each row has a 48 px tile, 2 clamped text lines, and a mono line with the date,
  target and "открыть". Five right-hand metric columns of 64 px each show a mono number over
  a label; views are 20 px in `--green`, and a missing metric is "—". Numbers use the
  Russian abbreviations "7,1 млн" and "70 тыс".
- **390:** the sort buttons wrap under the totals, and the chips wrap. In each row the tile
  and text come first, then the five metrics as one strip of 5 × 62 px under the text.
- **Must not:** fetch anything from a network, or count an absent metric as 0.

### 4.6 Подписчики (`/followers`)

The tab follows `frame-06m33s.png` (crop `crop-06m33s-followers.png`).

- **Reads:** `latest.json` `followers` series per target, cut to the period (`?period=week|30|
  90|all`); `collect.json` for the special cards; `X_STATS` from env (name and value `off` or
  `weekly` only).
- **States:**
  - Empty: no `latest.json`. "Статистика ещё не собиралась — `python3 -m factory stats
    collect`", plus the two special cards.
  - Data.
  - Decline: a red delta "−12" and a red sparkline. The sign is always written.
  - Special cards: "LinkedIn · нет доступа: статистика профиля только для организаций
    (Community Management API)" and "X · выключено: чтение X платное (X_STATS=off)".
  - Error: a stats file is unreadable (§3.2).
- **1440:** the header reads "N подписчиков · K аккаунтов", with the period buttons on the
  right. Cards sit in 3 columns, gap 12, sorted by followers descending. Each card has:
  - the monogram and label;
  - the mono 28 px number and the signed delta;
  - an inline SVG area sparkline, 100 % × 64 px;
  - "за N дней".
- **390:** one column at full width; the sparkline keeps its 64 px height.
- **Must not:** draw a sparkline from fewer than 2 points (show "мало данных" instead), or
  invent a 0 delta for a missing series.

### 4.7 Диалоги (`/dialogs`)

The tab follows `frame-06m56s.png`, as a placeholder only (§11.10).

- **Reads:** nothing.
- **States:** one static page with "Помощник в директе не подключён (отложено)" and the §18
  reasons. In the tab bar it is the non-interactive "Диалоги · выкл" at every width.
- **Must not:** link, fetch, or show a count badge.

## 5. Fixture, tests and the visual check

- **Fixture** (`tests/panel_fixture.py`) builds the §13.3 item 1 data into a temp dir: 2
  lanes, 5 folders, 3 rules (1 draft, 1 with a validation problem), 60 days of journal and
  record with failed, unknown, missed and over-budget slots, 40 posts in `latest.json`, and
  4 follower series with one decline. It also builds the empty fixture.
  - Folder names, titles and texts are neutral inventions.
  - Targets come from `derived_targets` of a fake env with canary values. The default
    profile's targets are read from `config.PROFILES` at runtime.
  - The clock is frozen. The publish entry point is `FakePoster`, so nothing publishes.
- **Tests** (`http.client` on port 0): §13.3 items 2 and 3 as written, plus:
  - 415 and 413 (§3.1);
  - `/img` with a `ref` that is not among the package's refs gets 404;
  - each §3.2 error state renders its defining text;
  - each tab's empty state renders its defining text.
- **Visual check:** `python3 tools/visual_check.py --out DIR` follows §13.3 item 4.
  - Widths: **390×844, 900×900, 1280×800, 1440×900, 1600×900 and 1920×1080**.
  - It covers every tab, in the data and empty fixtures, plus: the open day dialog, Reach
    Weak, Followers with the decline, the Rules error row and the 409 refusal, the open
    attention strip, and the Files folder view.
  - The probe fails on: text cut by its box, any element wider than the viewport, text under
    the sticky bar, overlapping controls, and targets under 24 × 24.
  - Set `TMPDIR` for Chromium to a short directory under `--out` (its socket path limit is
    about 107 characters).
  - The lane's screenshots go to the directory its specification names, outside the
    repository. Never commit a PNG.
- **Checks:** run the project command first, with `HOME` and `TMPDIR` outside the tree:
  `python3 -I -B -m unittest discover -s tests -t .`. Then run the visual check, and then
  `git status --short --ignored`, which must be clean.

## 6. Validation against the requirement

The tab bar, its order, the tab names and the dark palette come from the video's frames (§3.4,
§3.5). Each tab copies the regions of its frame in the same order (§4.1–§4.6). Dialogs is the
chosen disabled placeholder (§4.7). The panel follows the video's example and adds only
safety: the Host/CSRF/image checks and redaction. Nothing here goes beyond §11 except the
390 px layout, which the lane's acceptance requires.

## 7. Deferred — not currently justified

`docs/design/factory.md` §18 stays in force. In addition:

| Item | Why deferred | Trigger |
|---|---|---|
| Russian translations of core messages (checks, attention, record errors) | It would copy logic from `checks.py` and `attention.py` into `strings.py` | The operator asks for fully Russian messages |
| Live refresh (polling, SSE) | A reload reads a fresh snapshot; the cost is one stat walk | The operator keeps the panel open as a monitor |
| Loading spinners and skeletons | Pages are server-rendered and complete when they arrive | A snapshot build passes 1 s on real data |
| Touch gestures, a horizontally scrolling tab bar, a separate mobile view | The 390 layout is a CSS fallback for the required screenshots; a scroller would cut labels at its edge | The operator uses the panel on a phone |
| Folder renaming and deletion in Files | Not in the video's Files actions; the orchestrator manages stock | The operator asks |
