# Content factory: stock, rules, calendar, reach, panel

Design document. Status: ready to build in three lanes (§13). Written 2026-11-10 against
`main` at `06353de` (the poster is built: `poster/`, `README.md`, `docs/design/poster.md`).
Vendor documentation was read on 2026-11-10. Each external fact cites its page. Facts the
pages do not settle are marked **U** (unconfirmed), and §15 names the cheapest check for
each. The visual reference is a set of frames from the video: one per second over 5:32–7:02,
captured by the research stage and stored outside the repository. They are cited by file
name (`frame-MMmSSs.png`, crops `crop-*.png`).

## 1. Originating requirement

The operator asked on 2026-11-10, in chat with the orchestrator (close paraphrase; the
verbatim words are kept only in the task's pinned specification). The operator wants to
copy the interface of a program shown in a public video. The author describes a personal
"content factory" from 5:32 to 7:02, and the operator wants that factory's idea copied into
this media factory. Later the same day the operator restated that the work follows the
video's example.

Source video: https://www.youtube.com/watch?v=OCgszZVSp44 (segment 5:32–7:02). This design
copies the factory's idea and the layout of its interface. It does not copy the author's
brand, names, accounts, texts, images or other assets.

Decisions the operator has already made (pinned specification, decision forms of
2026-11-08 and 2026-11-10):

1. The orchestrator writes the text for each network in chat and shows all variants to the
   operator. Nothing is published before the operator says OK.
2. Photo styling uses code templates plus optional AI effects (budget USD 5/month). That is
   a separate lane. The factory only references images that are already prepared.
3. Photos live in the library `content/images/` (git-ignored).
4. Post languages are English and Ukrainian. They are carried by each variant's text; the
   factory does not handle language.
5. X is paid per use, with a hard cap of USD 5 per calendar month (poster §11.2).

Pending in the operator's form "where to start". This design assumes the recommended
answers; §16 says what changes under each other answer.

- **start:** queue and schedule for the four networks the poster already serves.
- **where:** the scheduler runs on this computer from a timer. Posts wait while the
  computer is off.
- **panel:** a local web panel styled like the video, built right after the queue.
- **dm:** no Instagram direct-message assistant for now.

### 1.1 Validation against the requirement

| What the video shows (5:32–7:02) | Where this design copies it |
|---|---|
| Content is prepared ahead and stocked in format folders, each with "days left" | Stock: folders of approved post packages, lanes by format, runway "N of 90 days" (§6) |
| Rules: folder → account and format, weekdays, hours, time zone, draft or running, frequency hints | Rules file and Rules tab (§7, §11.6) |
| Calendar of future and past publications, posts per week, "content runs out" date | Planner and Calendar tab (§8, §11.7) |
| Publishing happens by itself | Runner on a timer through the existing poster publish path (§9) |
| Reach of each post: best and weak, with a link to the post | Stats collector and Reach tab (§10, §11.8) |
| Followers per account, green when growing and red when not | Daily follower snapshots and Followers tab (§10, §11.9) |
| One dark web panel with tabs: Connection, Files, Rules, Calendar, Reach, Followers, Dialogs | Local panel with the same tabs; Dialogs is a disabled placeholder (§11) |
| Connecting every network with one click (through an aggregator) | Not copied: connection is the env file plus the poster's LinkedIn login; Connection shows the state (§11.4, §18) |

The core needs no paid API beyond X, which stays within the existing cap. Every other item
the video shows is listed in §18 with the reason it is not built now.

## 2. What the video shows, and how ours differs

| Video element | Frames | Ours | Difference and why |
|---|---|---|---|
| Tab bar, top-right meters (storage, seats, plan badge), bell | `frame-05m33s.png` | Same tab bar. Top right shows the bell (attention count), the X month meter, the LinkedIn token days and the last timer tick | Storage and seats belong to a multi-user product; our meters are the limits that actually bind us |
| Ring of 9 networks around "5/9 connected", account list | `frame-05m33s.png`, `crop-05m44s-ring.png`, `crop-05m46s-ring.png` | Ring of the same 9 network slots. The 4 built ones are lit and the 5 not built are dim with the text "not built". The center shows "N of 4" | Only 4 networks have a publisher |
| Files: lanes by format, folder cards with thumbnails, count, runway bar, target icons, "+ new folder in this lane", "Change order" | `frame-05m50s.png` | Lanes "Photo posts" and "Text posts", the same cards, the "+ new folder" card | No video lanes (the poster publishes images and text only). Reordering is deferred |
| Rules table: Start · Account · Source · Destination · Weekdays · Hours · Time zone; draft and running rows; limit hints | `frame-06m00s.png`, `frame-06m05s.png`, `crop-06m05s-rules.png` | The same columns and controls. Destination is a set of targets | Hour grid 06:00–23:00 instead of 07:00–00:00, because a 00:00 cell would be ambiguous between two weekdays |
| Calendar: stacked months, per-day network counters, header "posts per week · rules running · content runs out" | `frame-06m09s.png`, `frame-06m14s.png`, `crop-06m09s-calendar.png` | Same | — |
| Day window: time, preview, network and account, "published · file · open", "folder → format", "rule not running" | `frame-06m11s.png` | Same, plus the states the runner produces (failed, unknown, missed, no content, over limit, over X budget) | — |
| Reach: totals, network filter, sorts Popular · Weak · Fresh · Old · By likes; rows with views, likes, comments, saves, reposts and "open" | `frame-06m17s.png`, `frame-06m25s.png`, `crop-06m25s-reach.png`, `frame-06m31s.png` | Same. A metric a network does not provide shows "—", never 0 | — |
| Followers: total and account count, periods Week · 30 days · 90 days · All time, one card per account with number, delta and chart | `frame-06m33s.png` | Same | LinkedIn cards say "no access" (§4.3) |
| Dialogs: direct-message assistant with three modes | `frame-06m56s.png` | Tab visible and disabled, labelled "off" | Operator's recommended answer: not now (§18) |

## 3. Scope

Built across three lanes (§13):

- `python3 -m factory`, a new package next to `poster/`. Python 3.12, standard library only.
  It imports the poster and does not change its publishing behaviour.
- Stock (§6), rules (§7), planner (§8) and runner (§9), plus a systemd user timer on this
  computer.
- Stats collector (§10): Facebook and Instagram reads are free. X reads are paid and off by
  default. LinkedIn has no access.
- Local web panel (§11): `http.server` from the standard library, server-rendered HTML,
  one CSS file and one small JS file, no build chain.
- Offline unit tests and a visual check that uses the cached headless Chromium (§13.3).
- Short Russian README sections (outline in §13).

Not built: §18.

## 4. Vendor facts for stats

Legend: **C** means confirmed on the cited official page (read 2026-11-10). **O** means
observed live on this project's tokens (`docs/smoke/`). **U** means unconfirmed; §15 names
the check. Publishing facts are already settled in `docs/design/poster.md` §3 and are not
repeated here.

### 4.1 Meta (Facebook Page, Instagram)

| # | Fact | Status | Source |
|---|---|---|---|
| M1 | The Graph API has call-count rate limits and no per-call price. Pages: "Calls within 24 hours = 4800 * Number of Engaged Users". Instagram: "Calls within 24 hours = 4800 * Number of Impressions". The page names no monetary charge. | C | [Rate limiting](https://developers.facebook.com/docs/graph-api/overview/rate-limiting/) |
| M2 | Graph error codes: 10 "API Permission Denied" ("Permission is either not granted or has been removed"); 190 "Access token has expired"; 200–299 "API Permission". | C | [Error handling](https://developers.facebook.com/docs/graph-api/guides/error-handling/) |
| F1 | Page field `followers_count`: "Number of page followers". For data the Page owns, the permission table lists `pages_read_engagement`, `pages_read_user_content`, `pages_show_list`. | C | [Page reference v27.0](https://developers.facebook.com/docs/graph-api/reference/page/) |
| F2 | Post field `shares`: "Number of times the post has been shared". `reactions` edge: `fields=reactions.summary(total_count)`, where `total_count` is "Total number of reactions". `comments` edge: `summary=true` returns `total_count`, "The count of comments on this node". "A page access token can read all posts posted to or posted by that Page." | C | [Post](https://developers.facebook.com/docs/graph-api/reference/post/), [Reactions](https://developers.facebook.com/docs/graph-api/reference/object/reactions/), [Comments](https://developers.facebook.com/docs/graph-api/reference/object/comments/) |
| F3 | Insights need `read_insights` and `pages_read_engagement`. Post metric `post_media_view` ("Times content … was played or displayed"), period `lifetime`. `post_impressions` and `post_impressions_unique` are "Deprecated above Graph API v25". "Page Insights data is only available on Pages with 100 or more likes." "By June 15, 2026, a number of the Page Insights metrics will be deprecated for all API versions." | C | [Insights reference v27.0](https://developers.facebook.com/docs/graph-api/reference/insights) |
| F4 | The current Page tokens were issued for publishing. `GET /{page}/feed` answered HTTP 400, code 10: "requires the 'pages_read_engagement' permission or the 'Page Public Content Access' feature". `/published_posts` was readable. | O (2026-11-09) | `docs/smoke/` (poster smoke report) |
| F5 | Whether the current Page token can read F1–F3 (`followers_count`, post reactions and comments, `post_media_view`) | **U** (S1) | — |
| I1 | IG User fields `followers_count` ("Total number of Instagram users following the user.") and `media_count`. Permissions `instagram_basic` and `pages_read_engagement`. | C | [IG User](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user) |
| I2 | IG Media fields `like_count` ("the `like_count` field is omitted if the media owner has hidden like counts"), `comments_count`, `permalink`, `timestamp`. Permissions `instagram_basic` and `pages_read_engagement`. | C | [IG Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media) |
| I3 | `GET /{media_id}/insights?metric=…`. FEED metrics include `views`, `reach`, `likes`, `comments`, `saved`, `shares`, `total_interactions`. `impressions` is deprecated "For media created after July 2, 2024". Permissions `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`. Data can be delayed up to 48 hours and is "stored for up to 2 years". Unavailable data returns an empty set, not `0`. `reach` is estimated; `views` and `total_interactions` are "in development". | C | [IG Media insights](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights) |
| I4 | Account metrics `follower_count` and `follows_and_unfollows` are "Not returned if the IG User has less than 100 followers". We use the I1 field instead, which has no such floor. | C | [IG User insights](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/insights) |
| I5 | `GET /{ig_user}/media` answered 200 with the current token, so `instagram_basic` works. | O (2026-11-09) | `docs/smoke/` |
| I6 | Whether the current token carries `instagram_manage_insights` (I3) | **U** (S2) | — |

### 4.2 X

| # | Fact | Status | Source |
|---|---|---|---|
| X1 | Pay-per-use read prices: "Posts: Read" $0.005 per resource; "User: Read" $0.010 per resource. "Owned Reads" cost $0.001 per resource for endpoints that include `GET /2/users/{id}/tweets`, "when `{id}` matches the authenticated user and that user is the owner of the developer app". "All resources are deduplicated within a 24-hour UTC day window" ("a soft guarantee"). | C | [Pricing](https://docs.x.com/x-api/getting-started/pricing) |
| X2 | "Only successful responses that return data are billed." | C | [Usage and billing](https://docs.x.com/x-api/fundamentals/post-cap) |
| X3 | `GET /2/users/me` with `public_metrics` in `user.fields` returns `followers_count`, `following_count`, `post_count`, `listed_count`. Security: OAuth 2.0 user token or `UserToken`. | C | [Get my user](https://docs.x.com/x-api/users/get-my-user) |
| X4 | `GET /2/users/{id}/tweets`: `max_results` 5–100; field selection includes `public_metrics` (the reference names the parameter `post.fields`; older pages use `tweet.fields`); user token accepted. | C (parameter name **U**, S4) | [Get posts](https://docs.x.com/x-api/users/get-posts) |
| X5 | Post `public_metrics`: `impression_count`, `like_count`, `reply_count`, `retweet_count`, `quote_count`, `bookmark_count`. Non-public and organic metrics need user context, apply only to one's own posts, and only for posts from the last 30 days. | C | [Metrics](https://docs.x.com/x-api/fundamentals/metrics) |
| X6 | Whether the poster's X account owns the developer app (so the Owned Reads price applies), and the price actually charged for `users/me` | **U** (S3) | — |

### 4.3 LinkedIn (personal profile)

| # | Fact | Status | Source |
|---|---|---|---|
| L1 | Post analytics: `GET /rest/memberCreatorPostAnalytics?q=entity&entity=(share:…)` or `(ugc:…)`, `queryType` `IMPRESSION`, `MEMBERS_REACHED`, `RESHARE`, `REACTION`, `COMMENT` and others. Permission `r_member_postAnalytics`. | C | [Member Post Statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics?view=li-lms-2026-10) |
| L2 | Followers: `GET /rest/memberFollowersCount?q=me` returns `memberFollowersCount`. Permission `r_member_profileAnalytics`. | C | [Member Follower Statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/follower-statistics?view=li-lms-2026-10) |
| L3 | Both permissions belong to the Community Management API. "At this time, our Community Management APIs are only available to registered legal organizations for commercial use cases only." The development tier allows 500 calls per app and 100 per member per 24 hours. | C | [Increasing Access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-10), [Community Management App Review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review?view=li-lms-2026-10) |
| L4 | The poster's LinkedIn app has the products "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect" (poster §10). Neither grants L1 or L2. | Inferred from poster L8 + L3 | — |

**Consequence:** LinkedIn stats are not built (§18). The panel's LinkedIn cards say "no
access" and give the reason.

## 5. Layout

### 5.1 Code

```
factory/
  __init__.py, __main__.py    version; calls cli.main()
  cli.py          argparse; commands of §12; output through poster.redact.Redactor
  paths.py        content dir, stock dir, rules file, factory state dir (resolution order §5.2)
  stock.py        folders, packages, validation, image refs (reuses poster.package, poster.rules)
  ruleset.py      rules.json schema, defaults, validation, atomic write with revision check
  planner.py      slot generation, package assignment, runway, run-out date, X projection
  runner.py       due slots, catch-up, claim journal, publish through poster.cli.main
  journal.py      runs.jsonl and heartbeat.json (uses the poster.state helpers, §5.4)
  stats.py        collectors per network, snapshots, latest.json        (lane L2)
  panel/          server.py, views.py, strings.py, static/panel.css, static/panel.js   (lane L3)
tools/
  visual_check.py headless-Chromium screenshots and layout probe (lane L3, §13.3)
tests/
  test_factory_*.py, test_panel_*.py
```

The factory imports these poster pieces. `package.load` validates packages. `rules.check_text`,
`rules.check_image` and `rules.sniff` run the per-network checks. `config.derived_targets`,
`config.resolve_env_path`, `config.resolve_state_dir` and `config.load_settings` give targets,
paths and settings. `xapi.estimate` prices X posts. `state.Records` and `state.Ledger` read the
publish record and the X ledger. `cli.main` is the publish path. The publish code itself
stays as it is.

### 5.2 Files and state

| What | Default location | Override | In git |
|---|---|---|---|
| Stock folders | `content/stock/<folder>/` | `MF_CONTENT_DIR` (parent of `stock/` and `rules.json`) | no (`content/` is ignored) |
| Rules | `content/rules.json` | same | no |
| Image library | `content/images/` | poster's `MF_IMAGE_LIBRARY` | no |
| Publish record, X ledger | poster state dir (`…/media-factory/poster/`) | poster's `MF_STATE_DIR` | no |
| Runner journal, heartbeat, stats | `${XDG_STATE_HOME:-~/.local/state}/media-factory/factory/` | `MF_FACTORY_STATE_DIR` | no |

The rules file sits in `content/` because it names the operator's targets and folders. The
factory state dir is created with mode `0700`, and its files with `0600`. Nothing secret is
written there.

### 5.3 Who writes and who reads each shared file

| File | Writers | Readers |
|---|---|---|
| `content/stock/**` | orchestrator (packages, after the operator's OK); panel ("+ new folder" writes only `folder.json`) | planner, runner, panel |
| `content/rules.json` | orchestrator by hand or through `factory rule …`; panel | planner, runner, `factory check`, panel |
| poster `posts.jsonl` | poster only (both the CLI and the runner's in-process calls) | planner, runner, stats, panel |
| poster `x-ledger.jsonl` | poster; stats (X reads, §10.3) | planner (X projection), panel |
| `runs.jsonl`, `heartbeat.json` | runner only | planner, panel, `factory status` |
| `stats/*.jsonl`, `stats/latest.json` | stats only | panel |

### 5.4 Poster changes

There is exactly one poster change. `poster/state.py` gets public names for its JSON Lines
helpers (`read_jsonl`, `append_jsonl`, `locked`), and the private names stay as aliases. No
publishing behaviour changes, and the existing poster tests stay green unchanged.

## 6. Stock

### 6.1 Folders and packages

A folder is a directory under `content/stock/` whose name matches `[a-z0-9][a-z0-9-]{0,39}`.
It holds:

- `folder.json`:

  ```json
  {"schema": 1, "title": "Quotes", "lane": "photo"}
  ```

  `lane` is `photo` or `text`. It groups folders on the Files tab, and a `text` folder may
  not feed Instagram (Instagram requires an image, poster §8).
- Post packages: every other `*.json` file, in the poster's package format (poster §5.1),
  unchanged. Images are library names or relative paths, as in the poster.

The publish order inside a folder is the file name order, so the orchestrator names files
`001-…json`, `002-…json`. A package's `id` (or its file name) must be unique across the whole
stock and must not appear in `content/packages/`, because the poster record is keyed by
package id. The runner keeps no queue of its own: the poster record decides which packages
are used (§8.2).

**Approval.** The operator's decision 1 (§1) holds for scheduled posts too. The orchestrator
shows the whole batch in chat (every variant of every package). After the operator's OK it
writes the packages into a stock folder with `"meta": {"approved_by_operator": "<date>"}`.
The poster ignores `meta` (poster §5.1). The factory never publishes a package without this
field, and the Files tab shows such a package as "not approved".

### 6.2 Package states (computed on each plan; nothing is stored)

| State | Rule | Shown as |
|---|---|---|
| `invalid` | `poster.package.load` fails, or a variant fails `check_text`/`check_image` for a network the folder's rules use, or the id is a duplicate | "needs fixing: <first problem>" |
| `not-approved` | no `meta.approved_by_operator` | "not approved" |
| `held` | the poster refused it on a slot (exit 2) for a problem in the package itself (schema, text, image) and the file has not changed since (same size and mtime), or it failed on every target on 2 slots in a row | "held: <reason>" |
| `check-account` | the poster record shows `unknown` for one of its targets, or a runner slot for it ended `interrupted` and is not yet resolved (§9.3) | "unknown — check the account" |
| `used` | published (or `already`) on every target of every active rule that reads the folder | greyed in the folder view |
| `ready` | none of the above | normal |

Only `ready` packages are assigned to slots. Validation reuses the poster's own checks, so a
package that is `ready` here passes the poster's pre-flight at run time, unless the operator
changes it in between.

### 6.3 Runway ("days left")

The video shows "70 of 90 days", "193 days ✓" and "nobody takes it · use 0"
(`frame-05m50s.png`, `frame-06m00s.png`). Ours:

- The run-out moment of a rule is the time of its first future slot that finds no `ready`
  package in the planner's simulation (§8.2). The simulation starts at now and stops at
  400 days.
- A folder's runway in days is `floor((min run-out over its active rules − now) / 1 day)`.
- Display: "N из 90 дней" with the bar filled to `min(N, 90)/90`. At N ≥ 90 it shows
  "N дней ✓". Past 400 days it shows "> 400 дней ✓".
- A folder with no active rule shows "никто не берёт · расход 0", as in the video. A draft
  rule's row (§11.6) shows the runway the folder would have if that rule were activated:
  the simulation runs on the active set plus that rule.
- The "content runs out" date in the Calendar header is the earliest run-out over all active
  rules, together with the rule's name.

## 7. Rules

### 7.1 File

`content/rules.json`, written as one JSON document:

```json
{
  "schema": 1,
  "limits": {
    "facebook":  {"max_per_day": 3, "min_gap_hours": 3},
    "instagram": {"max_per_day": 3, "min_gap_hours": 4},
    "linkedin":  {"max_per_day": 2, "min_gap_hours": 6},
    "x":         {"max_per_day": 4, "min_gap_hours": 2}
  },
  "rules": [
    {
      "id": "quotes-main",
      "folder": "quotes",
      "targets": ["fb:main", "ig:main", "linkedin", "x"],
      "days": ["mon", "wed", "fri"],
      "hours": ["10:00", "19:00"],
      "timezone": "Europe/Berlin",
      "status": "active",
      "active_since": "2026-11-12T08:30:00Z"
    }
  ]
}
```

- `id` matches `[a-z0-9][a-z0-9-]{0,39}` and is unique in the file.
- `main` in `fb:main` and `ig:main` is a placeholder for the main profile's Page name. Targets
  are the poster's own target ids (poster §5.4) and must exist among
  `config.derived_targets(env)`.
- `days` holds weekday codes `mon`–`sun`, at least one. `hours` holds whole hours from
  `"06:00"` to `"23:00"`, at least one, and is kept sorted. `timezone` is an IANA name checked
  with `zoneinfo`. The panel and `factory rule new` default it to the machine's zone.
- `status` is `draft` or `active`. `active_since` is set when the rule is activated and kept
  for display: the video shows "работает с 29 сентября" (`frame-06m05s.png`).
- `limits` is optional. Missing networks use the defaults of §7.2.
- One rule publishes a package to all of its targets in a single poster call, which is the
  poster's unit of publication (poster §8). Several rules may read one folder (§8.2).

### 7.2 Frequency limits

The video prints its limits as "our estimate, the platform has no exact number"
(`frame-06m00s.png`). Ours are labelled the same way.

| Network | Default max per day | Default min gap | Basis shown in the panel |
|---|---|---|---|
| Facebook | 3 | 3 h | "our estimate; no platform number is used" |
| Instagram | 3 | 4 h | "our estimate; API ceiling 50 posts per 24 h" (poster I6) |
| LinkedIn | 2 | 6 h | "our estimate; API ceiling 150 shares per member per day" (poster L11) |
| X | 4 | 2 h | "our estimate; the real limit is the $5 month cap" |

A day is the local calendar day in the timezone of the rule that creates the slot.

### 7.3 Validation and activation

`factory check`, `factory rule start ID` and the panel's ▶ button run the same function.
Activation is refused, and the file is left unchanged, when any of these holds:

1. the folder does not exist, or it has no `ready` package;
2. a target is unknown, or its env variable names are missing (names only, as in poster
   §7), or the LinkedIn token is expired;
3. the folder's lane is `text` and the targets include Instagram;
4. over the next 14 days of concrete slots (active rules plus this one), some network gets
   more than `max_per_day` posts in a day or two posts closer than `min_gap_hours`. The
   message names the day, the hours and the rules involved;
5. the projected X spend (§8.3) with this rule exceeds `X_MONTHLY_CAP_USD` in the current
   month or the next. The message gives the numbers, for example "X November: $1.12 spent +
   $4.30 planned = $5.42 of $5.00".

An active rule that is edited is validated again before the write. A draft rule is saved
without checks 4–5, but problems 1–3 are shown on its row.

### 7.4 Writing the file

Every writer (the panel, `factory rule …`) does the same steps. Take the exclusive flock
`rules.lock` next to the file. Read the file and compare its SHA-256 with the revision the
form or command was based on; on a mismatch, refuse with "rules changed elsewhere, reload".
Validate, write a temporary file in the same folder with mode `0600`, `fsync`, then
`os.replace`. Readers never take the lock, because `os.replace` makes each read see a whole
file. When the orchestrator edits the file by hand, the next `factory check` validates it.

## 8. Planner

`planner.plan(rules, stock, records, journal, ledger, settings, now, horizon)` is pure: it
reads nothing itself and returns the same result for the same inputs. `factory plan`, the
runner and the panel all use it.

### 8.1 Slots

For each rule, and each date in `[today − back, today + horizon]` in the rule's timezone whose
weekday is in `days`, every hour in `hours` gives one slot. `back` is 1 day for the runner,
which covers the 12-hour catch-up window, and goes back to the first month with a record for
the calendar. The local wall time is converted
to UTC with `zoneinfo`. When the clock jumps forward and a local time does not exist, the
slot moves to the first valid minute after it. When the clock falls back and a local time
occurs twice, the first occurrence (`fold=0`) is used. The slot key is
`<rule id>@<UTC ISO time>`.

### 8.2 Assigning packages (shared by plan and runner)

Slots are processed in time order, ties broken by rule id. Each future slot of an active rule
takes the first package, in its folder's order, that meets all of these:

- the package is `ready` (§6.2) and has a variant for at least one of the rule's targets;
- for every rule target that has a variant, no source shows that (package, target) as
  taken. The sources are: the poster record (`published` or `unknown`); the runner journal
  (a slot `claimed` without a terminal entry, `interrupted` and not resolved, or resolved
  as published, §9.3); and earlier slots in this simulation.

A package that partly failed on an earlier slot (published on some targets) is therefore
not taken again. Its failed targets surface as an attention item (§9.5), and `factory retry`
handles them. A package that failed on every target is taken again by the next slot; after 2
such slots it becomes `held`.

Slot states in the plan:

| State | Meaning |
|---|---|
| `planned` | will publish package P to targets T |
| `no-content` | no `ready` package left (the run-out moment, §6.3) |
| `over-limit` | would break a §7.2 limit (possible only after a manual edit that skipped validation) |
| `over-budget` | its X part would push the month past the cap; the runner publishes it without X (§9.4) |
| `draft` | the rule is a draft; shown greyed with "правило не запущено", as in `frame-06m11s.png` |

Past slots take their state from the runner journal (§9.3). Publications made by hand with
the poster CLI appear from the poster record as "published (manual)".

### 8.3 Outputs

- **Calendar:** slots from the first month that has a record up to the horizon (default 120
  days), with per-day and per-network counts. A count is the number of publications, that is
  slot × targets with a variant, matching the video's "203 публикаций в неделю".
- **Posts per week:** the planned publications of the next 7 days.
- **Rules running:** "K правил в работе · ещё M в черновике" (the video: "9 правил в бою · ещё 70
  в плане").
- **Runway** per folder and the **content-runs-out** date (§6.3).
- **X projection** for the current and the next calendar month (UTC, the ledger's month):
  the amount spent so far (`Ledger.month_total`), plus `xapi.estimate(text, has_image)` for
  every planned X slot's actual package, plus planned X stats reads (§10.3, only when on).
  At the poster's default prices, for example, three image posts a week cost about
  13 × $0.215 = $2.80 a month.

`factory plan [--days 30] [--rule ID]` prints:

```
plan 2026-11-10 → 2026-12-10 (machine tz Europe/Berlin)
rules: 1 active, 1 draft     publications next 7 days: 12     content runs out 2026-12-19 (quotes-main)
X 2026-11: spent $0.230 + planned $1.720 = $1.950 of $5.00     X 2026-12: planned $2.795
folders
  quotes   photo  14 ready  1 not approved   runway 39 of 90 days (until 2026-12-19)
  tips     text    6 ready                    nobody takes it · use 0
slots
  2026-11-11 Wed 10:00 CET  quotes-main  001-focus.json   fb:main ig:main linkedin x
  2026-11-11 Wed 19:00 CET  quotes-main  002-habits.json  fb:main ig:main linkedin x
  …
```

## 9. Runner

### 9.1 Tick and timer

`python3 -m factory tick` is a short one-shot process. It:

1. takes the non-blocking flock `runner.lock` (when another tick holds it, it prints "tick
   already running" and exits 0);
2. publishes due slots (§9.2–§9.4);
3. runs the stats collection when it is due (§10.2, lane L2);
4. atomically rewrites `heartbeat.json` (`{"ts", "version", "due", "published", "errors"}`,
   one small object rather than an append, so it stays bounded).

Timer: a systemd **user** timer, which needs no root. This machine runs systemd in WSL2 with
user lingering enabled (observed 2026-11-10: `ps -p 1` → `systemd`;
`systemctl --user is-system-running` → `running`; `loginctl … Linger=yes`).
`factory timer --print` prints the two units, filled with the checkout's absolute path, and
the commands to enable them. The orchestrator installs them only with the operator's
consent.

```
# ~/.config/systemd/user/media-factory-tick.service
[Unit]
Description=Media factory: publish due slots, collect daily stats
[Service]
Type=oneshot
WorkingDirectory=<checkout>
ExecStart=/usr/bin/python3 -s -B -m factory tick
TimeoutStartSec=30min

# ~/.config/systemd/user/media-factory-tick.timer
[Unit]
Description=Media factory tick every 5 minutes
[Timer]
OnCalendar=*:0/5
AccuracySec=30s
[Install]
WantedBy=timers.target
```

Enabling: `systemctl --user daemon-reload` then
`systemctl --user enable --now media-factory-tick.timer`. systemd does not start a oneshot
unit that is still running, and `runner.lock` is a second guard, so a slow Instagram publish
(up to 5 minutes of container polling, poster §9.2) cannot overlap with the next tick. The
timer does its own catching up (§9.2), so `Persistent=` is not needed.

`-s -B` keeps user site-packages out and does not write `__pycache__` into the checkout.
`-I` is not used because it would drop the working directory from `sys.path`.

### 9.2 Due slots, on time and after downtime

At each tick the runner computes the plan's slots with `when ≤ now` that have no terminal
journal entry yet (`done`, `refused`, `missed`, `interrupted`).

- **On time** (`now − when ≤ 15 min`): published, oldest first.
- **Late, inside the catch-up window** (15 min < `now − when` ≤ 12 h): per rule, only the
  latest such slot is a candidate. Candidates run newest first, and each network gets at
  most one catch-up publication per tick. Before publishing, the runner also checks
  `min_gap_hours` against the last real publication on that network in the poster record
  (manual ones count). A candidate that would break this is marked `missed` with reason
  `gap`.
- **Older than 12 h**, and catch-up candidates not chosen, are marked `missed` with reason
  `off` or `superseded`.

No content is lost. A missed slot never consumed its package, so assignment (§8.2) gives
that package to the next slot, and the queue shifts by itself. After a weekend with the
computer off, Monday's first tick publishes at most one post per network, and the plan
continues from there. This is the form's "posts wait while the computer is off".

The run-time limit check (§7.2) also counts publications made by hand. A slot that would
break a limit is marked `missed` with reason `limit`, and its content shifts.

### 9.3 Journal and re-run safety

`runs.jsonl` is append-only. Writes go under `runs.lock`, using the poster's JSON Lines
helpers, which repair a torn last line.

```json
{"ts":"2026-11-11T09:00:04Z","slot":"quotes-main@2026-11-11T09:00:00Z","rule":"quotes-main","folder":"quotes","package":"001-focus","targets":["fb:main","ig:main","linkedin","x"],"status":"claimed"}
{"ts":"2026-11-11T09:01:31Z","slot":"quotes-main@2026-11-11T09:00:00Z","status":"done","exit":1,"outcome":{"fb:main":"published","ig:main":"published","linkedin":"failed","x":"published"},"summary":"<last 20 redacted poster lines, at most 2000 chars>"}
```

Terminal statuses are `done`, `refused` (poster exit 2, with its reason), `missed` (`off`,
`superseded`, `gap`, `limit`) and `interrupted`.

- The runner appends `claimed` before it calls the poster. A slot with any `claimed` entry
  is never published automatically again. That is what makes re-running safe: the same tick
  run twice, or two ticks at once, publish a slot once. On top of that, the poster's own
  record skips targets that are already published (poster §11.1).
- **Crash after `claimed`, before `done`:** a tick holds `runner.lock` for its whole run, so
  a `claimed` slot without a terminal entry can only come from a tick that died. The next
  tick reconciles it. If the poster record
  has events for that package and those targets after the claim time, it writes `done` from
  them. Otherwise it writes `interrupted`, which the poster may or may not have acted on.
  It is not retried automatically, because publishing is not idempotent (poster §9.6). The
  package counts as taken for those targets (§8.2), so no later slot can post it twice.
  The attention item says "check the account". The operator then records what they saw
  with `factory resolve <slot> --published` or `--not-published`. That appends a `resolved`
  entry: published keeps the package taken; not published releases it to the next slot.

### 9.4 Publishing through the poster

For each slot it publishes, the runner:

1. re-validates the package (§6.2). If it is no longer `ready`, the slot is `refused` and
   the package is `held`;
2. **X budget:** when the targets include `x` and the package has an `x` variant, it calls
   `Ledger.check(xapi.estimate(...), cap)`. If the cap would be exceeded, `x` is dropped
   from this slot's targets and the journal records `x: skipped (budget)`. The free networks
   publish on schedule, X spends nothing, and the attention item asks the operator (§17
   item 1);
3. calls `poster.cli.main(["--env-file", ENV, "publish", PATH, "--targets", "t1,t2,…"],
   environ=…, stdout=buf, stderr=buf)` in the same process. This is the existing publish
   path, so pre-flight, the X ledger reservations, redaction, partial-failure isolation and
   the record are the poster's own;
4. maps the result: exit 0 gives `done` with every target `published` or `already`. Exit 1
   gives `done` with per-target outcomes from `Records.latest(package, target)`
   (`published`, `failed`, `unknown`). Exit 2 gives `refused`, with the reason taken from
   the captured output. When the reason is in the package itself (schema, text, image), the
   package is `held` until its file changes. When it is not (missing variables, an expired
   token), only the slot is refused, and the attention item names the fix.

Failed targets are not retried by the next tick. `factory retry <slot>` runs the same publish
again for that slot's targets: the poster skips published targets and retries failed ones.
`retry` refuses `unknown` targets and points to the poster's `--force-target` after the
operator has checked the account.

### 9.5 Attention items

These are computed on demand, not stored, and shared by `factory status` and the panel's
bell:

- slots `done` with failed targets, slots ending `unknown` or `interrupted`, `refused` slots;
- `x: skipped (budget)` this month, and an X projection above 80 % of the cap;
- content runs out within 14 days;
- packages that are `invalid`, `not-approved` or `held`;
- the LinkedIn token expires within 7 days (poster rule) or has expired;
- no heartbeat for more than 30 minutes while rules are active ("the timer is not running");
- stats: the last collection failed, or a permission is missing (§10.4).

## 10. Stats (lane L2)

### 10.1 What is read

| Network | Followers | Per post | Permissions | Cost | Default |
|---|---|---|---|---|---|
| Facebook Page | `GET /{page_id}?fields=followers_count` (F1) | `GET /{post_id}?fields=shares,reactions.summary(total_count).limit(0),comments.summary(true).limit(0)` (F2); `GET /{post_id}/insights?metric=post_media_view` (F3) | `pages_read_engagement` (F1, F2); plus `read_insights` and a Page with ≥ 100 likes for views (F3) | $0 (M1) | on |
| Instagram | `GET /{ig_user_id}?fields=followers_count,media_count` (I1) | `GET /{media_id}?fields=like_count,comments_count,permalink,timestamp` (I2); `GET /{media_id}/insights?metric=views,reach,saved,shares,total_interactions` (I3) | `instagram_basic`, `pages_read_engagement` (I1, I2); plus `instagram_manage_insights` (I3) | $0 (M1) | on |
| X | `GET /2/users/me?user.fields=public_metrics` (X3) | `GET /2/users/{id}/tweets?max_results=N&<fields>=public_metrics&start_time=<30 days ago>` (X4, X5) | user token (OAuth 1.0a, the poster's signer handles query parameters) | $0.010 per user read; $0.005 per post read, or $0.001 at the Owned Reads rate (X1, X6) | **off** |
| LinkedIn | — | — | needs the Community Management API, available only to organizations (L3) | — | not built |

Missing metrics are stored as absent, never as 0. Instagram returns an empty set for
unavailable data (I3), and Facebook returns nothing for views on Pages under 100 likes (F3).

### 10.2 Schedule and bounds

- Collection runs once a day: on the first tick after 06:00 machine time when the last
  successful collection is more than 20 hours old. `factory stats collect` forces a run.
- Post metrics are read daily for posts up to 30 days old and weekly for posts 31–90 days
  old. After that the last value is kept. So the calls per day are bounded by the posts of
  the last 30 days plus one seventh of the posts from days 31–90.
- Followers are read once a day per account.
- Posts come from the poster record (`published`, not later `deleted`). The record holds the
  Facebook post id, the Instagram media id, the X post id and the LinkedIn URN.

### 10.3 X reads (off by default)

The setting is `X_STATS` in the env file: `off` (default) or `weekly`. When it is `weekly`,
the collector runs on Mondays. It reserves the cost in the poster's X ledger before each
request (`op` = `read_user` or `read_posts`), so X reads and X posts share the one $5 cap.
`max_results` is the number of X posts in the record from the last 30 days, which keeps the
estimate exact. Prices are the settings `X_PRICE_READ_USER` (default `0.010`) and
`X_PRICE_READ_POST` (default `0.005`, lowered to `0.001` once X6 is confirmed). For
example, with 20 X posts in the window, weekly reads cost 4 × (0.010 + 20 × 0.005) =
$0.44 a month at the default prices. If the reservation would pass the cap, the reads are
skipped and the panel says so. The planner counts planned weekly reads in the X projection.

### 10.4 Storage and probe

- `stats/followers.jsonl`: `{"date","target","network","followers"}`, one row per account
  per day.
- `stats/post-metrics.jsonl`: `{"date","target","network","post_id","views","reach","likes","comments","saves","shares","reposts"}`.
  Keys a network does not provide are left out.
- `stats/latest.json`: written atomically after each collection. It holds the latest
  metrics per post and each account's daily follower series (at most 400 points per
  account). This is the bounded artifact the panel reads, so the panel never parses the
  history files.
- `stats/collect.json`: the last run's time and per-target result (`ok`, or
  `no-permission <name>`, `token rejected`, `HTTP n code c`), redacted.
- `factory stats probe` makes one free read-only call of each kind per Meta target (a
  follower field, the newest post's fields, its insights) and prints, per call, `readable`
  or the missing permission named in the error. It does not call X unless given `--x`, and
  then only after a ledger reservation. It writes nothing. This is the check for S1 and S2.

## 11. Panel (lane L3)

### 11.1 Stack and server

- `python3 -m factory panel [--port 8770]` starts a `ThreadingHTTPServer` bound to
  `127.0.0.1`. If the port is taken it stops with "port in use, pass --port". Tests bind
  port 0.
- Pages are rendered on the server with f-strings and `html.escape` (in `views.py`). There
  are two static files: `panel.css`, and `panel.js` of about 150 lines (it opens dialogs,
  submits toggles on click and moves to the `#today` anchor). With JS off, every action
  still works as a plain form POST followed by a redirect (POST/redirect/GET).
- There is no build chain, no web fonts and no network icons. Fonts are system stacks: sans
  `ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif`; mono
  `ui-monospace, "Cascadia Mono", "JetBrains Mono", Consolas, monospace` (the video sets
  numbers and meta in mono, `frame-06m17s.png`). Networks appear as two-letter monograms
  (§11.2), never as third-party logo files.
- **Server-side checks.** These keep the promises "local only" and "never shows a secret":
  - every request: the `Host` header must be `127.0.0.1:<port>` or `localhost:<port>`,
    otherwise 421. This blocks DNS rebinding;
  - every POST: `Origin` (when present) must match the Host. The form field `csrf` must
    equal a 32-byte random token made at server start and embedded in pages. Otherwise 403.
    A page from another site in the operator's browser can neither read the token nor post
    without it, so it cannot activate a rule;
  - images: `/img?folder=F&file=P&ref=R` resolves the reference the way `poster.package`
    does. It requires that `realpath` lies inside the library or that folder, and that the
    file sniffs as JPEG, PNG, GIF or WEBP (`poster.rules.sniff`). Otherwise 404. A request
    like `ref=../../.env` gets 404;
  - env values: the panel reads only variable names and `LINKEDIN_TOKEN_EXPIRES_AT`. Error
    text from journals and stats passes through `poster.redact.Redactor` loaded with the env
    file. A test plants canary secrets and asserts that no page contains them.
- **Snapshot cache.** There is one snapshot object, owned by the server. Its key is the
  `(mtime_ns, size)` of `rules.json`, of every stock folder and package (one `os.scandir`
  stat walk), of `posts.jsonl`, `x-ledger.jsonl`, `runs.jsonl`, `stats/latest.json` and the
  env file, plus the current minute. The plan is recomputed only when the key changes, and
  the cache holds exactly one entry, replaced on change. A request costs one stat walk.
  Content reads happen only after a change. The publish record is small (about 4 lines per
  publication). If it ever passes 50 000 lines, the snapshot should read the file from its
  last offset instead of from the start; at today's volume that is not needed.

### 11.2 Visual style

Colours were sampled from the frames with the cached Chromium (dominant colour in each
region, 2026-11-10). Text colours that failed contrast in the video were lightened to meet
4.5:1. The ratios below were computed with the WCAG formula.

| Token | Value | Sampled from | Use | Contrast check |
|---|---|---|---|---|
| `--page` | `#000000` | outside the app, `frame-05m33s.png` | page background | — |
| `--app` | `#080808` | app body | main canvas | — |
| `--surface` | `#141414` | folder cards, day cells, follower cards (`frame-05m50s.png`, `frame-06m09s.png`, `frame-06m33s.png`) | cards, tab bar | — |
| `--surface-2` | `#18181c` | alternate rule row (`frame-06m00s.png`) | zebra rows, chips | — |
| `--head` | `#202028` | rules header row | table header, monogram disc | — |
| `--tab-active` | `#38383c` | active tab | active tab pill | — |
| `--text` | `#f0f0f4` | titles and numbers | primary text | 16.2:1 on `--surface` |
| `--muted` | `#8e8e93` | video uses `#6c6c70` (3.5:1, too low) | labels, meta | 5.7:1 on `--surface`, 5.0:1 on `--head` |
| `--green` | `#54ac5c` | views numbers, runway bars, active sort button (`#4cac54`) | growth, runway, active filter | 6.5:1 on `--surface` |
| `--on-green` | `#0a0a0a` | — (white on green is 2.9:1) | text on green buttons | 6.9:1 |
| `--red` | `#ff4d4f` | the "content runs out" date (`crop-06m09s-calendar.png`) | run-out date, decline, failures | 5.6:1 on `--surface` |
| `--day-on` | `#142818` bg, `#98d8a4` text | active weekday toggle | weekday on | 9.4:1 |
| `--hour-on` | `#182830` bg, `#74a4e0` border | selected hour cell | hour on | — |
| `--lane-photo` | `#e8c47c` | top edge of the photo lane cards | lane accent (with lane title) | — |
| `--lane-text` | `#74a4e0` | top edge of the article lane cards | lane accent (with lane title) | — |

Network monograms are a 22 px disc in `--head` with the letters in the network colour:
FB `#7aa7ff`, IG `#ff7ab6`, X `#f0f0f4`, in `#6cb4f0` (built), and TG `#6cc8f0`, TH
`#d8d8dc`, YT `#ff7a7a`, TT `#d8d8dc`, PI `#ff8a8a` (not built, drawn at 40 % opacity and
labelled "не построено"). Every letter colour is at least 6.4:1 on `#202028`.

Shell: a black page. The app is a rounded (12 px) `--app` container with `max-width:
1440px`, centered, 16 px outer margin. A sticky tab bar sits at the top
(`frame-05m33s.png`). The tab pill is 34 px tall with an icon-less label. The active tab is
`--tab-active` with `--text`; the others are `--muted`.

Widths: the panel targets desktop browsers. The named widths are **1280×800** and
**1920×1080**, and 1600×900 is checked between them. Below 1380 px of container width, the
Rules row wraps into two lines (§11.6). Every other tab is a fluid grid without horizontal
scroll at 1280.

### 11.3 Shell: tab bar, top right, bell

Modeled on `frame-05m33s.png` and `frame-06m09s.png`.

- Tabs (Russian, the video's words): Подключение · Файлы · Правила · Календарь · Охваты ·
  Подписчики · Диалоги. Диалоги is a `<span aria-disabled="true">` that reads
  "Диалоги · выкл", not a link (§11.10).
- Top right, replacing the video's storage meter and seat count:
  - a bell with the attention count as text in a badge (§9.5). Activating it expands an
    "Attention" strip under the tab bar that pushes the content down rather than overlaying
    it. Each item is a link to the tab and row it concerns;
  - the X meter: a bar plus "X ноябрь $0.23 из $5.00 · план +$1.72";
  - "LinkedIn: 41 дн." (or "LinkedIn: нужен вход");
  - "таймер: 2 мин назад", from `heartbeat.json`. It turns into red text "таймер молчит
    35 мин" after 30 minutes while rules are active.
- Each tab's sub-header line sits under the tab bar (the video's "5 из 9 сетей подключено",
  "14 папок", `frame-05m33s.png`, `frame-05m50s.png`).

### 11.4 Подключение (Connection)

Modeled on `frame-05m33s.png`, `crop-05m44s-ring.png` and `crop-05m46s-ring.png`.

- **Data:**
  - targets from `config.derived_targets(env)` (names only), grouped as "основной профиль"
    for the poster's main profile, with any other Page targets listed under it;
  - per network, a state with a text label: `подключено` (all variables present, and the
    last publish or stats read was not an auth error), `нужен вход` (LinkedIn variables
    missing or token expired), `ошибка токена` (the last call answered Graph code 190, M2,
    or HTTP 401 from X or LinkedIn),
    `нет ключей` (variables missing);
  - LinkedIn token days; the last publish (time and link) and the last stats read per
    target.
- **Layout:**
  - left column "АККАУНТЫ" with one row per profile and the monograms of its targets
    coloured by state;
  - right, the ring of 9 network slots. The center reads "N из 4", with "сети постера" under
    it. The ring arc is filled N/4 in `--green`, as in `crop-05m44s-ring.png`;
  - hover or focus on a node shows its name, as the video's tooltip in
    `crop-05m46s-ring.png` does;
  - selecting a node shows its details card under the ring: variable names with
    present/missing, token expiry, last publish, last stats read, and how to connect (for
    example `python3 -m poster login linkedin`).
- **Actions:** none that write. The video's one-click aggregator button is not copied
  (§18).

### 11.5 Файлы (Files)

Modeled on `frame-05m50s.png`.

- **Data:** stock folders grouped by lane. For each folder:
  - title, and three preview tiles: images for the photo lane, the first lines of text for
    the text lane, as in the video's article tiles;
  - a "+N" tile;
  - "N пакетов" (ready + used), the runway bar and label (§6.3), and the monograms of the
    targets of the rules that read the folder;
  - a red text line "нужно исправить: K" or "не одобрено: K" when such packages exist.
- **Layout:**
  - lane headers "Фото-посты · 2 папки · 31 пакет" and "Текстовые посты · …", with a thin
    rule and a 3 px top edge on the cards in the lane colour;
  - cards are 220 px wide in a wrapping grid;
  - the last card in each lane is dashed: "+ Фото-посты / новая папка в этой полосе".
- **Folder view** (click a card): packages in publish order. Each row shows the file, the
  theme, a preview of each variant's text (first line plus "…") with its network monogram,
  the image tile, and per-target state: `опубликован · дата · открыть`, `запланирован ·
  дата`, `ждёт`, or the §6.2 state with its reason.
- **Actions:** "+ new folder" (a form with name and lane; it writes `folder.json` only).
  Package files are written by the orchestrator in chat, after approval.

### 11.6 Правила (Rules)

Modeled on `frame-06m00s.png` (draft rows), `frame-06m05s.png` and `crop-06m05s-rules.png`
(running rows).

- **Header:** network filter chips with counts ("Все 3", "FB 2", "IG 1", …), as in the
  video's icon row. A chip with a running rule carries a small green dot plus the count text.
- **Columns:**
  1. **Пуск.** A 40 px round button. ▶ with "черновик" under it for a draft; ■ with
     "работает с 12 ноября" for an active rule.
  2. **Аккаунт.** "основной профиль", with the target monograms and ids under it.
  3. **Откуда брать контент.** A mini folder card: title, count, lane chip, and the runway
     bar "39 из 90 · до 19 дек.". A draft rule shows the runway it would have if activated.
  4. **Куда публиковать.** The format, derived as "Пост с фото" for the photo lane and
     "Текст" for the text lane, plus the target list. It is read-only.
  5. **Дни недели.** Seven 30×28 toggles Пн…Вс, then "3 дня в неделю · снять все" or
     "выбрать все".
  6. **Время публикаций.** A 6×3 grid of 42×28 cells, 06:00–23:00. Under it:
     "2 раза в день · 6 в неделю" and, for each network of the rule, its limit hint from
     §7.2 in `--muted`.
  7. **Часовой пояс.** An input with a datalist of `zoneinfo.available_timezones()`, showing
     the UTC offset ("Europe/Berlin · UTC+1").
- **Under the row:** validation problems (§7.3) as text with `role="alert"`, and for rules
  with X: "X: ≈$0.65 в неделю".
- **Footer:** "+ Новое правило" (pick a folder, a target set, days, hours and a zone; it is
  saved as a draft).
- **Actions:** each one is a POST carrying `csrf`, the rules-file revision, the rule id and
  the change. The write goes through §7.4. Start and stop run §7.3.
- **Width:** the grid track widths are fixed in CSS grid with no flex shrinking.
  - At ≥ 1380 px of container: one line with tracks 96 / 150 / 270 / 150 / 250 / 290 /
    160 px plus gaps.
  - Below that: two lines through `grid-template-areas` ("start account source target" /
    "start days hours tz").
  - The L3 visual check measures that no cell's text overflows at 1280, 1600 and 1920
    (§13.3).

### 11.7 Календарь (Calendar)

Modeled on `frame-06m09s.png`, `frame-06m14s.png` and `crop-06m09s-calendar.png` (month
grid and header), and `frame-06m11s.png` (day window).

- **Header:**
  - a "сегодня" button, which jumps to `#today`, and the current month's title;
  - on the right, three stats: "12 публикаций в неделю", "1 правило в работе · ещё 1 в
    черновике", and the run-out date in `--red` with "контент кончится · quotes-main" in
    `--muted` under it. When nothing runs out within the 400-day simulation (§6.3) it
    reads "> 400 дней".
- **Filter:** network chips with counts ("Все 48", "FB 12", …).
- **Grid:**
  - stacked months: the previous one, the current one and the next three, with a "показать
    ещё 3 месяца" link at the end; each month title carries "N публикаций";
  - week rows Пн…Вс;
  - each day cell shows the day number, the total in the top-right corner, and up to 4
    network chips "IG 2" (monogram plus count), then "+N";
  - past days are drawn at 60 % opacity, and today has a 1 px `--green` outline and the word
    "сегодня";
  - a day without slots is empty.
- **Day window:** a native `<dialog>` opened with `showModal()`, so the page behind it is
  inert. Without JS the URL `?day=YYYY-MM-DD` renders the same list as a section at the top
  of the page. The title is "12 ноября · ср · сегодня", with "N публикаций" and a close
  button. There is one row per slot × target:
  - time with the zone abbreviation (`10:00 CET`), as the video's "01:00 LA";
  - the image tile (or the first text line), the monogram and the target;
  - the state text: `опубликован · 001-focus · открыть` (link with `target="_blank"
    rel="noopener"`, as in `frame-06m31s.png`), `ошибка: 401 token expired`,
    `неизвестно — проверьте аккаунт`, `пропущен: компьютер был выключен`,
    `пропущен: лимит FB 3 в день`, `X пропущен: бюджет`, `quotes → FB IG in X` (planned),
    `нет контента` (red text), or `правило не запущено` (a muted tag, as in the video).
- **Actions:** none that write.

### 11.8 Охваты (Reach)

Modeled on `frame-06m17s.png` (Popular), `frame-06m25s.png` and `crop-06m25s-reach.png`
(Weak), and `frame-06m31s.png` ("open" opens the post in a new tab).

- **Data:** every `published` (not deleted) post from the poster record, joined with
  `stats/latest.json`.
  - Totals line: "N публикаций · просмотров · лайков · комментариев", summed over the posts
    shown. Absent metrics are not counted.
  - Network chips with counts.
  - Sort buttons: Популярные (views descending; posts without views fall back to likes +
    comments + shares, and are sorted after posts with views) · Слабые (the same order
    ascending; the video shows its zero-view posts here) · Свежие · Старые · По лайкам.
    The active one is `--green` with `--on-green` text.
- **Row:**
  - a 48 px image tile and two lines of the variant's text (clamped);
  - under it, mono `2026-11-11 · fb:main · открыть`;
  - on the right, a column per metric with a mono number and a label under it: views
    (`--green`, 20 px), likes, comments, saves, reposts. Metrics are shown as "—" when the
    network does not provide them, as the video does for some networks
    (`frame-06m25s.png`);
  - numbers are abbreviated the Russian way, "7,1 млн" and "70 тыс", as in the video.
- **Empty states:** "Статистика ещё не собиралась — `python3 -m factory stats collect`"
  before lane L2's first run. "Нет доступа: <permission>" per network when the probe found
  one missing.
- **Actions:** sorting and filtering only. These are links with query parameters
  (`?sort=weak&net=instagram`).

### 11.9 Подписчики (Followers)

Modeled on `frame-06m33s.png`.

- **Header:** "N подписчиков · K аккаунтов", and the period buttons Неделя · 30 дней ·
  90 дней · Всё время (`?period=`).
- **Cards:** a grid of 3 columns at ≥ 1380 px and 2 below, sorted by followers descending.
  Each card holds:
  - the monogram and the target label;
  - the big number (mono 28 px) and the delta for the period: "+2 025" in `--green`,
    "−12" in `--red`, "0" in `--muted`. The sign is always written, so colour is never the
    only signal;
  - an inline SVG area sparkline of the daily points. It is green when the period's delta
    is ≥ 0 and red when it is below;
  - "за 18 дней", the days of data actually present in the period.
- **Special cards:** "LinkedIn · нет доступа: статистика профиля только для организаций
  (Community Management API)"; "X · выключено: чтение X платное (X_STATS=off)".
- **Actions:** the period switch only.

### 11.10 Диалоги (Dialogs), disabled placeholder

Modeled on `frame-06m56s.png`, which shows the feature that is not built. In the tab bar it
is a non-interactive label "Диалоги · выкл" in `--muted`, not a link. A direct `/dialogs`
request returns a short page: "Помощник в директе не подключён (отложено)", plus the
reasons from §18.

### 11.11 Language and strings

All UI strings live in `panel/strings.py` as one Russian table: the video's words, and the
language the operator writes in. Dates are formatted in Russian ("12 ноября", "19 дек."). A
second language later is a second table, not a refactor.

## 12. CLI summary

```
python3 -m factory [--env-file PATH] [--content DIR] [--state-dir DIR] <command>

check                        validate stock and rules; exit 0 ok, 2 problems (listed)
plan [--days N] [--rule ID]  calendar, runway, run-out, X projection (§8.3)
tick [--dry-run]             publish due slots, daily stats, heartbeat (§9.1)
status                       last tick, next 5 slots, attention items, X month, LinkedIn days
retry SLOT                   re-publish a done slot's failed targets (§9.4)
resolve SLOT --published|--not-published   record the account check for an interrupted slot (§9.3)
rule new|start|stop ID       create a draft, activate (§7.3), back to draft
rule set ID [--days mon,wed] [--hours 10:00,19:00] [--timezone Z] [--targets T,…] [--folder F]
                             CLI equivalents of the Rules tab edits (§7.4)
timer --print                systemd user units and enable commands (§9.1)
stats probe [--x] | collect  §10.4                                          (lane L2)
panel [--port 8770]          local web panel on 127.0.0.1 (§11)             (lane L3)
```

`tick --dry-run` lists what would publish now and why the other due slots would be skipped.
It calls the poster with `--dry-run` and writes nothing. Exit codes follow the poster's:
`0` ok, `1` a slot ended failed, unknown or interrupted, `2` usage or validation error.

## 13. Slices (build lanes)

Core first, panel second: **L1 → L2 → L3**. L2 and L3 touch different files, and L3 reads
L2's outputs only through the schema fixed in §10.4. So if the operator wants the panel
sooner, L3 may start right after L1, and Reach and Followers then show their empty states
until L2 lands.

### 13.1 L1: Queue and schedule (core)

- **Builds:** `factory/` without `stats.py` and `panel/`; the §5.4 poster helper names; a
  Russian README section "Завод" (stock folders, approval field, rules file, `plan`, `tick`,
  `status`, `retry`, timer install, where state lives).
- **Acceptance:**
  1. `factory plan` on a fixture stock (2 folders, 2 rules, 1 draft) prints the §8.3 shape.
     Assignment, runway, run-out date, publications per week and the X projection match
     hand-computed values, and two runs on the same inputs give byte-identical output.
  2. `factory check` refuses each §7.3 case with its message, and leaves `rules.json`
     unchanged (same hash).
  3. `tick` with a fake clock and a fake poster entry point publishes an on-time slot once.
     A second `tick` in the same minute, and two concurrent ticks, call the poster once in
     total.
  4. A crash injected after `claimed` makes the next tick write `interrupted`, or `done`
     when the record shows the events. It never calls the poster again, and no later slot
     is assigned that package for those targets until `resolve … --not-published`.
  5. Downtime: the clock jumps 3 days ahead with slots in between. One tick publishes at
     most one slot per network, marks the rest `missed`, and the next planned slot gets the
     next package (nothing is lost or skipped in the stock).
  6. X over the cap: the slot publishes the other targets, and the journal shows
     `x: skipped (budget)` with zero X ledger rows for it.
  7. Daylight saving: slots on both sides of the spring and autumn transitions of a
     European zone keep their local wall time, and their UTC time moves by one hour. A
     unit test of the slot function with a non-existent and a repeated local time follows
     §8.1.
  8. Approval: a package without `approved_by_operator` is never assigned.
  9. `tick --dry-run` creates no file and no folder (checked by listing the state dirs
     before and after).
- **Checks:**
  - `python3 -I -B -m unittest discover -s tests -t .` (the project's command, README "Тесты"),
    all green including the unchanged poster tests;
  - no network: the poster's `tests/base.py` socket guard stays in force;
  - `git status --short --ignored` clean after the tests.
- **Live smoke** (operator OK required): one draft rule to a test Page the operator names,
  with one approved text package, set to the next whole hour. Then: `rule start`, install
  the timer, wait for the hour, check that `records` shows one post and that `tick` re-run
  by hand publishes nothing. Delete the post with the poster's `delete`, then `rule stop`.
  No other network is touched.
- **Operator provides:**
  - the first rules: which folders go to which networks, days and hours. A starter
    proposal is one photo folder to all four networks, Mon/Wed/Fri at 10:00, about $2.80 of
    X a month;
  - approval of the first batch in chat;
  - consent to install the user timer;
  - the name of the test Page for the smoke.

### 13.2 L2: Stats (core)

- **Builds:** `factory/stats.py`, `stats probe`, `stats collect`, the daily step in `tick`,
  `X_STATS` and the two read prices, and a README paragraph.
- **Acceptance:**
  1. With a fake transport, collection writes the §10.4 rows for Facebook, Instagram and,
     with `X_STATS=weekly`, X. Absent metrics are left out, not zero.
  2. With `X_STATS=off` (the default) the transport sees zero requests to `api.x.com`, and
     the ledger gets no rows.
  3. With `X_STATS=weekly`, every X read is reserved before it is sent. A reservation over
     the cap skips the reads and records `skipped (budget)`.
  4. A permission error (Graph code 10 or 200–299, M2) becomes `no-permission <name>`, with
     the permission name taken from the error message as in the observed answer of F4
     ("requires the '…' permission"). Code 190 becomes `token rejected`. Collection
     continues with the other targets.
  5. `latest.json` is written atomically and stays within its bounds.
  6. Canary secrets never appear in output or files.
- **Checks:** the project's test command. Live: `factory stats probe` on the main profile
  (free, read-only); it settles S1 and S2.
- **Operator provides:** if the probe shows missing permissions, a Meta Page token re-issued
  with `pages_read_engagement`, `read_insights` and `instagram_manage_insights` (written to
  the env file under the existing names). A choice on X stats: off (default) or weekly
  (about $0.44 a month at 20 posts, inside the shared $5 cap).

### 13.3 L3: Panel

- **Builds:** `factory/panel/`, `tools/visual_check.py`, and a README paragraph (how to
  start it, the URL, how to stop it with Ctrl+C).
- **Acceptance:**
  1. Every tab renders from a fixture with real-shaped data: at least 2 lanes, 5 folders, 3
     rules (1 draft, 1 with a validation problem), 60 days of history including failed,
     unknown, missed and over-budget slots, 40 posts with metrics, and 4 follower series
     with one negative delta. The empty-state fixture has no stock, no rules and no stats.
  2. **Security** (`http.client` tests against port 0):
     - a wrong `Host` gets 421;
     - a POST without `csrf`, or with a foreign `Origin`, gets 403 and leaves `rules.json`
       unchanged;
     - `/img` with `..`, an absolute path, a symlink out of the root or a non-image file
       gets 404;
     - no canary secret appears in any page.
  3. **Rules actions:** toggling a day, toggling an hour, changing the zone, starting,
     stopping and creating a rule each change exactly that field. A stale revision is
     refused with "rules changed elsewhere". Start refuses the §7.3 cases with the text
     shown on the row.
  4. **Visual check:** `python3 tools/visual_check.py --out DIR` starts the panel on a
     fixture at port 0. For each tab and state (including the open day dialog, Reach Weak,
     Followers with a decline, the Rules error row, and the attention strip open) at
     1280×800, 1600×900 and 1920×1080 it:
     - saves `--screenshot` PNGs with the cached `chrome-headless-shell` (path from
       `MF_CHROME`, default the newest
       `~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell`;
       extra library dir from `MF_CHROME_LIBS` for machines missing `libnspr4`, `libnss3`
       or `libasound`);
     - runs `--dump-dom --virtual-time-budget=2000` on the same URL with `?probe=1`. In
       probe mode the panel adds a script that measures every text node with a `Range`. It
       reports text whose range extends past its cell's box, any element wider than the
       viewport, any text node under the sticky tab bar, and controls whose boxes overlap
       others. The results go into a `<pre id="probe">` block. The tool fails on any
       finding.
     Both headless-shell modes were tried on this machine on 2026-11-10 (a probe page with
     `--dump-dom` returned its measured JSON, and `--screenshot` wrote a PNG).
  5. **Contrast:** the tool computes the WCAG ratio for each colour pair in the token table
     from the CSS file and fails below 4.5:1 for text. Interactive targets are at least
     24×24 CSS px (measured by the probe).
  6. The reviewer compares each tab's screenshot with the frames §11 cites for it. They
     must show the same regions in the same order.
- **Checks:** the project's test command, then `python3 tools/visual_check.py`. The
  reviewer looks at every PNG.
- **Operator provides:** opening the panel once in the Windows browser at
  `http://localhost:8770/` (settles S5), and feedback on the look.

## 14. Rendering and behaviour rules the panel lane must keep

- Each state has a defining text on the first screen at every width: "черновик" or
  "работает с …", "нет контента", "пропущен: …", "нет доступа …", "выключено".
- Neighbouring states use different words. Colour always comes with text: signs on deltas,
  labels on states, "не построено" on dim nodes.
- A fact is shown once per surface. For example, the X spend and plan appear only in the top
  bar, and the Calendar header does not repeat them.
- The day dialog is modal (`showModal`), so Tab and clicks do not reach the page behind it.
  Escape and the close button close it.
- No horizontal page scroll at 1280. Long titles and texts are clamped with an ellipsis and
  a `title` attribute carrying the full text. Long single tokens break (`overflow-wrap:
  anywhere`).
- Times are shown in the slot's rule zone with its abbreviation. The Calendar grid's day
  boundaries use the machine zone.

## 15. Unconfirmed facts and live checks

| Id | Unconfirmed | Cheapest check | Who / when |
|---|---|---|---|
| S1 | The current Page token can read `followers_count`, post reactions and comments, and `post_media_view`; the Page has ≥ 100 likes (F3, F5) | `factory stats probe` (L2): free GETs, publishes nothing. Before L2, one `GET /{page_id}?fields=followers_count` with the Page token answers the first part | L2 lane, live |
| S2 | The token carries `instagram_manage_insights` (I6) | same probe: `GET /{newest media}/insights?metric=views` | L2 lane, live |
| S3 | The X account owns the developer app (Owned Reads rate), and `users/me` is billed at $0.010 (X6) | The operator looks at the developer app's owner and the usage line in the X Developer Console after the first weekly read; no extra API call | Only if X stats are turned on |
| S4 | The field-selection parameter on `GET /2/users/{id}/tweets` is `tweet.fields` or `post.fields` (X4) | The first weekly read sends `tweet.fields`; a 400 naming the parameter switches it | Only if X stats are turned on |
| S5 | The Windows browser reaches a panel bound to `127.0.0.1` inside WSL2 through `localhost` (the same unknown as poster U5) | Start the panel and open `http://localhost:8770/` in Windows | L3, operator |
| S6 | The WSL2 distribution keeps running, so the user timer fires, while no terminal is open | Install the timer, close every WSL window for an hour, then `factory status` shows the heartbeat age | L1 smoke |

If S5 fails, the panel gets `--host` for the WSL interface address, with the same Host and
CSRF checks, and the allowed Host list gains that address. If S6 fails, a Windows Task
Scheduler entry at logon starts a long-lived process in the distribution (for example
`wsl.exe --exec sleep infinity`), which keeps it running; that lane verifies it the same way
as S6. Both are listed in §18 as conditional.

## 16. Answers in the pending form, and what changes otherwise

| Question | This design (recommended) | Other answer → change |
|---|---|---|
| start | L1 queue and schedule first | **Stats first:** order L2 → L1 → L3; nothing else changes. **New networks first (Telegram channel, Threads):** a poster lane adds the two targets first; the factory is unchanged (targets are generic), and the panel lights two more ring nodes |
| where | User timer on this computer; posts wait while it is off; catch-up as in §9.2 | **Separate small server:** the timer and state move there. `content/` is synced to it (rsync over SSH after each approved batch), the env file is copied once (the operator's call), and the panel reads the server's state through an SSH tunnel. Catch-up becomes a rare path. New monthly cost; needs a budget |
| panel | L3 right after the core | **Mock first:** L3 starts with a prototype stage (numbered variants rendered from fixtures, operator picks), then wires data. **No panel:** drop L3; `factory status` and a weekly `factory report` (text versions of Calendar, Reach and Followers) go to chat |
| dm | Disabled Dialogs tab | **Assistant in "suggest only" mode:** a new design. By our estimate (not checked against Meta's messaging docs here; that design would check it first) it needs a messaging permission with app review, a public HTTPS endpoint for incoming-message webhooks (this computer is not always on, so a server), a paid model per reply, and a draft channel to the operator. The panel's Dialogs tab becomes real |

## 17. Open items for the operator (non-blocking)

1. **X over the cap on a scheduled slot.** Options: (a) publish the free networks on time,
   skip X, and raise an attention item asking whether to raise the cap (**recommended**;
   it matches "refuse and ask" for X without holding back free posts); (b) hold the whole
   slot until the operator answers (the series stays in step, but the free networks miss
   their hour).
2. **Starter rules** (L1 input): which folders go to which networks, on which days and at
   which hours. Proposal: one photo folder to all four networks, Mon/Wed/Fri 10:00.
3. **Meta token re-issue** if probe S1 or S2 shows missing read permissions (L2 input).
4. **X stats:** off (default) or weekly (L2 input).

## 18. Deferred — not currently justified

| Item | Why deferred | Trigger to build |
|---|---|---|
| Video formats (Reels, trial Reels, Shorts, TikTok, YouTube, Pinterest), video lanes in Files | The poster publishes images and text only; there is no video pipeline | The operator brings video |
| Telegram channel and Threads targets | Recommended start is the four connected networks | Form answer "new networks first", or a later request |
| Dialogs: Instagram direct-message assistant | By our estimate (unchecked, §16): a messaging permission, an always-on webhook endpoint and a paid model per reply; plus the risk of speaking for the operator | Form answer "dm: yes" |
| One-click connect through an aggregator; OAuth buttons in the panel | Decided earlier: own poster without a subscription; connection is the env file plus `poster login linkedin` | Many new networks at once |
| LinkedIn stats (post analytics, followers) | Community Management API only for registered organizations (L3) | An organization app is approved |
| X stats daily | Paid reads would eat the shared $5 cap (X1); weekly is the opt-in | Budget raised |
| Instagram and Facebook demographics, reach breakdowns | Not shown in the video's tabs | Operator asks |
| Reordering folders and packages in the panel ("Изменить порядок") | File-name order is enough; the orchestrator renames | Frequent reordering |
| Upload and editing of packages in the panel; approval in the panel | Approval happens in chat (decision 1) | Operator asks to approve without chat |
| Publish and retry buttons in the panel | Publishing from a browser button adds risk; `factory retry` covers it | Operator asks |
| Automatic retries of failed or unknown publications | Publishing is not idempotent (poster §9.6) | — |
| Multi-user, storage and seat meters from the video | One operator, one set of accounts | Other people or brands join |
| Text generation inside the factory | The orchestrator writes texts in chat | Volume outgrows chat |
| Separate server | The recommended answer is this computer | Form answer "where: server" |
| Mobile layout, light theme, second UI language | Desktop tool, the video is dark, one operator | Operator asks |
| `--host` binding and a logon task for WSL | Only if S5 or S6 fails | Check fails |
| Indexed reading of a large publish record | About 4 lines per publication; small for years | Record above 50 000 lines |

## 19. Sources (read 2026-11-10)

Meta: [Rate limiting](https://developers.facebook.com/docs/graph-api/overview/rate-limiting/) ·
[Error handling](https://developers.facebook.com/docs/graph-api/guides/error-handling/) ·
[Page reference](https://developers.facebook.com/docs/graph-api/reference/page/) ·
[Post](https://developers.facebook.com/docs/graph-api/reference/post/) ·
[Reactions](https://developers.facebook.com/docs/graph-api/reference/object/reactions/) ·
[Comments](https://developers.facebook.com/docs/graph-api/reference/object/comments/) ·
[Insights](https://developers.facebook.com/docs/graph-api/reference/insights) ·
[IG User](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user) ·
[IG User insights](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/insights) ·
[IG Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media) ·
[IG Media insights](https://developers.facebook.com/docs/instagram-platform/reference/instagram-media/insights)

X: [Pricing](https://docs.x.com/x-api/getting-started/pricing) ·
[Usage and billing](https://docs.x.com/x-api/fundamentals/post-cap) ·
[Metrics](https://docs.x.com/x-api/fundamentals/metrics) ·
[Get my user](https://docs.x.com/x-api/users/get-my-user) ·
[Get posts](https://docs.x.com/x-api/users/get-posts)

LinkedIn: [Member Post Statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/post-statistics?view=li-lms-2026-10) ·
[Member Follower Statistics](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/members/follower-statistics?view=li-lms-2026-10) ·
[Increasing Access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access?view=li-lms-2026-10) ·
[Community Management App Review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review?view=li-lms-2026-10)

Project: `docs/design/poster.md` (publishing facts, record, ledger, limits) ·
`docs/smoke/` (observed token permissions, 2026-11-09) · research note on the video
(branch of the research lane, `docs/research/content-factory-video.md`).
