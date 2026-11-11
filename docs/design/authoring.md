# Authoring posts in the panel: photos, voice, Claude, Gemini, send

Design document. Status: ready to build in four lanes (§15). Written 2026-11-11 against
`main` at `f09433c` (poster, factory L1 and the L3 panel are built). Vendor and browser
documentation was read on 2026-11-11, and each external fact cites its page. Legend: **C**
means confirmed on the cited official page; **O** means observed on this machine; **U**
means unconfirmed, and §16 names the cheapest check for each. Another open lane (the
full-width panel) changes `factory/panel/static/panel.css`; nothing here depends on the old
`max-width`, and the top-bar measurements in §11.5 were taken with that lane's CSS applied.

## 1. Originating requirement

The operator wrote on 2026-11-11, in chat with the orchestrator. This is a close
paraphrase in the third person; the verbatim words stay in the task's pinned specification
because this repository is public. In the Files tab the operator uploads their own folder,
for now of photos. Below, where the text posts are, they want to sketch a text by typing or
by voice and, from that, get the publications for the other networks made with the photo as
the base. A photo may also get an effect, or the main person on it (the operator) may be
highlighted in some way. Everything else should be adapted to this menu too. Later they want
to simply select one photo, have the text filled in from their hints or just by a button and
adapted for the other networks, and then press one button that sends everything to the
networks.

Decisions the operator made in the form of 2026-11-11:

1. Per-network texts are written by Claude through the Anthropic API when the operator
   presses a button in the panel.
2. Voice: audio is recorded in the panel and transcribed with Gemini.
3. Highlighting the main person on a photo is Gemini image editing (background blur, soft
   glow, outline), with several styles to choose from.
4. The send button first shows every variant for review; then "publish now" or "add to the
   schedule queue".
5. One shared AI budget (texts, images, voice) of USD 10 per month; above that, ask the
   operator.

Earlier decisions that still hold: code templates for photos (quote on the photo, frame,
per-network crop); languages: LinkedIn and X in English, Facebook and Instagram in
Ukrainian, both languages on request; X capped at USD 5 per month (poster §11.2); the
operator reviews texts before anything is published.

### 1.1 Validation against the requirement

| Requirement (2026-11-11) | Where this design meets it |
|---|---|
| Upload my folder of photos in the Files tab | Folder or file upload into a photo-lane stock folder, browser-made thumbnails, photo grid (§6) |
| Sketch a text by typing or by voice | Hints box plus a record button; Gemini transcribes into the box, where it stays editable (§8.2, §8.3) |
| Make the other networks' publications from it, with the photo as the base | Claude sees the photo and the hints and writes one variant per network within the poster's limits (§8.4) |
| An effect on the photo; highlight me | Code templates (crop, frame, quote) and three Gemini styles, original and result side by side (§9) |
| Select one photo; text from my hints or just by a button | One click on a photo opens the composer; "Сгенерировать" works with empty hints too (§8.1, §8.4) |
| Adapted for the other networks | Per-network language, length rules, crop and image size (§8.4, §9.1) |
| One button sends everything | Review of every variant, then "Опубликовать сейчас" through the poster or "В очередь" into the stock with approval recorded (§10) |
| Adapt everything else to this menu | Files cards show photo counts and drafts; the folder view shows photos, their use and the queue; the top bar shows the AI month (§6.7, §10.5, §11.5) |
| (decision 5) USD 10 a month for AI, then ask | One local ledger for Anthropic and Gemini; every call is reserved before it is sent and refused above the cap (§11) |

Every item is built in lanes A–D (§15). Items cut from scope are in §18.

## 2. What exists today

Facts read from `main` at `f09433c`.

**Panel** (`factory/panel/`, design `factory.md` §11, brief `panel-brief.md`):

- `server.py`: a `ThreadingHTTPServer` on `127.0.0.1` with `daemon_threads = True`
  (`server.py:74`). Every request checks `Host` (421). Every POST checks `Origin` when
  present, requires `Content-Length`, refuses bodies over `MAX_BODY = 16 * 1024`
  (`server.py:33`, `:244`), refuses any type but `application/x-www-form-urlencoded`
  (`:34`, `:248`), and compares the form field `csrf` with `hmac.compare_digest` (`:257`).
  The POST path therefore cannot take a file today. Writes run under one `write_lock`
  (`:60`, `:271`).
- `end_headers` adds `SECURITY_HEADERS` to every response (`:39`, `:97`):
  `default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self';
  frame-ancestors 'none'`, plus `nosniff` and `no-referrer`. Pages are buffered, redacted
  once more and sent with `Content-Length`; `/img` streams a file with `copyfileobj`
  (`:185`). `log_message` logs nothing (`:94`).
- `model.py`: one snapshot, rebuilt when `state_key` changes (`:86`). The key includes a
  depth-1 `scandir` walk of `content/stock/` (`:58`), so a subfolder of a stock folder costs
  one stat entry, whatever it holds.
- `views.py`: the Files tab draws lanes "Фото-посты" and "Текстовые посты", folder cards
  and a folder view (`:390`, `:417`, `:457`); the top-bar status is built in `_status`
  (`:159`).
- `static/panel.js` is progressive enhancement; §11.1 of the factory design promised that
  every action also works without JS.

**Poster** (`poster/`):

- Package: `schema`, `id` (`[a-z0-9][a-z0-9._-]{0,79}`, `package.py:15`), `theme`,
  `variants` (`text`, `image`), `meta` (ignored by the poster). An image ref with `/` is a
  path relative to the package file's folder (`package.py:41`).
- Checks (`rules.py`), never truncating: X 280 weighted characters and at most 1 cashtag;
  Instagram 2 200 UTF-16 units, 30 hashtags, 20 mentions, JPEG only, 8 MB, aspect 0.8–1.91;
  LinkedIn 3 000 after escaping and under 36 152 320 pixels; Facebook 10 MB; X 5 MB
  (`rules.py:16-30`, `check_text` `:301`, `check_image`, `sniff` `:170`).
- `xapi.estimate` prices an X post ($0.015 text, $0.200 with a URL, $0.215 with an image);
  `state.Ledger` reserves before a request and settles after (`state.py:139-185`), on the
  public JSONL helpers `read_jsonl`, `append_jsonl`, `locked` (`state.py:29-64`).
- `cli.main([... "publish", PATH, "--targets", ...])` is the publish path the factory
  runner calls in-process. Instagram polls the container once a minute for up to 5 minutes
  (`instagram.py:11-12`), so one publish can take over 5 minutes.
- `http.UrllibTransport` (HTTPS only, no redirects, `TransportError` without details) and
  `vendor_message` (reduces vendor error bodies and masks long runs) (`http.py:181`, `:223`).

**Factory**: stock folders hold `folder.json` and packages; the loader skips
subdirectories (`stock.py:184`); a package without `meta.approved_by_operator` is never
published; publish order is file-name order; package ids are unique across the stock and
`content/packages/`. Three items deferred in `factory.md` §18 have now met their trigger
("operator asks"): upload and editing of packages in the panel with approval there
(`factory.md:1107`), publish buttons in the panel (`:1108`), text generation (`:1111`).

**Machine** (O, 2026-11-11): Python 3.12.3, standard library only. `which convert magick
ffmpeg cwebp` finds nothing. `import cgi` under `-W error::DeprecationWarning` fails with
"'cgi' is deprecated and slated for removal in Python 3.13".

## 3. Decisions and trade-offs

| # | Decision | Rejected options | Why |
|---|---|---|---|
| D1 | All pixel work (thumbnails, crop, frame, quote, re-encoding) runs in the operator's browser on `<canvas>`; the server only stores and validates bytes | Pillow (needs pip); ImageMagick/ffmpeg (not installed, a new system dependency); server-side headless Chromium (heavy, a second browser); Gemini for crops (costs money, not exact) | The standard library has no image codec. The browser decodes JPEG, PNG and WebP, applies EXIF orientation (B3) and encodes JPEG (B4). Canvas output carries no camera metadata, so no GPS tag reaches a network (§13) |
| D2 | One file per POST as the raw request body (`fetch` with `Content-Type: image/jpeg`), CSRF in a request header | `multipart/form-data` parsed with `cgi` (deprecated, removed in 3.13, O); `multipart/form-data` parsed with `email.parser.BytesParser(policy=email.policy.HTTP)` (works, O, but reads the whole body into memory and only serves a no-JS fallback nobody needs) | Streams to disk with a hard size limit, no parser at all, and a custom header forces a CORS preflight that the server refuses (no `do_OPTIONS`, so 501; §13) |
| D3 | Drafts live in `content/drafts/<id>/`; only "В очередь" writes a package into a stock folder, and only "Опубликовать сейчас" writes one into `content/packages/` | Drafts as unapproved packages inside stock folders | The factory's states stay as they are (`not-approved` would turn every draft into a red "не одобрено" line and a `factory check` note); drafts can hold voice, Gemini results and history that do not belong in a package |
| D4 | AI calls run in the request thread with a per-call deadline; publishing runs in one background thread that the page polls | A job queue for everything; publishing inside the request | AI calls end within 2–3 minutes and the browser simply waits; a publish can take over 5 minutes (Instagram polling) and must survive a closed tab |
| D5 | Gemini through the Interactions API with `store: false` | `generateContent` ("legacy", still "fully supported", G7) | The current docs and examples for audio and image editing use Interactions (G1, G5). By default Interactions stores every request for 55 days on the paid tier; `store: false` turns that off (G7) |
| D6 | Claude structured output (`output_config.format`, JSON schema) | Forced tool use; free text parsed by hand | Stable on all models, schema-checked JSON in one text block (A5) |
| D7 | Transcription with `gemini-3.5-flash-lite` and inline audio | `gemini-3.5-transcribe` | Inline WebM audio is documented for general models (G1, G2); the transcribe model's REST examples use a Files API upload first (G4), so it would cost two requests and a file clean-up |
| D8 | "Highlight" with `gemini-nano-banana-2.1` at 2K, one style per click | Generate all styles at once; `gemini-3-pro-image` | Google's recommended editing model, stable, $0.0504 per 2K image (G5, G6); one click shows its price and spends only what the operator asks for |
| D9 | Authoring pages need JavaScript; with JS off they say so | A no-JS path for each step | Recording, canvas templates and folder upload exist only in JS. Every other panel page keeps its no-JS behaviour |
| D10 | The AI month is a text item in the top-bar status, "ИИ $0.84 из $10.00" | A bar plus text; folding it into the X meter | Measured in §11.5: a bar variant adds a third status row at 900 px; folding needs about 113 px where 41 px are free |

## 4. Vendor and platform facts

### 4.1 Anthropic (Claude)

| # | Fact | Status | Source |
|---|---|---|---|
| A1 | `claude-sonnet-5-5` is "The best combination of speed and intelligence"; $2 input and $10 output per million tokens; vision and multilingual on all current models; retirement "Not sooner than September 28, 2027". `claude-haiku-5-5` costs from $0.10/$0.50 and is described "For high-volume, latency-sensitive tasks such as classification, extraction, and routing" | C | [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| A2 | Pricing table: Sonnet 5.5 $2 / MTok input, $10 / MTok output; Haiku 5.5 $0.10 / $0.50 up to 100 000 prompt tokens. `inference_geo: "us"` multiplies by 1.1; global (default) is standard | C | [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| A3 | Images: JPEG, PNG, GIF, WebP; cost `⌈width/28⌉ × ⌈height/28⌉` visual tokens; Claude 4.7 and later: long edge up to 2 576 px and at most 4 784 visual tokens; 10 MB per image (base64) on the Claude API; base64 `image` block with `media_type` | C | [Vision](https://platform.claude.com/docs/en/build-with-claude/vision) |
| A4 | Header `anthropic-version: 2026-10-21` (latest); in it `temperature`, `top_p` and `top_k` are removed and return 400 | C | [API versions](https://platform.claude.com/docs/en/api/versioning) |
| A5 | `output_config.format = {"type": "json_schema", "schema": …}`, stable, no beta header; the JSON comes in the response's `text` block; not supported: `minLength`/`maxLength`, numeric bounds, `additionalProperties` other than `false`, external `$ref`; `stop_reason: "refusal"` is billed and may not match the schema; `max_tokens` may cut the JSON | C | [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) |
| A6 | `output_config.effort` (`low` … `max`); Sonnet 5.5 defaults to `high`; "For chat and other latency-sensitive work, start with `medium` or `low`"; `thinking: {"type": "between_tools"}` turns off up-front thinking on Sonnet 5.5 at `low`–`high`; thinking counts toward `max_tokens` | C | [Effort](https://platform.claude.com/docs/en/build-with-claude/effort) |
| A7 | "Retained data is never used for model training without your express permission." Standard retention follows the commercial policy linked there | C | [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| A8 | `between_tools` thinking together with `output_config.format` is accepted on Sonnet 5.5 | **U** (LC1) | — |

### 4.2 Google (Gemini)

| # | Fact | Status | Source |
|---|---|---|---|
| G1 | Audio understanding: `POST https://generativelanguage.googleapis.com/v1beta/interactions`, headers `x-goog-api-key`, `Content-Type: application/json`, `Api-Revision: 2026-05-20`; body `model` and `input` with `{"type": "text", …}` and `{"type": "audio", "data": <base64>, "mime_type": …}`. Formats include `audio/webm` and `audio/opus`; "Maximum request size is 20 MB total"; "32 tokens per second of audio" | C | [Audio understanding](https://ai.google.dev/gemini-api/docs/audio) |
| G2 | `gemini-3.5-flash-lite`: Stable; inputs "Text, Image, Video, Audio, and PDF", output text; Thinking and Structured outputs supported | C | [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) |
| G3 | Paid prices per 1M tokens: `gemini-3.5-flash-lite` input $0.30 (text, image, video, audio), output $2.50 including thinking. `gemini-nano-banana-2.1` input $1.50, output text $7.50, output image $30; "Output images at 1K (1024x1024px) consume 1120 tokens and are equivalent to $0.0336 per image", 2K 1 680 tokens ($0.0504), 4K 3 780 tokens. Paid tier "Used to improve our products: No"; free tier "Yes" | C | [Pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| G4 | `gemini-3.5-transcribe`: pre-recorded audio up to 1 hour; Ukrainian `uk-UA` and Russian `ru-RU` supported; REST examples upload via the Files API; $0.003/min audio in, $0.002/min text out | C | [Transcription](https://ai.google.dev/gemini-api/docs/transcribe), [Pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| G5 | Image editing: same endpoint and headers as G1; `input` holds a text block and `{"type": "image", "mime_type": …, "data": <base64>}`; output options in `response_format`, e.g. `{"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "16:9", "image_size": "2K"}`; `image_size` "1K" (default), "2K", "4K" with an uppercase K; the image comes back in a `model_output` step as a block of `"type": "image"` with base64 `data`; "All generated images include a SynthID watermark"; Nano Banana 2.1 is "the primary model for generation and conversational editing" | C | [Image generation](https://ai.google.dev/gemini-api/docs/image-generation) |
| G6 | `gemini-nano-banana-2.1`: "Stable"; inputs text, image, video, PDF; output image and text; latest update October 2026 | C | [Nano Banana 2.1](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1) |
| G7 | "By default, the API stores all Interaction objects (`store=true`)"; paid tier retention 55 days, free tier 1 day; `store=false` opts out (and is incompatible with background execution). "the original `generateContent` API remains fully supported" | C | [Interactions](https://ai.google.dev/gemini-api/docs/interactions) |
| G8 | Response `usage` has `total_input_tokens`, `total_output_tokens`, `total_thought_tokens`, `total_tokens`; `generation_config.thinking_level` is `minimal`, `low`, `medium` or `high`; the reference shows the endpoint as `v1/interactions` | C | [Interactions API reference](https://ai.google.dev/api/interactions-api-v1) |
| G9 | Unpaid services: "human reviewers may read, annotate, and process your API input and output" and "Do not submit sensitive, confidential, or personal information to the Unpaid Services". Paid services: "Google doesn't use your prompts … or responses to improve our products"; the API is paid "only when accessing the API … through a Cloud Project associated with an active billing account" | C | [Gemini API terms](https://ai.google.dev/gemini-api/terms) |
| G10 | `v1beta` with `Api-Revision: 2026-05-20` (guide examples) versus `v1` (reference) | **U** (LC2) | G1, G8 |
| G11 | Whether `max_output_tokens` also bounds thought tokens; how many tokens one input photo costs on Nano Banana 2.1 | **U** (LC2, LC3) | — |
| G12 | The full `aspect_ratio` list (4:5, 3:4, 2:3, 9:16 for portraits) | **U** (LC3) | G5 links it from another page |
| G13 | Editing a photo of a real person (the operator) is accepted and keeps the face recognisably unchanged | **U** (LC3) | G5 says nothing about it |

### 4.3 Browser

| # | Fact | Status | Source |
|---|---|---|---|
| B1 | `getUserMedia` works only in secure contexts; "in insecure contexts, `navigator.mediaDevices` is `undefined`". `http://localhost` and `127.0.0.0/8` are potentially trustworthy; a LAN address over plain HTTP is not | C | [getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [Secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) |
| B2 | `<input type="file" webkitdirectory>` selects a folder; each `File` has `webkitRelativePath`; Baseline 2025 | C | [webkitdirectory](https://developer.mozilla.org/en-US/docs/Web/API/HTMLInputElement/webkitdirectory) |
| B3 | `createImageBitmap(blob)` accepts a `Blob`; `imageOrientation: "from-image"` (default) applies EXIF orientation; `resizeWidth`/`resizeHeight`/`resizeQuality` | C | [createImageBitmap](https://developer.mozilla.org/en-US/docs/Web/API/Window/createImageBitmap) |
| B4 | `canvas.toBlob(cb, "image/jpeg", q)` with quality 0–1; a canvas tainted by another origin throws `SecurityError` (our images are same-origin) | C | [toBlob](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/toBlob) |
| B5 | The operator's browser records `audio/webm;codecs=opus` with `MediaRecorder` | **U** (LC5) | — |
| B6 | The Windows browser reaches the panel inside WSL2 at `http://localhost:8770/` (factory S5). If it cannot and the panel is opened by a WSL address, B1 turns voice off | **U** (LC5) | `factory.md` §15 |

## 5. Layout

### 5.1 Code

```
factory/authoring/            new package, standard library only
  __init__.py
  photos.py     upload streaming, photo ids, photos/index.jsonl, listing, file paths
  drafts.py     draft schema, create/load/save with revision, files, delete
  budget.py     AI ledger: estimate, reserve, settle, month total, cap
  prices.py     price table with source URLs and the date read (§11.3)
  prompts.py    Claude system prompt and schema; Gemini transcription and style prompts
  claude.py     request build, response parse, usage -> price
  gemini.py     transcription and image-edit requests, parse, usage -> price
  send.py       review checks, package writing (queue, publish now), publish thread
factory/panel/
  server.py     POST route table with body kinds (§14.1); new GET routes; JSON replies;
                serve() waits for a running publish on Ctrl+C
  views.py      composer, review, drafts list, photos section, AI status item
  model.py      photo counts on folder cards; AI month cache
  strings.py    new Russian strings
  static/author.js    upload loop, recorder, editors, canvas templates (~450 lines,
                      loaded only on Files and composer pages)
  static/panel.css    composer and review styles
tests/test_author_*.py, tests/panel_fixture.py (photos and drafts), tools/visual_check.py
KEYS.md, README.md
```

The poster stays unchanged. The factory core (`stock`, `ruleset`, `planner`, `runner`,
`journal`, `checks`) stays unchanged.

### 5.2 Files and state

| What | Location | Mode | In git |
|---|---|---|---|
| Uploaded photos | `content/stock/<folder>/photos/<id>.<ext>`, `photos/thumb/<id>.jpg`, `photos/view/<id>.jpg`, `photos/index.jsonl` | dirs 0700, files 0600 | no (`content/` is ignored) |
| Drafts | `content/drafts/<draft-id>/draft.json`, `voice-<n>.webm` (until transcribed), `img/<style>.jpg`, `out/<network>.jpg` | same | no |
| Queued package | `content/stock/<folder>/<NNN>-<id>.json` and `media/<id>/<network>.jpg` | same | no |
| Published-now package | `content/packages/<id>.json` and `content/packages/media/<id>/<network>.jpg` | same | no |
| AI ledger | `<factory state>/ai-ledger.jsonl`, `ai-ledger.lock` | 0600 | no (outside every checkout) |

`content/` follows `MF_CONTENT_DIR`, the factory state follows `MF_FACTORY_STATE_DIR`.

### 5.3 Who writes and who reads

| File | Writers | Readers |
|---|---|---|
| `stock/<f>/photos/**` | panel upload only | panel (grid, composer, cards) |
| `content/drafts/**` | panel only | panel |
| `stock/<f>/<NNN>-<id>.json`, `media/<id>/**` | panel "В очередь" (new files only, `O_EXCL`); orchestrator as before | factory loader, planner, runner, panel |
| `content/packages/<id>.json`, `media/<id>/**` | panel "Опубликовать сейчас" (new files only) | poster, factory duplicate-id check |
| `ai-ledger.jsonl` | panel AI calls | panel top bar and composer |
| poster `posts.jsonl`, `x-ledger.jsonl` | poster only (also when the panel calls it) | panel review status, factory |

## 6. Files tab: photo upload

### 6.1 Flow

1. The operator opens a photo-lane folder (an existing card, or "+ Фото-посты · новая
   папка", which already lands in the folder view). The folder view gets a "Фото · N"
   section above the package list with two buttons: "Загрузить папку" (`webkitdirectory`,
   B2) and "Добавить фото" (`multiple`, `accept="image/jpeg,image/png,image/webp"`).
2. `author.js` sorts the picked files by `webkitRelativePath` (or name), skips files that
   are not JPEG, PNG or WebP by type and extension, and processes them one at a time:
   - decode with `createImageBitmap(file)` (EXIF orientation applied, B3). A failure
     (HEIC on Windows, a broken file) counts as skipped with its reason;
   - draw two copies with `resizeWidth/Height` and `resizeQuality: "high"`: **thumb**
     (long side 480 px, JPEG 0.82) and **view** (long side 1 600 px, JPEG 0.88);
   - `POST /files/photos?folder=F&kind=orig` with the original bytes; the answer is
     `{"id": "p-…", "dup": false}`. On `dup: true` (same bytes already stored) the next two
     posts are skipped;
   - `POST …&kind=thumb&id=P`, then `POST …&kind=view&id=P&w=W&h=H&name=N` (the view copy's
     size and the original base name).
3. A `role="status"` line counts "загружено 12 из 40 · пропущено 3 (HEIC)"; the skipped
   files are listed by name with the reason. At the end the page reloads.

### 6.2 Server route

`POST /files/photos` belongs to the route table of §14.1 with body kind `image`. In order,
before reading any body byte:

1. `Host` (421), `Origin` present and equal to `http://<Host>` (403), header
   `X-CSRF-Token` equal to the token (403);
2. `folder` matches `fstock.NAME_RE`, exists as a stock folder with lane `photo`
   (404/409); `realpath(stock/F)` lies under `realpath(stock)`; `photos/` is created
   0700 if absent and must not be a symlink (`os.lstat`);
3. `kind` is `orig`, `thumb` or `view`; for `thumb`/`view`, `id` matches
   `^p-[0-9a-f]{16}$` and `photos/<id>.*` exists;
4. `Content-Length` present and at most the kind's limit (413, connection closed);
   `Content-Type` in the kind's set (415);
5. free space on the content filesystem (`os.statvfs`) at least 1 GB plus the body (507).

Then it streams `rfile` into `photos/.up-<random>` (`O_CREAT|O_EXCL`, 0600) in 64 KB
chunks, computing SHA-256 on the way, and stops at `Content-Length`. It sniffs the result
with `poster.rules.sniff`: `orig` must be JPEG, PNG or WebP (otherwise 415 and the temp
file is removed); `thumb` and `view` must be JPEG. For `orig` the id is
`p-` + the first 16 hex digits of the SHA-256; if `photos/<id>.<ext>` exists the temp file
is removed and the reply is `dup: true`, otherwise `os.replace` moves it in place. For
`view` the server appends one row to `photos/index.jsonl` under a lock file in `photos/`:

```json
{"id": "p-3f2a9c01b7d4e6a8", "name": "IMG_0412.jpg", "ext": "jpg", "bytes": 6123456,
 "w": 1600, "h": 1200, "ts": "2026-11-11T10:00:00Z"}
```

A photo is listed only when its index row exists, so an upload cut short leaves invisible
files that the next attempt overwrites. `name` is the original base name, at most 120
characters, control characters removed; it is data shown escaped, never a path.

### 6.3 Limits and formats

| Limit | Value | Reason |
|---|---|---|
| Original | ≤ 25 MB; JPEG, PNG, WebP by sniffing | Phone JPEGs are 3–12 MB; HEIC cannot be decoded by the browser on Windows nor sniffed here, so it is refused with "экспортируйте JPEG" |
| Thumb, view | ≤ 2 MB each, JPEG | Made by the browser at 480 and 1 600 px |
| Photos per folder | ≤ 2 000 | Keeps the index read and the grid bounded |
| Files per pick | ≤ 300 (more: "выберите меньше") | One pass of the loop stays short |
| Disk | refuse below 1 GB free | A full disk would also break the poster's ledger |

Nothing is resized or re-encoded on the server. The original stays byte-identical (with
its EXIF) on this computer only (§13).

### 6.4 Why thumbnails come from the browser

The standard library cannot decode a JPEG. The browser already has the decoded image while
it uploads, so it makes the thumb (grid, cards) and the view copy (composer preview, Claude
and Gemini input, §8.4, §9.2). The view copy is 1 600 px on the long side: 58 × 43 = 2 494
visual tokens for a 4:3 photo on Claude (A3), well inside the 4 784 cap, and about 0.4 MB of
JPEG, well inside Gemini's 20 MB request (G1).

### 6.5 Serving

`GET /photo?folder=F&id=P&v=thumb|view|orig` checks the folder name and the id pattern,
resolves the file inside `stock/F/photos/` (realpath must stay inside it), sniffs it
(JPEG, PNG or WebP), and streams it with the sniffed `Content-Type`,
`Cache-Control: private, max-age=300`. Anything else is 404, as `/img` does today.

### 6.6 Snapshot cost

The depth-1 stock walk sees `photos/` as one entry, so a request still costs one stat walk
whatever the photo count. An upload changes that entry's mtime, so the next page rebuilds
the snapshot once. That rebuild is needed, because the cards show photo counts (§6.7).
`model.build` reads each photo folder's `index.jsonl` (≤ 2 000 short rows) only on such a
rebuild.

### 6.7 Files tab changes

- **Photo-lane card:** when a folder has photos, its tiles show the first three thumbs and
  "+N", and the count line reads "39 пакетов · 120 фото". Without photos it stays as now.
- **Text-lane header:** a button "+ Текстовый пост" opens the composer with no photo; the
  folder select defaults to the first text folder.
- **Drafts strip:** above the lanes, "Черновики · 3" with links when drafts exist; a draft
  whose publish was interrupted reads "прервано — проверьте аккаунт" in `--red`.
- **Folder view:** the "Фото · N" section (§6.1), a grid of 120 px thumbs (60 per page,
  "показать ещё"). Each tile carries a "Пост" button (a POST form that creates a draft,
  §7.2) and, when the photo is used, a text chip: "черновик", "в очереди" or
  "опубликовано". The package list below gains nothing new.

## 7. Drafts

### 7.1 Schema

`content/drafts/<id>/draft.json`, written atomically (temp file plus `os.replace`), 0600:

```json
{
  "schema": 1,
  "id": "2026-11-11-trip-3f2a",
  "created": "2026-11-11T10:00:00Z",
  "updated": "2026-11-11T10:04:12Z",
  "folder": "trip",
  "photo": "p-3f2a9c01b7d4e6a8",
  "hints": "Вчера на конференции…",
  "networks": ["facebook", "instagram", "linkedin", "x"],
  "langs": {"facebook": "uk", "instagram": "uk", "linkedin": "en", "x": "en"},
  "theme": "",
  "base": "original",
  "styles": {"blur": "img/blur.jpg"},
  "variants": {
    "x": {"text": "…", "quote": "…", "source": "claude",
          "image": "out/x.jpg",
          "template": {"crop": "16:9", "focus": [0.5, 0.4], "frame": null, "quote": false}}
  },
  "state": "draft",
  "publish": null
}
```

- `id`: `YYYY-MM-DD-<folder>-<4 hex>`; it matches the poster's id pattern and becomes the
  package id. `folder` is where the photo lives and the default queue folder; `photo` is
  null for a text post (then `folder` is a text-lane folder).
- `langs` values: `uk`, `en` or `en+uk` (both languages, English first). Defaults: Facebook
  and Instagram `uk`, LinkedIn and X `en`.
- `networks` defaults to the networks of the poster's main profile; Instagram is removed
  when `photo` is null.
- `source`: `claude` or `edited` (the operator changed the text).
- `state`: `draft`, `publishing`, `published`, `partial`, `queued`. `publish` holds
  `{"started": ts, "targets": […], "file": "packages/<id>.json"}` once a publish starts.
- The revision is the SHA-256 of the file. Every write carries the revision it was based on
  and is refused with "черновик изменён в другом окне — обновите" when it differs (the same
  pattern as the rules file).

### 7.2 Lifecycle

- `POST /compose/new` (form, `csrf` field; fields `folder`, optional `photo`) creates the
  folder with `os.mkdir` (an existing id retries with new hex) and redirects to
  `/compose/<id>`. A GET never writes.
- Each draft has a lock file `.lock`. An AI call or a publish takes it with
  `fcntl.flock(LOCK_EX | LOCK_NB)`; a second one gets 409 "уже выполняется". Edits do not
  take it; they rely on the revision.
- At most two AI calls run at a time across the panel (a semaphore), which bounds memory
  for base64 bodies and the spend rate.
- "Удалить черновик" (form POST, modal confirmation) removes the folder, only in state
  `draft`. After a successful queue or a publish where every target is `published`, the
  draft folder is removed; the package and its media are the record. A `partial` draft
  stays for "Повторить упавшие" (§10.3).

## 8. Compose

### 8.1 Page

`GET /compose/<id>`, modelled on the panel's dark style:

- **Head:** "← <folder title>", the draft id in mono, the state word, "Удалить черновик".
- **Left column (photo):** the photo strip of §9.3 (original and style results side by
  side) and the per-network previews of §9.1. A text post shows "без фото".
- **Right column (text):**
  - "Подсказки" textarea (up to 4 000 characters) with "Записать голос" next to it (§8.3);
  - a row per network: monogram, a language select (`uk`, `en`, `en+uk`), an on/off switch;
  - "Сгенерировать · до $0.08" (the reservation bound, §11.2);
  - one card per network: textarea, the poster's count line ("weighted 212/280") and its
    errors in `--red` with `role="alert"`, "Перегенерировать · до $0.05" (the bound
    computed for that call) with an optional one-line wish ("короче", "без хештегов");
- **Footer:** "Проверить и отправить →" opens the review (§10).
- **Missing keys:** "нет ANTHROPIC_API_KEY в .env" or "нет GEMINI_API_KEY в .env" replaces the
  button it disables (names only).

Widths: two columns `minmax(0, 5fr) minmax(0, 7fr)` from 1 200 px; one column below
(photo first). The named widths are 390, 900 and 1 440 (panel brief §1.2); the visual check
adds 1 280, 1 600 and 1 920.

### 8.2 Hints

Typing autosaves after 800 ms of quiet: `POST /compose/<id>/settings` (JSON `{hints,
langs, networks, rev}`) answers the new revision. Empty hints are allowed: "просто по
кнопке" then means Claude writes from the photo alone.

### 8.3 Voice

- "Записать голос" calls `getUserMedia({audio: true})` and records with `MediaRecorder`
  as `audio/webm;codecs=opus` (or `audio/webm`), the type Gemini documents (G1). When
  `MediaRecorder.isTypeSupported` accepts neither, the button reads "этот браузер не
  записывает WebM — откройте панель в Chrome или Edge". While recording, the button reads
  "Стоп · 0:12" (`aria-pressed="true"`, a `role="status"` timer). Recording stops by
  itself at 3:00.
- On stop, `POST /compose/<id>/voice` with the blob (body kind `audio`, ≤ 4 MB, media
  type `audio/webm`; parameters such as `codecs=opus` are ignored). The server stores
  `voice-<n>.webm`, reserves the budget (§11.2), and calls Gemini (§8.5). On success it
  appends the transcript to `hints` (a blank line between), saves the draft, deletes the
  audio file, settles the ledger and answers `{transcript, rev, month}`. On failure the audio stays and the card
  offers "Повторить расшифровку".
- States, each with its own words: "микрофон запрещён в браузере" (`NotAllowedError`),
  "микрофон не найден" (`NotFoundError`), "запись голоса работает только по адресу
  localhost" (`navigator.mediaDevices` undefined, B1), "расшифровка…", "бюджет ИИ
  исчерпан".
- No playback of the recording: the transcript is what the operator checks and edits.

### 8.4 Claude: generate and regenerate

Request (`claude.py`), sent with `poster.http.json_request` through `UrllibTransport`,
timeout 120 s:

```
POST https://api.anthropic.com/v1/messages
x-api-key: <ANTHROPIC_API_KEY>
anthropic-version: 2026-10-21
content-type: application/json

{"model": "claude-sonnet-5-5",
 "max_tokens": 4000,              (6000 when a network asks for en+uk)
 "system": "<SYSTEM, prompts.py>",
 "thinking": {"type": "between_tools"},
 "output_config": {"effort": "low",
                   "format": {"type": "json_schema", "schema": <SCHEMA>}},
 "messages": [{"role": "user", "content": [
   {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                "data": "<view copy>"}},
   {"type": "text", "text": "<USER>"}]}]}
```

- **Model:** `claude-sonnet-5-5` (A1): good copy in Ukrainian and English at $2/$10. A
  generation costs about $0.02 (§11.3). Haiku 5.5 would be twenty times cheaper but is
  described for classification and routing; it is deferred (§18).
- **SCHEMA:** `{"type": "object", "properties": {"theme": {"type": "string"}, "variants":
  {"type": "object", "properties": {<net>: {"type": "object", "properties": {"text":
  {"type": "string"}, "quote": {"type": "string"}}, "required": ["text", "quote"],
  "additionalProperties": false}, …}, "required": [<requested networks>],
  "additionalProperties": false}}, "required": ["theme", "variants"],
  "additionalProperties": false}`, with each network's object written inline (no `$ref`)
  and no length keywords (A5).
- **SYSTEM** (English, fixed in `prompts.py`): write as the author in first person; never
  invent facts beyond the hints and what the photo shows; one variant per requested network;
  `quote` is one short line (≤ 90 characters) for the quote-on-photo template, in the
  network's language. Per network, with the hard limits taken from `poster.rules` constants
  so the prompt and the check cannot drift:

  | Network | Target in the prompt | Hard check (poster) |
  |---|---|---|
  | Facebook | 400–900 characters, conversational, 0–3 hashtags at the end | none documented |
  | Instagram | hook in the first 125 characters, at most 1 500 characters, 3–8 hashtags at the end, no links | 2 200 UTF-16 units, 30 hashtags, 20 mentions |
  | LinkedIn | 600–1 300 characters, professional angle, short paragraphs, at most 3 hashtags | 3 000 after escaping |
  | X | at most 240 weighted characters (Cyrillic and Latin 1, emoji 2), at most 1 cashtag, no URL unless the hints contain one (a URL raises the X price from $0.015 to $0.200) | 280 weighted, 1 cashtag |

  `en+uk` asks for the English text, a blank line, then the Ukrainian one; on X both must
  fit together.
- **USER:** the hints, each network with its language, and for a regeneration the current
  texts of the other networks (for consistency) plus the operator's one-line wish.
- **Regenerate one network:** the same request with that network only and
  `max_tokens: 1500`; it replaces only that variant.
- **Answer handling:** the first `text` block of `content` is parsed as JSON.
  `stop_reason` `end_turn` saves the variants (`source: claude`) and answers them with each
  variant's `check_text` result. `refusal` shows "Claude отказался" and the text it gave;
  `max_tokens` shows "ответ обрезан — повторите"; both are billed and settled as such
  (A5). A text over a limit is kept, never cut, and shown with the poster's own error;
  the operator edits it or regenerates. Nothing retries by itself, so nothing spends
  without a click.

### 8.5 Gemini transcription

```
POST https://generativelanguage.googleapis.com/v1beta/interactions
x-goog-api-key: <GEMINI_API_KEY>
Content-Type: application/json
Api-Revision: 2026-05-20

{"model": "gemini-3.5-flash-lite",
 "store": false,
 "generation_config": {"thinking_level": "minimal", "max_output_tokens": 2000},
 "input": [
   {"type": "text", "text": "Transcribe this voice note verbatim in the language spoken
     (Russian, Ukrainian or English). Output only the transcript, no comments."},
   {"type": "audio", "mime_type": "audio/webm", "data": "<base64>"}]}
```

The transcript is the text of the `model_output` step. Usage comes from `usage` (G8).
Timeout 60 s. The key travels only in the header, never in the URL, so no URL in an error
can carry it. The dedicated `gemini-3.5-transcribe` is the fallback if transcripts of mixed
Russian and Ukrainian come out poor (§18).

### 8.6 Editing

Each textarea autosaves after 800 ms of quiet: `POST /compose/<id>/text` (JSON
`{network, text, rev}`). The server stores the text NFC-normalised, sets `source: edited`,
and answers `poster.rules.check_text(network, text)` as `{counts, errors, rev}`. The counts
on screen are always the poster's own (no JavaScript copy of the X weighting).

## 9. Photo: templates and highlight

### 9.1 Code templates (per network, in the browser)

Every published image is drawn by `author.js` on a canvas from the chosen **base** (the
original, or one Gemini result, §9.3) and saved as JPEG.

| Network | Default crop | Choices | Output |
|---|---|---|---|
| Instagram | 4:5 | 4:5, 1:1, 1.91:1 | 1080 × 1350 / 1080 × 1080 / 1080 × 566 |
| Facebook | original ratio | original, 4:5, 1:1, 16:9 | long side 2 048 |
| LinkedIn | original ratio | original, 1.91:1, 1:1 | long side 2 048 |
| X | 16:9 | 16:9, original, 1:1 | long side 1 600 |

- **Crop:** the window is the largest of the chosen ratio inside the base, centred on the
  focus point; one click on the preview sets the focus (default centre). The output never
  upscales: a smaller base gives a smaller output.
- **Frame:** an inset border of `max(16 px, 2.5 % of the short side)` in white, black or
  `#e8c47c` (the photo-lane accent).
- **Quote:** the variant's `quote` on a band of `rgba(0, 0, 0, 0.6)` at the bottom (or top)
  third, white `600` weight system sans (`system-ui, "Segoe UI", sans-serif`), sized from
  6 % of the width down until it fits in at most 4 lines of 86 % width (`measureText`).
  White on that band over a white photo is about 5.7:1 (WCAG formula).
- **Save:** "Сохранить картинки" posts each network's JPEG to
  `POST /compose/<id>/image?network=N` (body kind `image`, ≤ 8 MB, JPEG). Quality starts
  at 0.9 and steps down to 0.8 and 0.7 when the blob is over the network's byte limit. The
  server sniffs it, refuses an APP1 `Exif` segment (§13), runs
  `poster.rules.check_image(network, info)`, stores `out/<network>.jpg` and answers the
  check. The template settings go with `POST /compose/<id>/settings`.

### 9.2 Gemini highlight styles

Three styles, one Gemini call per click (`POST /compose/<id>/highlight` with JSON
`{style, who, rev}`), each button with its price bound ("до $0.09"):

| Style | Button | Instruction (prompts.py, English) |
|---|---|---|
| `blur` | Размыть фон | Blur the background as with a shallow depth of field. Keep the main person sharp and every pixel of their face, body and clothes unchanged |
| `glow` | Свечение | Add a soft warm rim light and glow around the main person. Do not change the face, features, body, clothes or the background content |
| `outline` | Контур | Add a thin soft white outline around the main person, sticker-like. Change nothing else |

All three append: "The main person is the most prominent person in the photo" plus the
operator's optional one-line description ("мужчина в синей куртке"), and "Do not add text,
logos or other people."

```
POST https://generativelanguage.googleapis.com/v1beta/interactions   (headers as §8.5)

{"model": "gemini-nano-banana-2.1",
 "store": false,
 "input": [{"type": "text", "text": "<style instruction>"},
           {"type": "image", "mime_type": "image/jpeg", "data": "<view copy>"}],
 "response_format": {"type": "image", "mime_type": "image/jpeg",
                     "aspect_ratio": "<nearest of 1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9>",
                     "image_size": "2K"}}
```

Timeout 180 s. The first `image` block of the `model_output` step is decoded, sniffed
(must be JPEG) and stored as `img/<style>.jpg`, replacing an earlier result of the same
style; `styles` records it. An answer without an image (a refusal or a safety block) shows
"Gemini не вернул картинку" with its text part and is settled at the usage reported. The
result carries Google's SynthID watermark (G5).

### 9.3 Side by side, and the pick

The left column shows two equal tiles side by side at every width (at 390 px each is about
170 px wide): **Оригинал** and the selected style result, each labelled. Under them, a row
of chips "Оригинал · Размыть фон · Свечение · Контур"; a chip without a result reads
"создать · до $0.09". Selecting a chip shows that result in the right tile; "Взять за
основу" sets `base`, and the per-network previews (§9.1) redraw from it. The original is
always kept, so a drifted face costs only the call.

### 9.4 What a text post does

A draft without a photo has no left column images, no Instagram, and no template
controls; everything else is the same.

## 10. Send

### 10.1 Review

`GET /compose/<id>/review`, reached by "Проверить и отправить →". For each target of the
selected networks (from the poster's main profile, with checkboxes):

- the monogram, the target id, the language;
- the full text (`white-space: pre-wrap`) and the image of `out/<network>.jpg`;
- the poster's own checks, exactly as `poster publish` runs them: `check_text`,
  `check_image(sniff(...))`, missing variables of the target (names only), LinkedIn token
  problems, and for X `xapi.estimate` ("X: $0.215 с картинкой") and the X month against
  `X_MONTHLY_CAP_USD`;
- a photo post whose network has no saved `out/<network>.jpg` gets the problem "картинка
  для <сеть> не сохранена";
- a problem disables both send buttons and is listed with `role="alert"`.

Then two actions:

- **Опубликовать сейчас** — a native `<dialog>` opened with `showModal()` asks "Опубликовать
  в N сетей сейчас? Это нельзя отменить." with Cancel and Publish (§10.3).
- **В очередь** — a folder select (photo-lane folders for a post with an image, text-lane
  folders for a text post; default the draft's folder) and, for the chosen folder, the
  rule that reads it and its next slot, or "никакое правило не берёт эту папку — пост будет
  ждать" with a link to Правила (§10.4).

Pressing either button is the operator's approval after seeing every variant: decision 4
of §1, and the approval rule of `factory.md` §6.1.

### 10.2 The package written

Both actions write a poster package, schema 1:

```json
{"schema": 1, "id": "2026-11-11-trip-3f2a", "theme": "<theme>",
 "variants": {"facebook": {"text": "…", "image": "media/2026-11-11-trip-3f2a/facebook.jpg"},
              "x": {"text": "…", "image": "media/2026-11-11-trip-3f2a/x.jpg"}},
 "meta": {"approved_by_operator": "2026-11-11", "source": "panel",
          "photo": "p-3f2a9c01b7d4e6a8"}}
```

The images are copied from `out/` into `media/<id>/` next to the package file, so the refs
(with `/`, relative to the package folder) resolve in the poster and pass the panel's `/img`
check. The approval date is today in the machine zone. After writing, the panel loads the
file with `poster.package.load` and checks every variant with `check_text`/`check_image`; a
failure removes what was written and shows the problems.

### 10.3 Publish now

1. Under the draft lock: write `content/packages/<id>.json` with `O_EXCL` (an existing id
   is refused) and its media; the draft becomes `publishing` with `publish.started` and the
   targets.
2. Start one background thread (one publish at a time in the panel; a second gets 409
   "идёт другая публикация"). It calls
   `poster.cli.main(["--env-file", ENV, "publish", PATH, "--targets", "t1,t2"])` in this
   process, exactly as the factory runner does, with output captured and redacted. The
   poster's pre-flight, X ledger, record and partial-failure rules apply unchanged.
3. Redirect to the review page, which now shows per-target progress. `author.js` polls
   `GET /compose/<id>/status` every 3 s; the server answers from the poster record
   (`Records.latest(id, target)` for rows after `publish.started`): `published` with its
   link, `failed` with the reduced error, `unknown — проверьте аккаунт`, or "ждём…".
4. When the thread ends: every target `published` → draft removed, the page shows the links;
   any `failed` → `partial`, with "Повторить упавшие" (the same call; the poster skips
   published targets and refuses unknown ones); exit 2 (pre-flight refusal) → back to
   `draft` with the poster's problems.
5. Ctrl+C on the panel while a publish runs prints "идёт публикация <id>: жду конца
   (Ctrl+C ещё раз — прервать)" and joins the thread. If the process dies anyway, the next
   start finds `publishing` with no record rows for some targets and shows them as
   "прервано — проверьте аккаунт" with the poster command for `--force-target`. The
   panel adds this item to its attention list in `model.build` (`factory/attention.py`
   stays unchanged).

### 10.4 Add to the queue

Under the panel's `write_lock`: pick `NNN` as the largest numeric prefix of the folder's
`*.json` files plus one (three digits, more when needed), write
`stock/<folder>/<NNN>-<id>.json` with `O_EXCL` and its `media/<id>/`, then reload the entry
with `factory.stock.reload_entry` and require no problems (otherwise remove and refuse).
The draft is removed and the page redirects to `/files?folder=<folder>#pkg-<id>`. The
factory then publishes it in file order when a rule reaches it; nothing else changes in the
factory.

### 10.5 The rest of the panel

The new packages appear everywhere the factory already shows packages: folder counts and
runway, Calendar slots, Reach rows after publication. The Connection, Rules, Calendar,
Reach and Followers tabs need no change.

## 11. AI budget guard

### 11.1 Ledger

`<factory state>/ai-ledger.jsonl`, append-only under `ai-ledger.lock`, built on
`poster.state.locked`, `append_jsonl` and `read_jsonl`:

```json
{"ts": "…", "month": "2026-11", "rid": "uuid", "vendor": "anthropic", "model": "claude-sonnet-5-5",
 "op": "generate", "draft": "2026-11-11-trip-3f2a", "price": "0.0733", "status": "reserved"}
{"ts": "…", "month": "2026-11", "rid": "uuid", "status": "ok", "actual": "0.0214",
 "usage": {"in": 4521, "out": 1236}}
```

- `reserve(estimate)`: under the lock, sum the month and refuse when
  `total + estimate > AI_MONTHLY_CAP_USD`; otherwise append the `reserved` row. Then the
  call is sent.
- `settle`: `ok` with `actual` from the vendor's usage; `failed` (counts 0) only for a 4xx
  answer that generated nothing (400, 401, 403, 404, 413, 429); `unknown` (counts the
  reservation) for 5xx, timeouts and transport errors.
- Month total: per `rid`, `actual` when `ok`, the reservation when `reserved` or
  `unknown`, 0 when `failed`, over rows whose reservation month is the current UTC month
  (the X ledger's month rule).
- The refusal text: "Бюджет ИИ: потрачено $9.95 из $10.00, этот запрос — до $0.08. Спросите
  оператора; лимит меняется в .env (AI_MONTHLY_CAP_USD)". Nothing is sent.

### 11.2 Reservation bounds (computed before each call)

| Call | Input bound | Output bound | Bound (typical) |
|---|---|---|---|
| Claude generate | UTF-8 bytes of system + user text (a token is never shorter than a byte) + `⌈w/28⌉·⌈h/28⌉` of the view copy, capped at 4 784 | `max_tokens` 4 000 (6 000 with `en+uk`) | ≈ $0.073, $0.093 with `en+uk` ($0.02) |
| Claude regenerate | same, plus the bytes of the other variants | 1 500 | ≈ $0.05 with typical texts ($0.01) |
| Gemini transcription | 32 tokens/s × 180 s + prompt bytes | 2 000 at $2.50 | ≈ $0.007 ($0.002) |
| Gemini highlight (2K) | prompt bytes + 2 000 for the photo (**U**, G11) at $1.50 | 1 680 image tokens at $30 + 4 000 text or thought tokens at $7.50 (**U**, G11) | ≈ $0.086 ($0.055) |

Settling prices Claude `usage.input_tokens` and `usage.output_tokens`; Gemini
`total_input_tokens` at the input rate, `total_output_tokens` at the image rate (an upper
bound when part of it is text) and `total_thought_tokens` at the text rate. A month of 30
photo posts (one generation, two regenerations, one voice note and one or two styles each)
comes to about $3.70, inside $10.

### 11.3 Price table (`prices.py`, read 2026-11-11)

| Model | Input / MTok | Output / MTok | Source |
|---|---|---|---|
| `claude-sonnet-5-5` | $2.00 | $10.00 | [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| `gemini-3.5-flash-lite` | $0.30 (audio too) | $2.50 (including thinking) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `gemini-nano-banana-2.1` | $1.50 | text $7.50, image $30.00 (2K = 1 680 tokens) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |

Prices live in code next to their URL and date; a price change is a reviewed code change.
The ledger stores the computed dollars, so old rows keep their prices.

### 11.4 Cap setting

`AI_MONTHLY_CAP_USD` in the env file, default `10.00`, a finite decimal ≥ 0 (validated like
`X_MONTHLY_CAP_USD`). Only the operator changes it.

### 11.5 Top bar

A text item after the X meter in `.status`: "ИИ $0.84 из $10.00" in mono, with
`title="Claude + Gemini за <месяц>, по UTC"`. It turns `--red` and reads "ИИ $9.95 из
$10.00 · лимит" when less than $0.10 remains (above every bound of §11.2 with typical
texts). It reads the month total through a one-entry cache keyed by the ledger's
`(ino, mtime_ns, size)` and the current UTC month, owned by the server and passed to the
view through `Ctx`, so a page costs one `stat` and the snapshot is not rebuilt by AI calls.

**Measurement**, taken before choosing where the item goes, because the bar is crowded. Main
at `f09433c` with the full-width lane's `panel.css` (`ea21c24`) applied, in a scratch
export; the data fixture of `tests/panel_fixture.py`; the Files tab;
`chrome-headless-shell` 156.0.8078.4 at device scale 1; text boxes measured with
`getBoundingClientRect`, `scrollWidth` and `Range.getClientRects`; 2026-11-11.

| Viewport | Top bar today | With "ИИ $10.00 из $10.00" (text, 126 px) | With bar + text (190 px) | With "ИИ ноябрь $0.84 из $10.00" + bar (230 px) |
|---|---|---|---|---|
| 390 | 231.8 px, 3 status rows | 255.2 px, 4 rows | — | 255.2 px |
| 900 | 109 px | 109 px (fits the status row) | — | 132.4 px (timer wraps to a third row) |
| 1 280 | 109 px | 109 px | 109 px | 109 px |
| 1 440 | 67 px, one line (41.3 px free) | 109 px (status row under the tabs) | 109 px | 109 px |
| 1 600 | 67 px | 67 px (63.5 px free) | 109 px | — |
| 1 920 | 67 px | 67 px | — | 67 px |

No text was cut in any case (`scrollWidth = clientWidth`, one line per item) and no page
scrolled sideways. The text-only item keeps 900 and 1 600 unchanged and moves the
one-line threshold from about 1 399 px to about 1 537 px of viewport; between them the
status row sits under the tabs, as it already does at 1 280. Folding "· ИИ $0.84 из $10"
into the X meter would need about 113 px (17 mono characters at the measured 6.6 px) where
41 px are free, so it would wrap too while changing the X meter's agreed text. The visual
check's 1 440 screenshots will show the two-row top bar; that is the expected result.

## 12. Keys and models

| Name (env file) | Purpose | Used by |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude Messages API, header `x-api-key` | `factory/authoring/claude.py` |
| `GEMINI_API_KEY` | Gemini Interactions API, header `x-goog-api-key` | `factory/authoring/gemini.py` |
| `AI_MONTHLY_CAP_USD` | optional, AI month cap (default `10.00`) | `budget.py` |

- `KEYS.md` moves `GEMINI_API_KEY` from "Planned" into a new "AI (panel authoring)" table
  with the other two names. Values only in the env file.
- Both key names contain `KEY`, so `poster.redact.Redactor.add_env` already masks their
  values in every page, JSON reply and log line.
- Keys are read from the env file at call time (`config.load_env`), never from the process
  environment, like every other credential here.
- Models (verified 2026-11-11): `claude-sonnet-5-5` (A1), `gemini-3.5-flash-lite` (G2),
  `gemini-nano-banana-2.1` (G6). They are constants in `prompts.py`.
- The Gemini key must belong to a Google Cloud project with an active billing account.
  Otherwise the service is "Unpaid", and Google may have people read the operator's photos
  and voice (G9). The panel cannot detect the tier; the operator confirms it (§17).

## 13. Security

| Threat | Server-side check | Test (hostile input) |
|---|---|---|
| A foreign site posts an upload or starts a paid call from the operator's browser | Every new POST: `Host` (421); for `fetch` bodies `Origin` must be present and equal `http://<Host>`, and `X-CSRF-Token` must match (403). A custom header forces a CORS preflight; the server has no `do_OPTIONS`, so the preflight gets 501 and the browser never sends the request. Form POSTs keep the `csrf` field | POST without the header, with a wrong token, with `Origin: http://evil.example`, without `Origin`; each gets 403 and the ledger, drafts and photos are unchanged |
| DNS rebinding | `Host` check on every route (421) | Wrong `Host` on each new GET and POST |
| Oversized or endless bodies | Per-route `Content-Length` limit checked before reading (413, connection closed); streaming stops at the declared length; free-space check (507) | 26 MB `orig`, 9 MB rendered image, 5 MB audio, 70 KB JSON; missing `Content-Length` (411) |
| Path traversal and symlinks | Folder names by `NAME_RE` and must exist; photo ids by pattern; draft ids by the poster id pattern; draft files from a fixed set (`img/<style>.jpg`, `out/<network>.jpg`); `realpath` must stay inside its root; `photos/` must not be a symlink; temp files `O_EXCL` | `folder=../x`, `id=../../.env`, `name=../../draft.json`, a `photos` symlink to `/tmp`; all 404 or 409 and nothing written outside |
| A non-image saved as a photo | `poster.rules.sniff` on the stored bytes; `orig` JPEG/PNG/WebP, others JPEG | an HTML file sent as `image/jpeg`: 415, temp removed |
| Camera metadata (GPS) reaching a network | Every published image is a canvas re-encode (§9.1). The server walks the JPEG markers of each rendered image and refuses an APP1 segment that starts with `Exif\0\0` | a rendered JPEG with an injected Exif segment: 422 |
| Key values in pages, JSON or logs | Keys only in headers; JSON and HTML replies pass `Redactor.redact`; vendor errors pass `vendor_message`; the panel logs one redacted line per failure and never a request or response body | canary values for both keys; a fake vendor error that echoes the key; no page, JSON reply or log line contains them |
| Photos and voice in git | `content/` is ignored; nothing is written outside `content/` and the state dir | `git check-ignore` holds for `content/stock/f/photos/p.jpg` and `content/drafts/d/voice-1.webm` |
| Data kept by vendors | Gemini requests carry `store: false` (G7); only the view copy (no EXIF) and the hints are sent, never file names or the original | request bodies in tests contain `"store": false` and no `name` field |
| Spending without the operator | Every paid call is one click; the ledger reserves before sending and refuses above the cap; no automatic retries; at most two calls at once | concurrent generate clicks: the second gets 409; a month at $9.95 refuses a $0.08 bound with no vendor request sent |
| Microphone over plain HTTP from another host | The browser refuses it (B1); the panel binds 127.0.0.1 only | — |

The panel's CSP needs no change: `fetch` to the same origin falls under `default-src
'self'`, canvas drawing uses same-origin images, and the design uses no `blob:` URL in
`img-src` or `media-src`. `author.js` sets sizes through the CSSOM, which `style-src
'self'` allows, never through `style` attributes.

## 14. Panel changes

### 14.1 POST route table

`do_POST` stops assuming a form. A table maps each path pattern to its body kind; the
checks run in this order for every POST: `Host`; route lookup (404); `Origin`
(foreign → 403, absent → 403 for non-form kinds); `Content-Length` (411, 400, 413);
`Content-Type` against the kind (415); CSRF (form: the `csrf` field after parsing; other
kinds: `X-CSRF-Token` before reading the body); then the handler.

| Path | Kind | Limit | Content types |
|---|---|---|---|
| `/rules/<action>`, `/files/new-folder` (existing) | form | 16 KB | `application/x-www-form-urlencoded` |
| `/compose/new`, `/compose/<id>/publish`, `/compose/<id>/queue`, `/compose/<id>/delete` | form | 16 KB | same |
| `/files/photos` | image | `orig` 25 MB, `thumb`/`view` 2 MB | `image/jpeg`, `image/png`, `image/webp` |
| `/compose/<id>/image` | image | 8 MB | `image/jpeg` |
| `/compose/<id>/voice` | audio | 4 MB | `audio/webm` |
| `/compose/<id>/generate`, `/text`, `/settings`, `/highlight` | json | 64 KB | `application/json` |

JSON replies go through one helper: `Content-Type: application/json; charset=utf-8`,
`Cache-Control: no-store`, the body redacted, errors as `{"error": "<Russian text>"}` with
400, 403, 404, 409, 413, 415, 422, 502 (vendor error) or 504 (vendor timeout).

### 14.2 GET routes

`/photo` (§6.5), `/compose` (drafts list), `/compose/<id>`, `/compose/<id>/review`,
`/compose/<id>/file?name=…` (draft images, same checks as §6.5), `/compose/<id>/status`
(JSON, §10.3).

### 14.3 Rendering rules for the new pages

The rules of `factory.md` §14 apply. In addition:

- Each state has its own visible words: "черновик", "генерация…", "расшифровка…",
  "длиннее лимита: X 312/280", "бюджет ИИ исчерпан", "нет GEMINI_API_KEY в .env",
  "запись голоса работает только по адресу localhost", "публикуется…", "опубликован ·
  открыть", "ошибка: …", "прервано — проверьте аккаунт", "в очереди: <папка> · ближайший
  слот <дата>".
- A button that spends shows its bound ("до $0.08") as text, and the top bar shows the month.
- The publish confirmation is a modal `<dialog>`; Escape and Cancel close it.
- Busy buttons are disabled and keep their width; results replace their own card, never
  the page.
- No horizontal scroll from 390 to 1 920; long texts wrap (`overflow-wrap: anywhere`);
  previews keep their aspect ratio inside a fixed box.

## 15. Slices (build lanes)

Order **A → B → C → D**. A needs no keys. B adds the ledger with the first paid call. C
adds images. D sends. After B, D can already send text posts if the operator wants that
sooner; photo posts need C for the per-network crop (Instagram refuses a 3:4 phone photo,
aspect 0.75, `rules.py:26`).

### 15.1 A: Photos in Files

- **Builds:** `factory/authoring/photos.py`; the POST route table (§14.1) with the header
  CSRF; `/files/photos`; `/photo`; the "Фото · N" section, grid and photo chips; photo
  counts on cards; the upload loop in `author.js`; strings; a README paragraph.
- **Acceptance:**
  1. Server (unit tests over `http.client`, port 0): posting the three bodies of 18
     fixture images (JPEG with EXIF orientation 6, PNG, WebP; made by the fixture's
     stdlib JPEG writer and byte templates) stores 18 originals byte-identical (SHA-256
     equal), their thumbs and view copies, and 18 index rows; a HEIC-signature body and a
     text body get 415 and leave nothing behind. Posting the same originals again answers
     `dup: true` and stores nothing.
  2. Browser (visual check, probe mode): the probe passes the stored EXIF-6 original,
     fetched from `/photo`, to the same `author.js` function the upload loop uses, and
     reports the thumb and view sizes; the copies are portrait (height > width). The
     folder-picker part is LC5.
  3. Every §13 row that concerns uploads and `/photo` holds (tests over `http.client`
     against port 0).
  4. The existing rules and new-folder forms behave exactly as before (the existing panel
     tests pass unchanged).
  5. An upload cut after `orig` leaves no index row; a repeat completes it.
- **Checks:** `python3 -I -B -m unittest discover -s tests -t .`;
  `python3 tools/visual_check.py --out DIR` with new states "files with photos" and "folder
  view with photos" at 390, 900, 1 280, 1 440, 1 600 and 1 920; `git status --short
  --ignored` clean after the tests.
- **Operator provides:** nothing.
- **Live check:** LC5 (upload part) by the operator.

### 15.2 B: Drafts, texts, voice, budget

- **Builds:** `drafts.py`, `budget.py`, `prices.py`, `prompts.py`, `claude.py`,
  `gemini.py` (transcription), the composer page without image templates, the AI item in the
  top bar, `KEYS.md` and the README section "Создание постов в панели".
- **Acceptance:**
  1. With a fake transport, "Сгенерировать" sends one request whose body matches §8.4 (model,
     version header, `output_config`, the image block, no `temperature`), stores the four
     variants and answers the poster's checks; an X variant of 312 weighted characters is
     kept whole and marked with the poster's error.
  2. `refusal` and `max_tokens` answers show their texts and settle as billed.
  3. Regenerating X changes only `variants.x`.
  4. Budget: with the month at $9.95 and a cap of $10, generate is refused before any
     request (the fake transport sees zero calls); the top bar is red. Two concurrent
     reservations that each fit alone but not together: exactly one passes. A 500 answer
     settles `unknown` and keeps the reservation; a 400 settles `failed` at 0.
  5. Voice: a fixture WebM is posted, the fake Gemini answers a transcript, it lands in the
     hints, and the audio file is gone; on a fake 503 the file stays and "Повторить
     расшифровку" is offered. The request carries `"store": false`.
  6. Revision: two saves from the same revision; the second is refused with the reload
     text.
  7. Canary values for both keys never appear in pages, JSON replies or the captured log.
- **Checks:** the project's test command; the visual check with states "composer empty",
  "composer generated with an X error", "budget refused", "no keys"; clean
  `git status --short --ignored`.
- **Operator provides:** `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` in the env file; the
  Gemini project's billing confirmation (§12).
- **Live checks:** LC1, LC2.

### 15.3 C: Images

- **Builds:** canvas templates (§9.1), `/compose/<id>/image`, the Exif marker walk, the
  Gemini edit call (§9.2), the side-by-side strip and the pick (§9.3).
- **Acceptance:**
  1. In probe mode the composer renders a 3024 × 4032 fixture photo for each network and
     posts the results to `/compose/<id>/image`: Instagram 1080 × 1350, Facebook and
     LinkedIn 1536 × 2048, X 1600 × 900, all JPEG; each passes `check_image` for its
     network; none has an APP1 Exif segment.
  2. Frame and quote render inside the output; the quote text fits in at most 4 lines at
     the widths of the fixture (measured by the probe with a `Range`).
  3. With a fake Gemini answer holding a JPEG, "Размыть фон" stores `img/blur.jpg`, shows it
     next to the original, and the ledger has one reservation and one `ok` row. An answer
     with only text shows "Gemini не вернул картинку".
  4. Choosing a style as the base redraws every network preview from it.
- **Checks:** the project's test command; the visual check with states "composer with
  styles side by side" and "per-network previews" at the six widths; the reviewer looks at
  every PNG.
- **Operator provides:** one photo of themselves for LC3, and a verdict on whether the face
  stayed the same.
- **Live check:** LC3.

### 15.4 D: Review and send

- **Builds:** the review page, `send.py`, publish thread and status polling, queue
  writing, interrupted-publish attention item, Ctrl+C wait.
- **Acceptance:**
  1. Review lists every variant with the poster's checks; a missing variable disables both
     buttons with the variable's name.
  2. Publish now with a fake poster entry point that records rows for two targets and fails
     a third: the page shows two links and one error, the draft is `partial`, and "Повторить
     упавшие" calls the poster again with the same targets.
  3. A second publish click while one runs gets 409; the poster is called once.
  4. Queue writes `NNN-<id>.json` with `approved_by_operator` and media; `factory check`
     passes; `factory plan` assigns it to the first slot of the folder's rule after the
     folder's earlier ready packages (file order); the draft is gone.
  5. A queued package's images open through `/img`.
  6. A crash injected after `publishing` shows "прервано — проверьте аккаунт" and the
     attention item after restart; nothing is published again by itself.
- **Checks:** the project's test command; the visual check with states "review", "review
  with a problem", "publishing", "partial"; clean `git status --short --ignored`.
- **Operator provides:** OK for LC4 and the name of the test Page.
- **Live check:** LC4.

## 16. Unconfirmed facts and live checks

All live checks need the operator's OK; their total cost is under $0.20.

| Id | Settles | Cheapest check | Cost |
|---|---|---|---|
| LC1 | A8; the Claude reply shape and `usage` on the real key | One "Сгенерировать" on one fixture photo with short hints. If `between_tools` is refused with the JSON format, omit `thinking` (adaptive at `effort: low`) | ≈ $0.02 |
| LC2 | G10, G11 (thinking bound); WebM accepted inline; transcript location; `usage` names | One 5-second voice note in Ukrainian or Russian. If `v1beta` with `Api-Revision` fails, switch the URL to `v1` (G8) | ≈ $0.001 |
| LC3 | G11 (photo token count), G12, G13; the image block's place in the reply | One "Размыть фон" on a photo of the operator at 2K. If `aspect_ratio` is refused, drop the field. If Gemini refuses or changes the face, build the code "spotlight" of §18 | ≈ $0.06 |
| LC4 | The panel's publish path end to end | "Опубликовать сейчас" of one photo post to a test Page only; then `python3 -m poster delete` | free |
| LC5 | B5, B6; folder upload from Windows | The operator opens `http://localhost:8770/`, uploads about 20 phone photos, records a short voice note; `MediaRecorder.isTypeSupported("audio/webm;codecs=opus")` is shown in the composer's details | free |

If B6 fails (the panel is reached by a WSL address), voice stays off with its message, and
the rest works; a Chrome flag that treats that origin as secure would be the operator's own
choice.

## 17. Open items for the operator (non-blocking)

1. **Gemini billing:** the key's Google Cloud project has an active billing account (G9).
   Without it, photos and voice fall under the free tier's human review.
2. **Keys:** `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` in the env file (lane B).
3. **Cap:** `AI_MONTHLY_CAP_USD` stays at the decided 10.00 unless the operator changes it.
4. **LC3 photo and verdict**, and **the test Page for LC4**.

No question here changes the design; each has a default above.

## 18. Deferred — not currently justified

| Item | Why deferred | Trigger to build |
|---|---|---|
| Code "spotlight" highlight (darken or blur outside an oval the operator places) | The operator chose Gemini for highlighting | LC3 shows a refusal or a changed face |
| Drag-to-crop | One click for the focus point plus ratio choices covers the crops | Operator asks for finer crops |
| `claude-haiku-5-5` or a model picker | Sonnet 5.5 costs about $0.02 a post, far inside the budget | Budget pressure or the operator asks |
| `gemini-3.5-transcribe` | Needs a Files API upload first; flash-lite takes inline audio | Poor transcripts of mixed Russian and Ukrainian |
| Generating all styles at once | Spends on results nobody asked for | Operator asks |
| Audio playback before transcription; keeping recordings | The transcript is what gets checked; recordings are personal data | Operator asks |
| HEIC decoding | No decoder in the browser on Windows or in the standard library | Operator's phone cannot export JPEG |
| Several photos per post, carousels, video | The poster publishes one image per network | Poster gains carousels or video |
| Alt text | Not asked; the poster does not send it (`poster.md` §17) | Operator asks |
| "Publish at a chosen time" for one post | The queue and the rules cover scheduling | Operator asks |
| "Next in queue" placement | File order decides; reordering is deferred in `factory.md` §18 | Frequent reordering |
| Editing queued packages in the panel | Approval happens on the review page; the orchestrator can still edit files | Operator asks |
| Batch generation for a whole folder | AGENTS rule 1: no bulk paid generation without a confirmed budget; one click per post fits USD 10 | Operator confirms a batch budget |
| Prompt caching, Files APIs | Small prompts, one photo per call | Larger prompts or many photos per call |
| Price overrides in the env file | Prices come from official pages with dates; a change is a code change | Prices change often |
| Server-side image processing | Needs pip or a system tool | A dependency is accepted |
| No-JS authoring, multipart parsing with `email` | The steps need JS (D9) | — |
| AI keys on the Connection tab | Their state shows where they are used (composer) | Operator asks |
| A CLI for the AI ledger | The top bar shows the month | The ledger needs auditing outside the panel |

## 19. Sources (read 2026-11-11)

Anthropic: [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) ·
[Pricing](https://platform.claude.com/docs/en/about-claude/pricing) ·
[Vision](https://platform.claude.com/docs/en/build-with-claude/vision) ·
[API versions](https://platform.claude.com/docs/en/api/versioning) ·
[Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) ·
[Effort](https://platform.claude.com/docs/en/build-with-claude/effort) ·
[API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)

Google: [Models](https://ai.google.dev/gemini-api/docs/models) ·
[Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) ·
[Nano Banana 2.1](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1) ·
[Pricing](https://ai.google.dev/gemini-api/docs/pricing) ·
[Audio understanding](https://ai.google.dev/gemini-api/docs/audio) ·
[Transcription](https://ai.google.dev/gemini-api/docs/transcribe) ·
[Image generation](https://ai.google.dev/gemini-api/docs/image-generation) ·
[Interactions](https://ai.google.dev/gemini-api/docs/interactions) ·
[Interactions API reference](https://ai.google.dev/api/interactions-api-v1) ·
[Terms](https://ai.google.dev/gemini-api/terms)
(the `ai.google.dev` pages redirect to `aistudio.google.com/docs/…` with the same content)

Browser: [getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) ·
[Secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) ·
[webkitdirectory](https://developer.mozilla.org/en-US/docs/Web/API/HTMLInputElement/webkitdirectory) ·
[createImageBitmap](https://developer.mozilla.org/en-US/docs/Web/API/Window/createImageBitmap) ·
[toBlob](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/toBlob)

Project: `docs/design/poster.md` (limits, ledger, record) · `docs/design/factory.md`
(stock, approval, panel §11, §14, §18) · `docs/design/panel-brief.md` (named widths).
