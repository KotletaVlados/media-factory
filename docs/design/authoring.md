# Authoring posts in the panel: «Создать», topics, Gemini texts, photos, send

Design document. Status: slices A, B′ and D′ are built (`main` at `4dd221f`). Slice C
(ratio choices, frame, quote, Gemini highlight styles) is pinned in §18 and ready to build.
M follows (§15).

History:

- First written on 2026-11-11 against `f09433c`.
- Revised on 2026-11-12 against `main` at `82b8311` for slice B′. That revision follows the
  operator's decisions of 2026-11-12 (texts by Gemini, the «Создать» entry, «Медиатека»)
  and the seed-to-result research report of 2026-11-12, which is kept outside the
  repository.
- Revised on 2026-11-13 against `main` at `eb75f0a` for slice D′, after the operator's
  decisions of 2026-11-13 (send before images; a plain crop for each network).
- Revised on 2026-11-13 against `main` at `4dd221f` for slice C (§18). Where §7.1, §9 or
  §11 differ from the code as merged, §18 follows the code and says so.

Vendor and browser documentation was read on the dates given in §4, and each external fact
cites its page. Legend: **C** means confirmed on the cited official page; **O** means
observed on this machine; **U** means unconfirmed, and §19 names the cheapest check for
each.

## 1. Originating requirement

This repository is public, so the operator's words are paraphrased here in the third
person. The verbatim words, with their dates and times, are in the pinned specification of
the slice B′ task.

**2026-11-11, in chat with the orchestrator.** The operator uploads their own folder
(photos for now) in the Files tab. Below, where the text posts are, they want to sketch a
text by typing or by voice. From that, the publications for the other networks should be
made with the photo as the base. Later they want to select one photo, have the text filled
in from their hints or just by a button, adapted for each network, and then press one
button that sends everything.

**2026-11-12 18:20 UTC, a voice message to the orchestrator:**

- The operator does not understand what the Files section and its folders are for.
- They want to drop in a photo of themselves and "spin" a topic into a publication for all
  networks at once, each in its own format and for its own audience: a short one for X, a
  business one for LinkedIn, one for Instagram, another for Facebook.
- The panel should suggest the topic, or they type a topic into some window and the panel
  helps expand it.
- They want to start with photos; video should later work the same way.
- They want to make the minimum of movements, with their own face in the posts: "drop in a
  seed, get a finished result".
- The files live on their computer and are uploaded from there.

Decisions in force (the operator's forms and answers):

| When | Decision |
|---|---|
| 2026-11-11 | One shared AI budget of USD 10 per month for texts, photo processing and voice; above it the panel refuses and asks. Voice: recorded audio, recognised by Gemini. Send (slice D): review all variants, then «Опубликовать сейчас» or «В очередь» |
| 2026-11-12 18:04 UTC | Texts are written by **Gemini**, not Claude. The project has no Anthropic key and takes no Anthropic dependency |
| 2026-11-12 ~18:43 UTC | Build the photo phase by the research plan: «Создать» is the first tab, then drop a photo, then 3–5 topic suggestions from Gemini (or an own topic typed or dictated), then «Развернуть» gives four per-network texts, then (D) review and publish or queue. Rename «Файлы» to «Медиатека»: all photos with status marks; schedule-queue folders move deeper and are created automatically. Use the existing Gemini key; the operator has billing on or will turn it on |
| Earlier | X and LinkedIn texts in English, Instagram and Facebook in Ukrainian; panel UI in Russian; X capped at USD 5 per month (poster ledger); the operator reviews texts before anything is published; code templates for photos (quote, frame, per-network crop) |
| 2026-11-11 and 2026-11-12 | Gemini highlights the main person (blurred background, glow or outline), with several styles to choose from, inside the shared AI budget (built in C, §18) |
| 2026-11-13 ~01:35 UTC | Build slice D (send) before C (images), so the first real post leaves the panel sooner |
| 2026-11-13 07:01 UTC | D plus a simple automatic crop for each network, without effects, so the first post comes as fast as possible; templates and «highlight me» come later in C (§17) |

### 1.1 Validation against the requirement

| Requirement | Where this design meets it |
|---|---|
| "What is the Files folder for?" | «Создать» is the entry and opens first (§8.1). The operator never names or picks a folder: uploads land in «Мои фото», which is created by itself (§8.8). The tab is called «Медиатека» (§8.8). Queue folders move under a collapsed section in slice M (§15) |
| Start with a photo of me | The «Создать» page is one drop zone plus recent photos (§8.2). Photos stay on this computer (§6) |
| Suggest a topic, or I type one and we expand it | Topic cards from Gemini, based on the photo and the author profile (§8.3, §8.4). An own topic is typed or dictated (§8.3, §8.5). «Развернуть» expands it (§8.4) |
| X short, LinkedIn business, Instagram one, Facebook another, for each audience | One text per network with its own language, length and angle (§8.4). «Профиль автора» names the audience of each network and goes into every request (§8.7) |
| Minimum of movements | Three actions to four texts: drop a photo, tap a topic card, «Развернуть». Topics arrive without a click (§8.3) |
| Type or dictate | Topic box plus «Голос», with Gemini transcription (§8.5) |
| Maybe process the photo, maybe not | Slice D′: one plain crop per network, automatic, centred or moved by one tap (§17). Slice C: ratio, frame and quote per network, and Gemini highlight styles of the operator, each optional, on the review page (§9, pinned in §18) |
| One button sends everything | Slice D′: review every variant, then publish now or queue, three movements after the texts (§10, §17) |
| USD 10 a month for AI, then ask | One ledger, reservation before every call, refusal in Russian, month shown on «Создать» (§11) |
| Video the same way, later | A separate task; not designed here (§21) |

Every row is built in slices B′, D′, C and M (§15). Cut scope is in §21.

## 2. What exists today

Facts read from `main` at `82b8311` on 2026-11-12.

**Panel** (`factory/panel/`, design `factory.md` §11, brief `panel-brief.md`):

- `server.py`: a `ThreadingHTTPServer` on `127.0.0.1` with `daemon_threads = True`
  (`server.py:109-110`). Every request checks `Host` (421). POST goes through a route table
  (`post_route`, `server.py:77`; `Route`, `:58`) with two kinds today: `form` (rules
  actions and `/files/new-folder`, at most `MAX_BODY = 16 * 1024`) and `image`
  (`/files/photos`). `do_POST` (`:293`) checks, in order: Host, route, Origin (absent →
  403 for non-form kinds), Content-Length (411/400/413), Content-Type (415), then CSRF
  (the `csrf` field for forms, the `X-CSRF-Token` header before any body byte for other
  kinds). JSON replies go through `_json` (`:357`): `no-store`, body redacted.
- `end_headers` adds `SECURITY_HEADERS` (`:44`): `default-src 'self'; img-src 'self';
  style-src 'self'; script-src 'self'; frame-ancestors 'none'`, plus `nosniff` and
  `Referrer-Policy: same-origin` (Chrome sends `Origin: null` on form POSTs under `no-referrer`). `log_message` logs nothing (`:130`).
- `GET /` redirects to `/connection` (`:175`); pages come from `PAGES` (`:50`).
- `model.py`: one snapshot, rebuilt when `state_key` changes (`:87`; a depth-1 walk of
  `content/stock/` plus one stat per photo index). `photo_uses` (`:503`) marks photos
  "published" or "queued" from stock packages whose `meta.photo` names them; its docstring
  says drafts join in lane B.
- `views.py`: `page` (`:114`) draws the tab bar from `strings.TABS` (`strings.py:13`) and
  takes `sub` and `sub_right` for the row under the top bar. `files` (`:435`) draws the
  lanes «Фото-посты» and «Текстовые посты» with folder cards (`_folder_card`, `:397`).
  `_folder_view` (`:475`) adds, for a photo-lane folder, the «Фото» section
  (`_photos_section`, `:522`): two upload buttons, a newest-first grid of 60 per step, and
  the chips «в очереди» and «опубликовано».
- `static/author.js` (slice A) holds `makeCopies(blob)` (`:44`, exported as
  `window.MFAuthor.makeCopies`) and the upload loop. `uploadOne` (`:162`) posts `orig`,
  `thumb` and `view` for one file inside a closure bound to the folder view's section.

**Photos** (`factory/authoring/photos.py`, slice A): uploads stream into
`stock/<folder>/photos/` with an id of `p-` plus 16 hex digits of the SHA-256 (§6). The
folder must exist and be of lane `photo` (`folder_path`, `photos.py:74`). `pre_check`
(`:236`) runs every check that needs no body byte.

**Poster** (`poster/`), unchanged since the first revision:

- Checks (`rules.py`) never truncate: X allows 280 weighted characters and 1 cashtag.
  Instagram allows 2 200 UTF-16 units, 30 hashtags and 20 mentions. LinkedIn allows 3 000
  units after escaping (`check_text`, `rules.py:301`).
- `state.read_jsonl`, `append_jsonl` and `locked` (`state.py:29-64`) are public helpers.
- `http.json_request` builds a JSON request. `UrllibTransport` is HTTPS only, follows no
  redirects, and raises `TransportError` without details (`http.py`).
- `vendor_message` reduces a vendor error body and masks long runs.
- `redact.Redactor.add_env` masks the value of every variable whose name contains `KEY`,
  `TOKEN` or `SECRET`.

**Tests**:

- `tests/base.py` blocks every non-loopback connect and resolve (`_guard_connect`, `:36`)
  and puts canary secrets in the fake env (`CANARIES`, `:57`). Its `FakeTransport`
  (`:103`) answers scripted responses.
- `tests/panel_fixture.py` builds the data, empty and photo fixtures (`build_photos`,
  `:492`). `PanelCase` (`:532`) runs a panel on port 0.
- `tools/visual_check.py` renders every state at 390, 900, 1000, 1100, 1200, 1279, 1280, 1440, 1600 and 1920
  with the cached Chromium and runs `probe.js`.

**Machine** (O, 2026-11-12): Python 3.12.3, standard library only. The env file of the
primary checkout has a `GEMINI_API_KEY` line (checked by name; the value was not read). It
has no active `ANTHROPIC_API_KEY` line and no `AI_MONTHLY_CAP_USD` line.

## 3. Decisions and trade-offs

| # | Decision | Rejected options | Why |
|---|---|---|---|
| D1 | All pixel work (thumbnails, crop, frame, quote, re-encoding) runs in the browser on `<canvas>`; the server only stores and validates bytes | Pillow; ImageMagick or ffmpeg; headless Chromium on the server; Gemini for crops | The standard library has no image codec. Canvas output has no camera metadata (built in A) |
| D2 | One file per POST as the raw body, CSRF in a header | `multipart/form-data` with `cgi` or `email` | Streams to disk with a hard limit and needs no parser (built in A) |
| D3 | Drafts live in `content/drafts/<id>/`. Only D's «В очередь» and «Опубликовать сейчас» write packages | Drafts as unapproved packages in stock folders | Factory states stay unchanged; drafts hold topics, AI results and later style images |
| D4 | AI calls run in the request thread with a 120 s deadline and at most two at a time. Publishing (D) runs in a background thread | One job queue for everything | An AI call ends within seconds and the page waits; a publish can take over 5 minutes |
| D5 | Gemini through the Interactions API with `"store": false` | `generateContent` (legacy, still supported, G9) | The current guides for structured output, audio and image editing use Interactions (G1, G4). Interactions stores requests for 55 days on the paid tier unless `store` is false (G9) |
| D6 | Texts and topics with Gemini structured output: `response_format` of type `text`, `mime_type` `application/json` and a JSON `schema` | Free text parsed by hand; function calling | The schema is checked by the vendor, `minItems`/`maxItems` are enforced (G4), and the JSON is the text of the `model_output` step (G6) |
| D7 | Texts and topics with `gemini-3.8-flash` at `thinking_level: "low"` | `gemini-4-hydrogen`; `gemini-3.5-flash-lite` | 3.8 Flash is the model the research report names. It is stable, takes images, supports structured output and costs $0.75 / $3.75 per MTok through 2026-12-31 and $1.50 / $7.50 after (G2, G3). Google's overview recommends Hydrogen for new projects, but it costs $1.50 / $7.50 now and thinks at `high` by default (G2, G3, G5). Flash-Lite is cheaper but Google describes it for throughput, not writing. The model is one constant in `prompts.py` (§21 names the trigger to switch) |
| D8 | Transcription with `gemini-3.5-flash-lite` and inline audio | `gemini-3.5-transcribe` | Inline WebM and OGG audio are documented for general models (G8). The transcribe model's examples upload through the Files API first, which costs two requests and a clean-up |
| D9 | Authoring pages need JavaScript; with JS off they say so | A no-JS path for each step | Drop, recording and canvas exist only in JS. «Профиль автора» is a plain form and works without JS |
| D10 | The AI month is shown in the row under the top bar on every «Создать» page, not in the top bar | A top-bar item (first revision) | The top bar already gains the «Создать» tab and the longer «Медиатека» label. Measured in §11.5: the bar keeps its heights except at 1 414–1 513 px, where it moves to two rows as it already does at 1 280. The AI spend happens only on «Создать», so the fact sits there once |
| D11 | «Создать» is the first tab and `GET /` redirects to it. «Медиатека» is a label change of the `files` tab; its URL stays `/files` | Rename the URL to `/media` | Attention links (`model.attention_link`), the visual check, the tests and the operator's bookmarks keep working. The URL is not shown as text |
| D12 | Uploads from «Создать» go to the stock folder `my-photos` («Мои фото», lane `photo`). The upload route creates it on the first `orig` upload, by renaming a prepared dot-folder | A GET that creates it; a separate "ensure" POST; storage outside the stock | A GET never writes. The rename is atomic, so two first uploads leave one valid folder. Slice A's storage, listing and `/photo` serve it unchanged, and the stock loader skips dot-names (`stock.py:175`) |
| D13 | A new draft asks Gemini for topics once, by itself (≈ $0.005, bound shown on the drop zone) | A «Предложить темы» click first; a request on every page load | One movement less, as the operator asked. The draft records that its automatic request was made, so a reload never spends again |
| D14 | Voice audio stays in the page. The server holds it in memory for one call and never writes it to disk | Storing `voice-<n>.webm` for a retry (first revision) | No recording of the operator's voice on disk. The page keeps the blob for «Повторить расшифровку» |
| D15 | Draft writes are per field, under a short per-draft lock; the last write wins | A whole-file revision on every write | An AI result that arrives while the operator types would make the next autosave stale. The panel is local and used by one operator |
| D16 | «Перегенерировать» sends the topic, the profile, the photo, that network's current text and the wish | All four texts as context (first revision) | The reservation bound stays small and fixed. Consistency across networks comes from the shared topic and profile |
| D17 | «Профиль автора» is one form page saved to `content/profile.json` | Profile in the env file; a profile that learns from edits | The content folder is ignored by git and holds the operator's own data. Learning from edits is deferred (§21) |

## 4. Vendor and platform facts

### 4.1 Google (Gemini), read 2026-11-12 unless marked

The `ai.google.dev` pages redirect to `aistudio.google.com/docs/…` with the same content.

| # | Fact | Status | Source |
|---|---|---|---|
| G1 | `POST https://generativelanguage.googleapis.com/v1beta/interactions` with headers `x-goog-api-key`, `Content-Type: application/json` and `Api-Revision: 2026-05-20` (in the REST examples of the audio and structured-output guides). Input blocks: `{"type": "text", "text": …}`, `{"type": "image", "data": <base64>, "mime_type": …}`, `{"type": "audio", "data": <base64>, "mime_type": …}` | C | [Audio](https://ai.google.dev/gemini-api/docs/audio), [Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding), [Structured output](https://ai.google.dev/gemini-api/docs/structured-output) |
| G2 | `gemini-3.8-flash`: "Stable"; inputs "Text, Image, Video, Audio, and PDF"; output "Text"; input limit 1 048 576, output 65 536 tokens; Structured outputs and Thinking supported; latest update September 2026. The models overview calls it "Our previous-generation Flash model" and says "For any new projects, use our latest models: Gemini 4 Hydrogen or 3.5 Flash-Lite". `gemini-3.5-flash-lite`: Stable, the same inputs, text output, Structured outputs and Thinking supported, latest update July 2026 | C | [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite), [Models](https://ai.google.dev/gemini-api/docs/models) |
| G3 | Paid Standard prices per 1M tokens. `gemini-3.8-flash`: input "$0.75 through December 31, 2026", "$1.50 starting January 1, 2027"; output, thinking included, "$3.75 through December 31, 2026", "$7.50 starting January 1, 2027". `gemini-3.5-flash-lite`: input $0.30 (text, image, video, audio), output $2.50 including thinking. `gemini-4-hydrogen`: $1.50 / $7.50. "Used to improve our products": free tier Yes, paid tier No | C | [Pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| G4 | Structured output on Interactions: `"response_format": {"type": "text", "mime_type": "application/json", "schema": {…}}`. Supported: the types string, number, integer, boolean, object, array, null; `enum`, `items`, `minItems`/`maxItems` (enforced), `properties`, `required`, `additionalProperties`. `minLength`/`maxLength` are "ignored by the server". A schema over the limits gives `400 INVALID_ARGUMENT`. The reference's TextResponseFormat allows `mime_type` `application/json` or `text/plain`; `schema` is "Only applicable when mime_type is application/json" | C | [Structured output](https://ai.google.dev/gemini-api/docs/structured-output), [Interactions API reference](https://ai.google.dev/api/interactions-api-v1) |
| G5 | `generation_config.thinking_level`. On `gemini-3.8-flash`: low, medium, high, default medium; "minimal" is "Not supported". On `gemini-3.5-flash-lite`: minimal, low, medium, high, default minimal. `max_output_tokens` "sets the maximum number of tokens a response can generate, including thought tokens". Hitting it gives the status `incomplete`, and the thinking tokens are still billed. Thought tokens are billed as output | C | [Thinking](https://ai.google.dev/gemini-api/docs/thinking) |
| G6 | Response: `status` is one of `in_progress`, `requires_action`, `completed`, `failed`, `cancelled`, `incomplete`, `requires_continuation`. `incomplete` means "completed, but contains incomplete results (e.g. hitting max_tokens)". `steps` holds a `model_output` step whose `content` has `{"type": "text", "text": …}` blocks. `usage` has `total_input_tokens`, `total_output_tokens`, `total_thought_tokens`, `total_tokens` and per-modality counts. The request has `store`, `generation_config`, `response_format` and `system_instruction` | C | [Interactions API reference](https://ai.google.dev/api/interactions-api-v1) |
| G7 | Image input on Gemini 3 and 4 costs, per `resolution`: low 280 tokens, medium 560, high 1 120, ultra_high 2 240. The default ("unspecified") is 1 120. `resolution` sits in the image block. Image types: PNG, JPEG, WebP, HEIC, HEIF. The whole request is at most 20 MB | C | [Media resolution](https://ai.google.dev/gemini-api/docs/media-resolution), [Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding) |
| G8 | Audio: "32 tokens per second of audio". Formats include WebM, OGG and Opus. "Maximum request size is 20 MB total" | C | [Audio](https://ai.google.dev/gemini-api/docs/audio) |
| G9 | "By default, the API stores all Interaction objects (`store=true`)": 55 days on the paid tier, 1 day on the free tier. `store=false` opts out. "the original `generateContent` API remains fully supported" (now called legacy) | C | [Interactions](https://ai.google.dev/gemini-api/docs/interactions) |
| G10 | Unpaid services: "human reviewers may read, annotate, and process your API input and output"; "Do not submit sensitive, confidential, or personal information to the Unpaid Services". Paid services: prompts and responses are not used to improve products. Paid means a Cloud project with an active billing account (read 2026-11-11) | C | [Gemini API terms](https://ai.google.dev/gemini-api/terms) |
| G11 | Slice C's facts, read 2026-11-11: `gemini-nano-banana-2.1` is stable and edits images; output images at 2K are 1 680 tokens ($0.0504); every result carries SynthID; `response_format` of type `image` with `aspect_ratio` and `image_size`. `gemini-3.5-transcribe` uploads through the Files API in its examples | C | [Image generation](https://ai.google.dev/gemini-api/docs/image-generation), [Nano Banana 2.1](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1), [Transcription](https://ai.google.dev/gemini-api/docs/transcribe) |
| G12 | The guides use `v1beta` with `Api-Revision: 2026-05-20`; the reference shows `POST /v1/interactions` with no such header. Which one the key accepts | **U** (LC1) | G1, G6 |
| G13 | The reference says `steps` is present "when included in the response" and names no request field for it. The SDK reads `output_text`, which is not in the reference's REST fields. Where the text sits in a real REST reply | **U** (LC1) | G6 |
| G14 | Whether `total_output_tokens` already includes `total_thought_tokens` | **U** (LC1) | G6 |
| G15 | The schemas of §8.4 (with `minItems`, `maxItems` and `additionalProperties: false`) are accepted on 3.8 Flash at `thinking_level: "low"`; `"resolution": "high"` is accepted on an inline image block; inline `audio/ogg` and `audio/webm` are accepted on 3.5 Flash-Lite | **U** (LC1) | G4, G7, G8 |
| G16 | How a safety block looks in a reply. The reference names no reply-side safety field | **U** (LC1, if it occurs) | G6 |
| G17 | Slice C's open facts: the photo's token count on Nano Banana 2.1, the full `aspect_ratio` list, and whether the operator's face is kept | **U** (LC3) | G11 |

### 4.2 Browser and codecs

| # | Fact | Status | Source |
|---|---|---|---|
| B1 | `getUserMedia` works only in secure contexts; "in insecure contexts, `navigator.mediaDevices` is `undefined`". `http://localhost` and `127.0.0.0/8` are potentially trustworthy; a LAN address over plain HTTP is not (read 2026-11-11) | C | [getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia), [Secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) |
| B2 | `webkitdirectory` folder selection; `createImageBitmap` applies EXIF orientation; `canvas.toBlob(cb, "image/jpeg", q)` (read 2026-11-11, used by A) | C | [webkitdirectory](https://developer.mozilla.org/en-US/docs/Web/API/HTMLInputElement/webkitdirectory), [createImageBitmap](https://developer.mozilla.org/en-US/docs/Web/API/Window/createImageBitmap), [toBlob](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/toBlob) |
| B3 | File drop: the target must cancel `dragover` for `drop` to fire. Dropped files are read with `DataTransferItem.getAsFile()`. Cancel `drop` on `window` for file drags, or the browser may open the dropped file | C | [File drag and drop](https://developer.mozilla.org/en-US/docs/Web/API/HTML_Drag_and_Drop_API/File_drag_and_drop) |
| B4 | `new MediaRecorder(stream, {mimeType, audioBitsPerSecond})`; `MediaRecorder.isTypeSupported()` checks a type; an unsupported type throws `NotSupportedError` | C | [MediaRecorder()](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/MediaRecorder) |
| B5 | Opus "scales from low bitrate narrowband speech at 6 kbit/s to very high quality stereo music at 510 kbit/s" | C | [RFC 6716](https://www.rfc-editor.org/rfc/rfc6716) |
| B6 | The operator's browser records `audio/webm;codecs=opus` and reaches the panel at `http://localhost:8770/` (so the microphone is allowed by B1) | **U** (LC5) | — |

## 5. Layout

### 5.1 Code

```
factory/authoring/            standard library only
  photos.py     (A) upload, ids, index, listing, paths; (B′) ensure_default()
  drafts.py     (B′) draft schema, create, load, per-field update, AI lock, list cache
  profile.py    (B′) profile schema, limits, load, save, prompt block
  budget.py     (B′) AI ledger: reserve, settle, month total, cap, static bounds
  prices.py     (B′) dated price table with source URL and read date
  prompts.py    (B′) model constants, instructions, schemas, per-network targets
  gemini.py     (B′) request build, reply parse, usage -> price; (C) highlight op,
                expand quotes, Russian 4xx reasons
  send.py       (D′) crop contract, review checks, package writing, publish thread,
                status, queue and the offered rule, delete; (C) ratio choices, base,
                look digest, settings, style files
factory/panel/
  server.py     JSON and audio route kinds; /create routes; AI transport injection;
                drafts cache and AI-month cache (one entry each);
                (D′) review, status, file, image, focus, publish, retry, queue, delete;
                publish-function and targets injection; Ctrl+C waits for a publish;
                (C) settings, highlight
  views.py      create, create_draft, create_profile; «черновик» chip; (D′) create_review;
                (C) its «Фото» section and card controls
  model.py      photo_uses includes drafts (given by the server, §8.8)
  strings.py    tabs and every new Russian string
  static/author.js    (A) + MFAuthor.uploadFile(folder, csrf, file) for «Создать»;
                      (D′) MFAuthor.makeCrop(bitmap, spec, focus);
                      (C) frame and quote in makeCrop, layoutTemplate
  static/create.js    (B′) drop zone, topics, voice, expand, editors, regenerate
  static/send.js      (D′) crops, focus, dialogs, status polling on the review page;
                      (C) base as source, styles, settings
  static/panel.css    create and review styles
tests/test_author_{drafts,profile,budget,gemini,create,send,images}.py,
tests/panel_fixture.py (create, send and images fixtures, FakeGemini), tools/visual_check.py
KEYS.md, README.md
```

The poster stays unchanged, except that C's `vendor_message` reads a JSON array (§18, D33).
The factory core (`stock`, `ruleset`, `planner`, `runner`, `journal`, `checks`,
`attention`, `cli`, `inputs`, `paths`) stays unchanged.

### 5.2 Files and state

| What | Location | Mode | In git |
|---|---|---|---|
| Uploaded photos (A) | `content/stock/<folder>/photos/…`; the default folder is `content/stock/my-photos/` | dirs 0700, files 0600 | no (`content/` is ignored) |
| Author profile (B′) | `content/profile.json` | 0600 | no |
| Drafts | `content/drafts/<id>/draft.json` (B′); `out/<network>.jpg` (D′); `img/<style>.jpg` (C); `content/drafts/.publish.lock` (D′) | dirs 0700, files 0600 | no |
| Queued package (D′) | `content/stock/<folder>/<NNN>-<id>.json`, `media/<id>/<network>.jpg` | same | no |
| Published-now package (D′) | `content/packages/<id>.json`, `content/packages/media/<id>/…` | same | no |
| AI ledger (B′) | `<factory state>/ai-ledger.jsonl`, `ai-ledger.lock` | 0600 | no (outside every checkout) |

`content/` follows `MF_CONTENT_DIR`; the factory state follows `MF_FACTORY_STATE_DIR`. No
voice recording is ever written (D14).

### 5.3 Who writes and who reads

| File | Writers | Readers |
|---|---|---|
| `stock/<f>/photos/**`, `stock/my-photos/folder.json` | panel upload only | panel; the stock loader reads `folder.json` |
| `content/profile.json` | panel «Профиль автора» form | panel (every Gemini text request) |
| `content/drafts/**` | panel only | panel; C and D′ |
| `ai-ledger.jsonl` | panel AI routes | panel («Создать» sub row, refusals) |
| packages, poster `posts.jsonl`, `x-ledger.jsonl` | unchanged by B′. D′: the panel writes packages and media (publish now, queue) and `rules.json` (the offered rule); the poster, called by the panel, writes `posts.jsonl` and `x-ledger.jsonl` | the poster, the factory, the panel |

## 6. Photos (slice A, built)

Slice A is built as designed in the first revision (`d19ed5f`, fixes in `fea48ca` and
`82b8311`). This section records it, because B′ reuses it.

### 6.1 Flow

1. In the folder view of a photo-lane folder, the «Фото» section offers «Загрузить
   папку» (`webkitdirectory`) and «Добавить фото» (`multiple`,
   `accept="image/jpeg,image/png,image/webp"`).
2. `author.js` sorts the files and skips non-images and HEIC with a reason. For each file it
   decodes with `createImageBitmap` (EXIF orientation applied) and draws a **thumb** (480
   px, JPEG 0.82) and a **view** copy (1 600 px, JPEG 0.88). It then posts `kind=orig`,
   `kind=thumb` and `kind=view` to `POST /files/photos?folder=F` as raw bodies with
   `X-CSRF-Token`. A `dup: true` answer skips the other two posts.
3. A `role="status"` line counts the run; skipped files are listed once per folder with
   their reason; a clean run reloads the page.

### 6.2 Server route

`POST /files/photos` (body kind `image`) checks, before any body byte: Host, Origin, CSRF
header, the folder (`NAME_RE`, exists, lane `photo`, real path inside the stock), the kind
and id, the length and type limits, and at least 1 GB free. It streams the body into
`photos/.up-<random>` (`O_EXCL`, 0600), hashes it, and sniffs it with
`poster.rules.sniff`. It then moves the file in place or answers `dup`. The `view` post
appends the index row `{"id", "name", "ext", "bytes", "w", "h", "ts"}` under a lock file.
A photo is listed only when its row exists.

### 6.3 Limits

Original ≤ 25 MB (JPEG, PNG, WebP by sniffing); thumb and view ≤ 2 MB, JPEG; ≤ 2 000
photos per folder; ≤ 300 files per pick; refusal below 1 GB of free disk. The original
stays byte-identical, with its EXIF, on this computer only.

### 6.4 Serving

`GET /photo?folder=F&id=P&v=thumb|view|orig` resolves the file inside `photos/`, sniffs
it, and streams it with `Cache-Control: private, max-age=300`. Anything else is 404.

### 6.5 Snapshot cost

The snapshot key adds one stat per photo index; `model.build` reads each photo folder's
`index.jsonl` only when the key changes.

### 6.6 What the view copy is for

The view copy (1 600 px on the long side, JPEG made by the canvas, so no EXIF) is the
image every Gemini request carries (§8.4, §9.2). At `"resolution": "high"` it costs at
most 1 120 input tokens whatever its size (G7: the level is the maximum allocated per
image). It is about 0.4 MB, far inside the 20 MB request limit.

### 6.7 Files tab as built

Photo-lane cards show the first three thumbs, "+N" and "N пакетов · M фото". The folder
view has the «Фото» section (the photo count stands once, in the sub row «N фото») with 60 photos per step and «показать ещё», and the chips
«в очереди» and «опубликовано» from stock packages. The first revision also planned a
text-post button, a drafts strip and a «Пост» button on each tile for lane B. In this
revision the drafts list lives on «Создать» (§8.2) and the tile button moves to slice M
(§15). Text-only posts are deferred (§21).

## 7. Drafts

### 7.1 Schema

`content/drafts/<id>/draft.json`, written atomically (temp file plus `os.replace`), 0600.
B′ writes these fields:

```json
{
  "schema": 1,
  "id": "2026-11-12-my-photos-3f2a",
  "created": "2026-11-12T19:00:00Z",
  "updated": "2026-11-12T19:04:12Z",
  "folder": "my-photos",
  "photo": "p-3f2a9c01b7d4e6a8",
  "topics_auto": "done",
  "topics": [{"title": "Утро у моря", "angle": "Про дисциплину: почему я бегаю в 6 утра"}],
  "topic": "Утро у моря — про дисциплину и привычки",
  "variants": {
    "x":         {"text": "…", "lang": "en", "source": "gemini"},
    "linkedin":  {"text": "…", "lang": "en", "source": "gemini"},
    "instagram": {"text": "…", "lang": "uk", "source": "edited"},
    "facebook":  {"text": "…", "lang": "uk", "source": "gemini"}
  },
  "error": null,
  "state": "draft"
}
```

- `id`: `YYYY-MM-DD-<folder>-<4 hex>`, with the date in the machine zone. It matches the
  poster's id pattern `[a-z0-9][a-z0-9._-]{0,79}` and later becomes the package id. An
  existing id retries with new hex.
- `folder` and `photo` name an indexed photo. A draft always has a photo in B′; text-only
  posts are deferred (§21).
- `topics_auto` is `pending` (a new draft with a key, before its automatic request),
  `done` (the automatic request was reserved, whatever its outcome) or `manual` (no key
  when the draft was created).
- `topics`: the last suggestion set (3–5 items) or `[]`. `topic`: the chosen or own topic,
  at most 2 000 characters.
- `variants`: empty until «Развернуть». The networks and languages are fixed by the
  decisions: `x` en, `linkedin` en, `instagram` uk, `facebook` uk. `source` is `gemini` or
  `edited`. A text is at most 5 000 characters.
- `error`: `null` or `{"op": "topics|expand|regenerate|voice", "network": …, "text":
  "<Russian>", "ts": …}`. It is set by a failed AI call and cleared by the next success of
  the same op.
- `state`: always `draft` in B′. D′ adds `publishing`, `partial` and `published`, plus
  `publish`, `focus` and `refused` (§17.2). A queued draft is removed, so `queued` is never
  stored. C adds `base`, `look`, `quotes`, `who` and `highlight_error` at the top level
  (§18.2). The first revision put `image`, `template` and `quote` inside each variant, but
  B′ code rewrites a variant's whole dict on every edit, so §18 follows the code (D29).

### 7.2 Lifecycle and locks

- `POST /create/new` (JSON `{folder, photo}`) checks that the photo is indexed in that
  folder, creates the draft folder with `os.mkdir` (0700), and writes `draft.json`. It
  answers `{"id", "url"}`. At most 500 drafts; above that the answer is 409 «черновиков уже
  500 — удаление черновиков появится в срезе D».
- Field writes (topic, text, AI results) take `.lock` in the draft folder with
  `fcntl.flock(LOCK_EX)` for the read-modify-write only (milliseconds): reload, change the
  field, set `updated`, replace the file.
- An AI call takes `.ai.lock` with `LOCK_EX | LOCK_NB` for its whole duration. A second
  call on the same draft gets 409 «уже выполняется». A panel-wide semaphore admits at most
  two AI calls at once; a third gets 409 «ИИ занят двумя запросами — подождите».
- Deleting drafts, and removing a draft after a queue, come with D′. A published draft
  stays read-only until it is deleted (D23, §17).

### 7.3 Draft list cache

The server keeps a one-entry cache of draft summaries (`id`, `folder`, `photo`, `topic`,
`updated`). It is keyed by a depth-0 `scandir` of `content/drafts/` (each draft folder's
inode, `mtime_ns` and size; replacing `draft.json` changes its folder's mtime). It is
rebuilt only when that key changes, by reading each `draft.json`. The cache is owned by
`server.Panel` and passed to the views; the snapshot and its `state_key` do not include
drafts, so a draft save never rebuilds the factory plan.

## 8. «Создать»: photo, topic, texts

### 8.1 Tabs and entry

- `strings.TABS` becomes: («create», «Создать»), («connection», «Подключение»),
  («files», «Медиатека»), («rules», «Правила»), («calendar», «Календарь»), («reach»,
  «Охваты»), («followers», «Подписчики»). «Диалоги · выкл» stays last.
- `GET /` answers 302 to `/create`.
- New pages: `GET /create`, `GET /create/<id>` (id by the pattern of §7.1, else 404) and
  `GET /create/profile`. All three are tab `create`. The first two load `author.js` and
  `create.js`; the profile page loads no script.
- The row under the top bar (`page(sub=…, sub_right=…)`) on these pages holds, on the
  left, «Новый пост», «Черновик · 12 ноя, 19:04» or «Профиль автора». On the right is the
  AI month (§11.5).

### 8.2 The «Создать» page

From top to bottom, in one column at every width (max 960 px wide, centred from 1 000 px):

1. **Drop zone** (a `<label>` around a hidden single-file input, `accept="image/jpeg,
   image/png,image/webp"`): «Бросьте фото сюда», the button «Выбрать фото», and the hint
   «JPEG, PNG или WebP · Gemini предложит темы (до $0.02)» (the price never wraps alone, and
   with no key or past the cap the hint is only «JPEG, PNG или WebP»). The heading is in
   the text colour, the way a main action is. At least 180 px tall at 390
   px. Drag-over outlines the zone and changes the hint to «Отпустите — загружу»; drops
   outside it are cancelled (B3).
2. **Profile line**: «Профиль автора · заполнен» or «Профиль автора не заполнен — темы и
   тексты будут общими», linking to `/create/profile`.
3. **«Недавние фото»**, with the line «Нажмите на фото, чтобы начать пост» on its own row
   under the heading, so no word of it wraps alone (when any photo exists): the 8 newest
   index rows across all photo-lane folders, by `ts`, as 72 px thumbs (96 px from 900 px) in a wrapping row. Each
   is a `<button>` whose name is «Пост из фото <name>».
4. **«Черновики · N»** (when any exist): the 10 newest by `updated`. Each row has a 48 px
   thumb, the topic (one line with an ellipsis, the full text in `title`) or «без темы»,
   the stage word (`без темы`, `своя тема`, `темы`, `тексты готовы`, `длиннее лимита`,
   `ошибка`) and the date with the time («11 нояб., 09:40»), and links to `/create/<id>`.

Flow:

- A drop or pick of **one** image runs slice A's `makeCopies` and three posts through
  `MFAuthor.uploadFile("my-photos", csrf, file)` (§8.8). A `role="status"` line shows
  «Загрузка фото…», then «Создаю черновик…». Then comes `POST /create/new` with
  `{folder: "my-photos", photo: id}` and a navigation to its `url`.
- A drop of several files shows «Перетащите одно фото» and uploads nothing. HEIC, non-image
  files and decode failures show slice A's reasons (`UPLOAD_JS.heic`, `.type`, `.decode`).
  An upload refusal shows the server's text. A `dup` answer is fine: the existing photo is
  used.
- A recent-photo button posts `/create/new` with that photo's folder and id, without
  uploading anything.
- Without JavaScript the page says «Создание постов работает только с включённым
  JavaScript.»

### 8.3 The draft page and «Темы»

`GET /create/<id>`. Layout: one column below 1 000 px, in the order photo, «Тема»,
«Тексты». From 1 000 px there are two columns: photo and «Тема» on the left, «Тексты» on
the right, starting at the top of the page (the heading is on the first screen). From
1 000 to 1 279 px the columns are `minmax(0, 1fr) minmax(0, 1fr)`, from 1 280 px
`minmax(0, 5fr) minmax(0, 7fr)`; the cards stand in two or more columns
(`repeat(auto-fill, minmax(220px, 1fr))`), so the left column holds the topic box and
«Развернуть» on a 700 px screen (measured at 1 000 × 700, 1 280 × 800, 1 440 × 900 and
1 920 × 1 080). In the 1 000–1 279 range the wish field of a text card stands on its own row above
«Перегенерировать», so its whole hint fits (the probe measures the placeholder at 1 000, 1 100,
1 200 and 1 279). The loading line of «Тема» (topics, voice) sits in its heading row, and
the loading line of «Тексты» («Gemini пишет тексты…», for «Развернуть» and «Перегенерировать»)
sits in the «Тексты» heading row, so no blank band separates a heading from its content.
Before «Развернуть», the right column shows «Тексты появятся после «Развернуть»»; while the
texts are written it gives way to the loading line. Below 1 000 px a click on «Развернуть»
scrolls «Тексты» to the top, where its loading line is, and when the texts arrive the page
scrolls to «Тексты» again unless the heading and the first card's editor are already on the
screen (the placeholder was hidden, so the page was short at the click); from 1 000 px nothing
scrolls. A failed request scrolls the error banner into view.

- **Photo**: the view copy from `/photo?…&v=view`, `object-fit: contain`, at most 280 px
  tall below 1 000 px and 12vh (80–180 px) from 1 000 px, so that «Тема» starts on the first
  screen next to the texts and the box and «Развернуть» stay on a 700 px screen, inside a fixed box (no layout shift).
- **«Тема»** section:
  - **Automatic topics**: when `topics_auto` is `pending`, `create.js` posts
    `/create/<id>/topics` with `{"auto": true}` on load. The server flips `topics_auto` to
    `done` under `.lock` before it reserves; a second automatic request answers 200 with
    the draft's current topics and sends nothing. While waiting, the section reads
    «Gemini подбирает темы…» (`role="status"`) and the topic buttons are disabled.
  - **Cards**: 3–5 `<button>` cards, each with the title (bold) and the angle (one line,
    wrapping). A tap copies «<title> — <angle>» into the topic box, saves it, marks
    that card with the visible word «выбрано» and `aria-pressed="true"`, and scrolls the
    box and «Развернуть» into view when they are not (`scrollIntoView({block: "nearest"})`
    on the row of «Развернуть», with a 16 px margin; no scroll when they already are on the
    screen; «сохранено» keeps its reserved place on the label row, so it does not push the box
    and «Развернуть» toward the window edge after the scroll). At 390 × 844 the tap therefore brings both onto the screen; from 1 000 px they
    are on the first screen before any tap.
  - **Heading row**: «Тема», «Ещё темы · до $0.02» and «Голос · до $0.02» stand in one row
    (wrapping on a narrow page); the loading line and the voice line follow in the same row.
  - **«Ещё темы · до $0.02»** asks again (replacing the cards). When `topics` is empty it
    reads «Предложить темы · до $0.02».
  - **Topic box**: label «Тема поста — выберите карточку или напишите свою», a textarea of
    up to 2 000 characters (a counter appears from 1 800). It autosaves 800 ms after
    typing stops through `POST /create/<id>/topic`, showing «сохранено».
  - **«Голос · до $0.02»** beside the topics button, above the cards (§8.5); the bound is
    part of the button's text, and the timer shows once, in the button.
  - **«Развернуть · до $0.05»**: the primary (green) button, in one fixed place directly
    under the topic box, with the hint «выберите тему или впишите свою» beside it; disabled
    while the box is empty. After any variant has `source: edited` it reads «Развернуть
    заново — правки пропадут · до $0.05».

### 8.4 Gemini: topics, expand, regenerate

All three calls (`gemini.py`) are sent with `poster.http.json_request` through
`UrllibTransport`, timeout 120 s:

```
POST https://generativelanguage.googleapis.com/v1beta/interactions
x-goog-api-key: <GEMINI_API_KEY from the env file>
Content-Type: application/json
Api-Revision: 2026-05-20

{"model": "gemini-3.8-flash",
 "store": false,
 "generation_config": {"thinking_level": "low", "max_output_tokens": <per call>},
 "response_format": {"type": "text", "mime_type": "application/json", "schema": <per call>},
 "input": [
   {"type": "text", "text": "<INSTRUCTIONS + PROFILE + TASK, prompts.py>"},
   {"type": "image", "mime_type": "image/jpeg", "resolution": "high",
    "data": "<base64 of photos/view/<id>.jpg>"}]}
```

- **Facts behind it:** the endpoint, headers and blocks (G1); `response_format` (G4); the
  model and its prices (G2, G3); `thinking_level: "low"` because `minimal` is refused on
  3.8 Flash (G5); `max_output_tokens` bounds thinking too (G5); at most 1 120 tokens for
  the image (G7); `store: false` (G9).
- **Unconfirmed:** `v1beta` with `Api-Revision` versus `v1` (G12). If LC1's request is
  refused, the URL becomes `.../v1/interactions` without the header; one constant
  changes. The
  instructions go in the first text block rather than `system_instruction`, so one fewer
  field shape is unconfirmed.
- **Before sending:** the view copy must exist, sniff as JPEG, and carry no APP1 segment
  starting with `Exif\0\0` (a marker walk of at most 64 KB of headers). Otherwise the
  answer is 409 «копия фото содержит EXIF — загрузите фото заново». No file name, path or
  original is ever sent.

| Call | Route | `max_output_tokens` | Schema (inline, no `$ref`) |
|---|---|---|---|
| Topics | `POST /create/<id>/topics` `{auto}` | 2 000 | `{"type": "object", "properties": {"topics": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "object", "properties": {"title": {"type": "string"}, "angle": {"type": "string"}}, "required": ["title", "angle"], "additionalProperties": false}}}, "required": ["topics"], "additionalProperties": false}` |
| Expand | `POST /create/<id>/expand` `{}` | 6 000 | `{"type": "object", "properties": {"x": {"type": "string"}, "linkedin": {"type": "string"}, "instagram": {"type": "string"}, "facebook": {"type": "string"}}, "required": ["x", "linkedin", "instagram", "facebook"], "additionalProperties": false}` |
| Regenerate | `POST /create/<id>/regenerate` `{network, wish}` | 2 500 | `{"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": false}` |

**INSTRUCTIONS** (English, fixed in `prompts.py`):

- Every call: «You help the author write social posts built around this photo. The photo
  shows the author or their world. Never invent facts beyond the topic, the author profile
  and what the photo shows. Never name people in the photo. Do not describe the photo's
  technical qualities.»
- **Topics**: «Suggest 3 to 5 distinct post topics that fit this photo and the author's
  themes and audiences. `title`: at most 80 characters, in Russian. `angle`: one sentence
  in Russian saying what the post would say and for whom.»
- **Expand**: «Write one post per network, in the first person as the author, on the
  topic below.» Per network, with the hard limits taken from the `poster.rules` constants
  so the prompt and the check cannot drift:

  | Network | Language | Target in the prompt | Hard check (poster, never truncating) |
  |---|---|---|---|
  | X | English | short and sharp, at most 240 weighted characters (Latin and Cyrillic 1, emoji 2), at most 1 cashtag, no URL unless the topic contains one (a URL raises the X price from $0.015 to $0.200) | 280 weighted, 1 cashtag |
  | LinkedIn | English | business angle, 600–1 300 characters, short paragraphs, at most 3 hashtags | 3 000 after escaping |
  | Instagram | Ukrainian | a lively caption with a hook in the first 125 characters, at most 1 500 characters, 3–8 hashtags at the end, no links | 2 200 UTF-16 units, 30 hashtags, 20 mentions |
  | Facebook | Ukrainian | conversational, 400–900 characters, 0–3 hashtags | none documented |

- **Regenerate**: «Rewrite only the <network> post. Keep its language and rules. The
  author's wish: <wish or "none">.» The prompt carries that network's current text.

**PROFILE** (§8.7): the non-empty profile fields as labelled lines («Who the author is:
…», «Audience on LinkedIn: …»). With no profile it reads «Author profile: not filled in;
write for a general audience.» **TASK**: the topic (expand and regenerate) and the wish
(regenerate).

**Reply handling** (`gemini.parse`):

1. A 2xx reply with `status` `completed`: the text is the concatenation of the `text`
   blocks of the last `model_output` step in `steps`, or the top-level `output_text` if a
   real reply carries that instead (G13; LC1 settles which). The text is parsed as JSON and
   checked against the call's shape: topics are 3–5 objects with non-empty strings; expand
   has four non-empty strings; regenerate has one.
2. `status` `incomplete` gives «ответ Gemini обрезан — повторите». `failed` or
   `cancelled`, an empty text, invalid JSON or a wrong shape give «Gemini вернул неполный
   ответ — повторите» (G16). All are settled at the reported `usage` (billed, G5).
3. A non-2xx reply gives «Не удалось получить <темы|тексты|новый текст|расшифровку
   голоса> от Gemini»; a 4xx adds « (HTTP <status>): <reduced message>», reduced by
   `vendor_message` and redacted (a 5xx shows no status; the ledger keeps it). `TransportError` or a timeout gives «нет связи с
   Gemini — повторите».
4. On success the server stores the result under `.lock` and clears `error`:
   - **topics** replace `topics`;
   - **expand** replaces all four `variants` with `source: gemini`, NFC-normalised;
   - **regenerate** replaces only `variants.<network>`.
   It answers each variant with `poster.rules.check_text(network, text)` as `{counts,
   errors}`. A text over a limit is kept whole and never cut: the card shows the poster's
   error (§8.6). On failure the server stores `error` and answers it with 409 (refusals),
   502 (vendor error) or 504 (timeout or transport).
5. Nothing retries by itself, so nothing spends without an action (D13's automatic topic
   request is the single exception, once per draft).

### 8.5 Voice: recording and transcription

- «Голос» calls `getUserMedia({audio: true})` and records with `MediaRecorder` as
  `audio/webm;codecs=opus`. Otherwise it uses `audio/ogg;codecs=opus` or `audio/webm`,
  checked with `isTypeSupported` (B4), with `audioBitsPerSecond: 32000`. If neither type
  is supported, the button reads «этот браузер не записывает звук — откройте панель в
  Chrome или Edge».
- While recording: «Стоп · 0:07» with `aria-pressed="true"` and a `role="status"` timer.
  Recording stops by itself at 2:00.
- On stop, `POST /create/<id>/voice` sends the blob (body kind `audio`, at most 1 MB,
  media type `audio/webm` or `audio/ogg`; parameters are ignored). The server reads the
  body into memory, checks the container signature (EBML `1A 45 DF A3` or `OggS`), and
  reserves the bound of §11.2. It then calls:

```
POST …/v1beta/interactions          (headers as §8.4)
{"model": "gemini-3.5-flash-lite",
 "store": false,
 "generation_config": {"thinking_level": "minimal", "max_output_tokens": 2000},
 "input": [
   {"type": "text", "text": "Transcribe this voice note verbatim in the language spoken
     (Russian, Ukrainian or English). Output only the transcript, no comments."},
   {"type": "audio", "mime_type": "audio/webm", "data": "<base64>"}]}
```

- On success the transcript (the reply's text, as in §8.4 step 1, without JSON) is
  appended to `topic` with a space, under `.lock`. The answer is `{topic, transcript,
  month}`, and the page puts `topic` into the box.
- On failure the page keeps the blob and shows «Повторить расшифровку». Nothing about the
  audio is written anywhere; the body buffer is dropped when the request ends.
- States, each with its own words: «микрофон запрещён в браузере» (`NotAllowedError`),
  «микрофон не найден» (`NotFoundError`), «запись голоса работает только по адресу
  localhost» (`navigator.mediaDevices` undefined, B1), «расшифровка…».
- There is no playback: the transcript in the box is what the operator checks and edits.

### 8.6 Editing the texts

After «Развернуть», «Тексты» shows four cards in this order: X, LinkedIn, Instagram,
Facebook. Each card has:

- **Head**: the network monogram and name, then the language word «англ.» or «укр.».
- **Textarea**: the full text, `white-space: pre-wrap`, growing with its content; nothing
  is clipped.
- **Count line**: one short Russian line in mono, made from the poster's own counters
  and limits (`gemini.present`): «212 / 280 знаков» (X), «230 / 3000 знаков» (LinkedIn),
  «114 / 2200 знаков · хештеги 3 / 30» (Instagram), «136 знаков» (Facebook, which has no
  documented limit).
- **Over a limit**: instead of that count, one line in `--red` with `role="alert"`:
  «длиннее лимита: 312 / 280 — сократите». The count is shown once, and no English text
  from the poster's `errors` reaches the card.
- **Regenerate row**: one input «пожелание: короче, без хештегов…» (at most 200
  characters) and «Перегенерировать · до $0.05».

Typing autosaves 800 ms after the last key through `POST /create/<id>/text` (JSON
`{network, text}`). The server refuses more than 5 000 characters with «текст длиннее 5 000
знаков» (refused, never cut). It stores the text NFC-normalised, sets `source: edited`, and
answers `check_text` as `{counts, errors}` and `gemini.present` as `{line, problems}`
(the panel shows the second). The count line on screen always comes from the
server, so JavaScript keeps no copy of the X weighting. A busy card disables its own
buttons and keeps their width.

### 8.7 «Профиль автора»

`GET /create/profile` is a form posting to `POST /create/profile` (body kind `form`, the
`csrf` field, 16 KB). It works without JS.

| Field | Label | Limit |
|---|---|---|
| `who` | Кто вы | 600 characters |
| `topics` | О чём пишете | 600 |
| `audience.x`, `.linkedin`, `.instagram`, `.facebook` | Аудитория в X / LinkedIn / Instagram / Facebook | 300 each |
| `tone` | Тон | 300 |
| `avoid` | Каких слов и тем избегать | 300 |

- Saving writes `content/profile.json` atomically (0600) as `{"schema": 1, "who": …,
  "topics": …, "audience": {…}, "tone": …, "avoid": …, "updated": …}` and redirects 303 to
  `/create/profile?saved=1`, which shows «Профиль сохранён».
- A field over its limit re-renders the form with the operator's text kept and «<поле>:
  не больше N знаков» (409); nothing is cut or saved.
- An explainer under the heading: «Профиль уходит в каждый запрос к Gemini вместе с фото.
  Хранится только на этом компьютере (content/profile.json).»
- The last save wins; there is no revision field (D15).

### 8.8 «Медиатека» and the default folder

- **Label**: the `files` tab and its page heading read «Медиатека»; the URL stays `/files`
  (D11). Everything slice A shows stays as it is.
- **Default folder**: `photos.ensure_default(stock_root)` runs in `pre_check` when the
  kind is `orig` and the folder is `my-photos`, and only when `stock/my-photos` does not
  exist. It creates `stock/` (0700) if needed, makes `stock/.my-photos.<random>/` (0700),
  and writes `folder.json` `{"schema": 1, "title": "Мои фото", "lane": "photo"}` (0600,
  `O_EXCL`). It then runs `os.rename` to `stock/my-photos`. If the target appeared
  meanwhile, the rename fails, the prepared folder is removed, and the existing folder is
  used. A `my-photos` of another lane gets the usual 409 «папка «my-photos» не из полосы
  фото-постов». The folder then behaves like any photo folder: a card in «Фото-посты», «0
  пакетов · N фото», «никто не берёт · расход 0» until a rule reads it (D′ offers one when a post is queued, §17).
- **Chip «черновик»**: `photo_uses` also marks a photo «черновик» when a draft names it and
  no stock package does («в очереди» and «опубликовано» win). The draft summaries come
  from the server's draft cache (§7.3), passed in by the view; `model.build` does not read
  drafts.
- **`author.js`**: the per-file upload (decode, copies, three posts) becomes
  `MFAuthor.uploadFile(folder, csrf, file)`, which returns a promise of `{id, dup}`. The
  folder view's loop calls it unchanged in behaviour; «Создать» calls it with
  `my-photos`.

## 9. Photo: templates and highlight (slice C)

Unchanged from the first revision except where noted. Slice D′ builds, ahead of C, the
**default crop** column of the table below (as plain crops of the original, with exact
integer sizes), the focus tap, `MFAuthor.makeCrop`, the `POST /create/<id>/image` route
and `out/<network>.jpg`. It builds them automatically on the review page, not behind a
«Сохранить картинки» button (§17.1, D18–D20). C keeps the rest of this section and reuses
D′'s crop function, route and files. §18 pins C against the merged code. Where it differs
from this section, §18 governs: the controls are on the review page (D27), 1.91:1 is
955 × 500 (D28), a change deletes and re-makes crops (D30), and the bound is computed
(D32).

### 9.1 Code templates (per network, in the browser)

Every published image is drawn by `author.js` on a canvas from the chosen **base** (the
original, or one Gemini result, §9.3) and saved as JPEG. In D′ the base is always the
original.

| Network | Default crop | Choices | Output |
|---|---|---|---|
| Instagram | 4:5 | 4:5, 1:1, 1.91:1 | 1080 × 1350 / 1080 × 1080 / 1080 × 566 |
| Facebook | original ratio | original, 4:5, 1:1, 16:9 | long side 2 048 |
| LinkedIn | original ratio | original, 1.91:1, 1:1 | long side 2 048 |
| X | 16:9 | 16:9, original, 1:1 | long side 1 600 |

- **Crop:** the largest window of the chosen ratio inside the base, centred on the focus
  point; one click on the preview sets the focus. The output never upscales.
- **Frame:** an inset border of `max(16 px, 2.5 % of the short side)` in white, black or
  `#e8c47c`.
- **Quote:** a short line on a band of `rgba(0, 0, 0, 0.6)` at the bottom or top third,
  white `600` system sans, sized down from 6 % of the width until it fits in at most 4
  lines of 86 % width. The line comes from the variant's `quote`. B′ does not generate
  quotes: C adds a `quote` string per network to the expand schema of §8.4, and the
  operator can type one for older drafts.
- **Save:** each network's JPEG goes to `POST /create/<id>/image?network=N` (built in D′,
  §17.3: body kind `image`, at most 8 MB, JPEG). Quality starts at 0.9 and steps down to
  0.8 and 0.7 above the network's byte limit. The server sniffs the image, refuses an APP1
  `Exif` segment (the marker walk B′ already has, §8.4), runs `check_image`, and stores
  `out/<network>.jpg`. In C, a change of ratio, frame, quote or base redraws and re-posts
  the affected networks; D′ redraws only on a focus tap.

### 9.2 Gemini highlight styles

Three styles, one Gemini call per click (`POST /create/<id>/highlight` with JSON `{style,
who}`), each button showing its bound («до $0.09»):

| Style | Button | Instruction (prompts.py, English) |
|---|---|---|
| `blur` | Размыть фон | Blur the background as with a shallow depth of field. Keep the main person sharp and every pixel of their face, body and clothes unchanged |
| `glow` | Свечение | Add a soft warm rim light and glow around the main person. Do not change the face, features, body, clothes or the background content |
| `outline` | Контур | Add a thin soft white outline around the main person, sticker-like. Change nothing else |

All three append "The main person is the most prominent person in the photo", the
operator's optional one-line description, and "Do not add text, logos or other people."

```
POST https://generativelanguage.googleapis.com/v1beta/interactions   (headers as §8.4)

{"model": "gemini-nano-banana-2.1",
 "store": false,
 "input": [{"type": "text", "text": "<style instruction>"},
           {"type": "image", "mime_type": "image/jpeg", "data": "<view copy>"}],
 "response_format": {"type": "image", "mime_type": "image/jpeg",
                     "aspect_ratio": "<nearest of 1:1, 4:5, 5:4, 3:4, 4:3, 2:3, 3:2, 9:16, 16:9>",
                     "image_size": "2K"}}
```

Timeout 180 s. The first `image` block of the `model_output` step is decoded, sniffed (it
must be JPEG) and stored as `img/<style>.jpg`. An answer without an image shows «Gemini не
вернул картинку» with its text part and is settled at the reported usage. The result
carries SynthID (G11).

### 9.3 Side by side, and the pick

The draft page's photo becomes two equal tiles at every width, «Оригинал» and the selected
style result, each labelled. Under them is a row of chips «Оригинал · Размыть фон ·
Свечение · Контур»; a chip without a result reads «создать · до $0.09». «Взять за основу»
sets `base`, and the per-network previews (§9.1) redraw from it. The original is always
kept.

## 10. Send (slice D′)

Unchanged from the first revision except for the points below. §17 pins the build, and
where §17 and this section differ, §17 governs.

- The review page is `GET /create/<id>/review`, reached from the draft page by
  «Проверить и отправить →».
- The package `theme` is the draft's `topic`.
- The networks are the four of §7.1 that the poster's main profile has targets for.
- The images are D′'s plain crops (§17.1).

### 10.1 Review

For each target, the review shows:

- the monogram, the target id, the language, the full text and the image of
  `out/<network>.jpg`;
- the poster's own checks, exactly as `poster publish` runs them: `check_text`,
  `check_image(sniff(...))`, missing variables (names only), LinkedIn token problems, and
  for X `xapi.estimate` and the X month against `X_MONTHLY_CAP_USD`.

A missing `out/<network>.jpg` is shown once, in the crop line «Готовлю картинки: …»
(§17.4), and keeps both buttons disabled. Any problem disables both buttons and is listed
with `role="alert"`.

- **Опубликовать сейчас**: a native modal `<dialog>` asks «Опубликовать в N сети сейчас?
  Это нельзя отменить.», with N in its Russian plural (§10.3, §17.4).
- **В очередь**: a folder select. It defaults to the draft's folder, which is `my-photos`
  for posts started from «Создать». For the chosen folder it shows the rule that reads it
  and its next slot in words. When no rule reads the folder, it offers to create one
  («пн, ср, пт в 10:00») through the rules checks (§10.4).

Pressing either button is the operator's approval after seeing every variant (decision of
2026-11-11; `factory.md` §6.1).

### 10.2 The package written

```json
{"schema": 1, "id": "2026-11-12-my-photos-3f2a", "theme": "<topic>",
 "variants": {"facebook": {"text": "…", "image": "media/2026-11-12-my-photos-3f2a/facebook.jpg"},
              "x": {"text": "…", "image": "media/2026-11-12-my-photos-3f2a/x.jpg"}},
 "meta": {"approved_by_operator": "2026-11-12", "source": "panel",
          "photo": "p-3f2a9c01b7d4e6a8"}}
```

The images are copied from `out/` into `media/<id>/` next to the package file. After
writing, the panel loads the file with `poster.package.load` and checks every variant; a
failure removes what was written.

### 10.3 Publish now

1. Under the publish lock and the draft lock: write `content/packages/<id>.json`
   exclusively (a dot-file put in place with `os.link`) and its media. The draft becomes
   `publishing` with its first attempt and the targets.
2. One background thread at a time calls `poster.cli.main(["--env-file", ENV,
   "--state-dir", STATE, "publish", PATH, "--targets", "t1,t2", "--library", LIB])` in
   this process, with output captured and redacted.
3. The review page polls `GET /create/<id>/status` every 3 s. The answer comes from the
   poster record after the attempt's offset: `published` with its link, `failed` with the
   reduced error, «неизвестно — проверьте аккаунт», or «ждём…».
4. When the thread ends:
   - every target `published`: the draft becomes `published` and stays, read-only, until
     it is deleted (D23);
   - any `failed` or `unknown`: the draft becomes `partial`, with «Повторить упавшие» for
     the failed ones;
   - exit 2: the package is removed, and the draft goes back to `draft` with the poster's
     problems.
5. Ctrl+C waits for a running publish. An interrupted one shows «прервано — проверьте
   аккаунт» on its review page and in «Черновики» (an attention-bell item is deferred,
   §21).

### 10.4 Add to the queue

Under the panel's `write_lock`, the server takes the next `NNN` and writes
`stock/<folder>/<NNN>-<id>.json` exclusively, together with `media/<id>/`. It then loads the
package with `poster.package.load`, and no problems are allowed. The draft is removed, and
the page redirects to `/files?folder=<folder>&queued=<id>#pkg-<id>`: the package row opens with
one line, «В очереди «<папка>» · выйдет пт, 13 нояб., 16:00» (the first planned slot of the
plan; «выйдет, когда правило начнёт читать папку» when no rule reads the folder), and its title
is the post's theme. The offered rule is created in the
same request when its checkbox is on (D25, §17.5 item 15).

### 10.5 The rest of the panel

New packages appear wherever the factory shows packages. «Удалить черновик» (a form POST
with a modal confirmation) comes with D′. It is allowed in every state except a running
publish (§17.5 item 16).

## 11. AI budget guard

### 11.1 Ledger

`<factory state>/ai-ledger.jsonl`, append-only under `ai-ledger.lock`, built on
`poster.state.locked`, `append_jsonl` and `read_jsonl`:

```json
{"ts": "…", "month": "2026-11", "rid": "uuid", "vendor": "google", "model": "gemini-3.8-flash",
 "op": "expand", "draft": "2026-11-12-my-photos-3f2a", "price": "0.0406", "status": "reserved"}
{"ts": "…", "month": "2026-11", "rid": "uuid", "status": "ok", "actual": "0.0109",
 "usage": {"in": 3612, "out": 1480, "thought": 640}, "http": 200, "state": "completed"}
```

- `reserve(op, bound)`: under the lock, sum the month and refuse when `total + bound >
  AI_MONTHLY_CAP_USD`; otherwise append the `reserved` row. Only then is the request
  built and sent.
- `settle`:
  - `ok`: `actual` from `usage`, also for `incomplete` and parse failures, which are billed;
  - `failed` (counts 0): only a 4xx reply (400, 401, 403, 404, 413, 429), which generated
    nothing;
  - `unknown` (counts the reservation): 5xx, timeouts and transport errors.
- **Month total:** per `rid`, the `actual` when `ok`, the reservation when `reserved` or
  `unknown`, 0 when `failed`, over rows whose reservation month is the current UTC month
  (the X ledger's rule). A reservation left by a killed panel counts, which errs on the
  safe side.
- **Refusal text:** «Бюджет ИИ на ноябрь исчерпан: «Развернуть» стоит до $0.05. Новые запросы —
  с 1 декабря, раньше — после того, как вы поднимете месячный лимит в файле .env.» The
  refused action stands by its button name («Темы», «Голос», «Развернуть», «Перегенерировать»); «до $0.05» is
  bound by no-break spaces, so the price never splits across lines. The page shows the
  sentence of its main action once («Темы» on `/create`, «Развернуть» on a draft). The
  amounts stand once, in the sub row («ИИ · ноябрь $9.99 из $10.00 · лимит»). Nothing is sent. Routes answer 409 `{"error": <text>}`.

### 11.2 Bounds (reserved before each call, shown on each button)

Tokens are bounded by UTF-8 bytes, because a token covers at least one byte. The photo is
at most 1 120 tokens at `resolution: "high"` (G7). Output is bounded by `max_output_tokens`,
thinking included (G5). Audio is bounded by its length at Opus's lowest bitrate:
`ceil(bytes × 8 / 6 000)` seconds × 32 tokens (B5, G8).

- **Reserved bound:** computed from the actual bytes of this call.
- **Button bound:** the static worst case (every field at its limit, 4 bytes per
  character), rounded up to the cent, for the price period of today's UTC date. The
  reserved bound is never above it.

| Call | Input bound (worst case) | Output bound | Button: through 2026-12-31 / from 2027-01-01 | Typical (U until LC1) |
|---|---|---|---|---|
| Topics (3.8 Flash) | template + profile 3 000 ch + photo ≈ 16 100 | 2 000 | до $0.02 / до $0.04 | ≈ $0.005 |
| Expand (3.8 Flash) | + topic 2 000 ch ≈ 24 100 | 6 000 | до $0.05 / до $0.09 | ≈ $0.011 |
| Regenerate (3.8 Flash) | + text 5 000 ch + wish 200 ch ≈ 44 900 | 2 500 | до $0.05 / до $0.09 | ≈ $0.005 |
| Voice (3.5 Flash-Lite) | 1 MB body → ≤ 1 399 s × 32 + prompt ≈ 45 800 | 2 000 | до $0.02 / до $0.02 | ≈ $0.001 |
| Highlight (Nano Banana 2.1, C) | prompt ≤ 1 KB + 512 + photo 2 240 (G17 unconfirmed) | one 2K image 1 680 + 1 000, all at $30.00/MTok | до $0.09 / до $0.09 | ≈ $0.06 (U until LC3) |

Settling prices `total_input_tokens` at the input rate and `total_output_tokens +
total_thought_tokens` at the output rate. If LC1 shows that output already includes
thought (G14), the sum is an upper bound and the code drops the second term. A month of 30
photo posts (topics, one expand, two regenerations and one voice note each) comes to about
$0.8 (about $1.6 at 2027 prices), inside $10.

### 11.3 Price table (`prices.py`, read 2026-11-12)

| Model | Input / MTok | Output / MTok (thinking included) | Valid | Source |
|---|---|---|---|---|
| `gemini-3.8-flash` | $0.75 | $3.75 | through 2026-12-31 (UTC date of the call) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| `gemini-3.8-flash` | $1.50 | $7.50 | from 2027-01-01 | same |
| `gemini-3.5-flash-lite` | $0.30 (audio too) | $2.50 | — | same |
| `gemini-nano-banana-2.1` (C) | $1.50 | text $7.50, image $30.00 (2K = 1 680 tokens) | read 2026-11-11 | same |

Prices live in code next to their URL and read date, and a price change is a reviewed code
change. The ledger stores dollars, so old rows keep their prices.

### 11.4 Cap setting

`AI_MONTHLY_CAP_USD` in the env file, default `10.00`. It must be a finite decimal ≥ 0,
validated like `X_MONTHLY_CAP_USD`; a bad value refuses every AI call with «AI_MONTHLY_CAP_USD
в .env: нужно число, например 10.00». Only the operator changes it.

### 11.5 Where the month is shown, and the top-bar measurement

The right side of the row under the top bar on every «Создать» page reads «ИИ · ноябрь
$0.84 из $10.00» in mono, with `title="Gemini за <месяц>, по UTC"`. It turns `--red` and
adds «· лимит» when less than the largest button bound remains. The month total is read
through a one-entry cache keyed by the ledger's `(ino, mtime_ns, size)` and the UTC month.
The cache is owned by `server.Panel`, so a page costs one `stat` and AI calls never
rebuild the snapshot.

**Measurement** (2026-11-12): `main` at `82b8311` exported twice to scratch. The second
copy has `strings.TABS` with «Создать» first and «Медиатека», plus a sub-row item «ИИ
ноябрь $10.00 из $10.00» on `/files`. Data fixture of `tests/panel_fixture.py`, `/files`
and `/connection`. Chrome for Testing 156.0.8078.4 headless shell at device scale 1, `.topbar`
measured by `getBoundingClientRect`, `scrollWidth` against `clientWidth` for every tab.

| Viewport | Top bar today | With «Создать» and «Медиатека» |
|---|---|---|
| 390 | 231.8 px (tabs in 3 rows) | 231.8 px (3 rows) |
| 600 | 170.4 px | 170.4 px |
| 900, 1 000, 1 280 | 109 px | 109 px |
| 1 414, 1 440 | 67 px (one line) | 109 px (status under the tabs) |
| 1 600, 1 920 | 67 px | 67 px |

- The one-line threshold moves from 1 399 px to 1 514 px of viewport.
- The sticky bar (from 900 px) stays at or under 109 px, inside the 136 px
  `scroll-padding-top`.
- No tab text was cut, and no page scrolled sideways at any width.
- The sub row stayed one 32 px row with the AI item at every width.
- The visual check's 1 440 screenshots of every tab will show the two-row top bar, as at 1
  280 today; that is the expected result.

## 12. Keys and models

| Name (env file) | Purpose | Used by |
|---|---|---|
| `GEMINI_API_KEY` | Gemini Interactions API, header `x-goog-api-key` | `factory/authoring/gemini.py` |
| `AI_MONTHLY_CAP_USD` | optional, AI month cap (default `10.00`) | `budget.py` |

- `KEYS.md` moves `GEMINI_API_KEY` from «Planned» into a new table «AI (panel)» with
  `AI_MONTHLY_CAP_USD`. Values live only in the env file.
- The name contains `KEY`, so `Redactor.add_env` already masks its value in every page,
  JSON reply and log line.
- The key is read from the env file at call time (`config.load_env`), never from the
  process environment, and travels only in the header. It never appears in a URL, so no
  URL in an error can carry it.
- Models are constants in `prompts.py`: `gemini-3.8-flash` (topics, texts),
  `gemini-3.5-flash-lite` (voice), and `gemini-nano-banana-2.1` (C).
- The project has no Anthropic key and no Anthropic code path (decision of 2026-11-12).
- The key's Google Cloud project must have an active billing account; otherwise photos
  and voice fall under the unpaid terms (G10). The panel cannot detect the tier; the
  operator answered on 2026-11-12 that billing is on or will be turned on.

## 13. Security

| Threat | Server-side check | Test (hostile input) |
|---|---|---|
| A foreign site starts an upload or a paid call from the operator's browser | Every new POST: `Host` (421). For JSON and audio bodies `Origin` must be present and equal `http://<Host>`, and `X-CSRF-Token` must match (403) before any body byte. A custom header forces a CORS preflight, which the server refuses (no `do_OPTIONS`, 501). The profile form keeps the `csrf` field | POST each new route without the header, with a wrong token, with `Origin: http://evil.example`, without `Origin`: 403; the ledger, drafts and profile are unchanged and the fake transport saw nothing |
| DNS rebinding | `Host` check on every route (421) | Wrong `Host` on each new GET and POST |
| Oversized or endless bodies | Per-route `Content-Length` limit before reading (413, connection closed): JSON 64 KB, audio 1 MB, profile form 16 KB | 70 KB JSON, 1.1 MB audio, missing `Content-Length` (411) |
| Path traversal | Draft ids by the §7.1 pattern; folder and photo ids by A's patterns and the index; the draft folder's real path must lie inside `content/drafts/`; `drafts/` and each draft folder must not be symlinks | `/create/../../.env`, `id=../x`, a draft folder symlinked to `/tmp`: 404 or 409, nothing written outside |
| Camera metadata reaching Google | Only the view copy is sent; it must sniff as JPEG and carry no `Exif` APP1 segment (§8.4) | a view copy with an injected Exif segment: 409, no request |
| Voice kept on disk | The audio body is read into memory and never written (D14) | after a voice call, no file under the content or state folders has an audio signature or a `.webm`/`.ogg` name |
| Key values in pages, JSON, logs, ledger, drafts | The key is only in a header; JSON and HTML replies pass `Redactor.redact`; vendor errors pass `vendor_message`; the panel logs one redacted line per failure and never a request or reply body; ledger rows and drafts hold no request bodies | a canary `GEMINI_API_KEY`; a fake vendor error that echoes it; no page, JSON reply, log line, ledger row or draft contains it |
| Data kept by the vendor | Every request carries `"store": false` (G9); no file name or original is sent | every captured request body has `"store": false` and no `name` field |
| Spending without the operator | Every paid call is one action (one automatic topic request per new draft, D13); reservation before sending; refusal above the cap; no automatic retries; at most two calls at once and one per draft | a month at $9.99 refuses each op with no request sent; a second click on one draft gets 409 and one request is seen; reloading a draft page twice sends one topic request |
| Prompt injection through text in the photo | The model's output is only shown to the operator for editing and is never published or executed in B′; D shows every text before approval | — |
| Microphone over plain HTTP from another host | The browser refuses it (B1); the panel binds 127.0.0.1 only | — |
| Photos, profile and drafts in git | `content/` is ignored | `git check-ignore` holds for `content/profile.json`, `content/drafts/d/draft.json`, `content/stock/my-photos/photos/p.jpg` |

The panel's CSP needs no change: `fetch` to the same origin falls under `default-src
'self'`, the view copy is a same-origin `<img>`, and recording needs no `blob:` URL.
`create.js` sets sizes through the CSSOM, never through `style` attributes.

## 14. Panel changes

### 14.1 POST route table

The checks run in the order of `do_POST` today (§2). The `Route` gains the kinds `json`
and `audio`; non-form kinds dispatch to their handler after the CSRF header check.

| Path | Kind | Limit | Content types | Slice |
|---|---|---|---|---|
| `/rules/<action>`, `/files/new-folder` (existing) | form | 16 KB | `application/x-www-form-urlencoded` | — |
| `/files/photos` (existing) | image | `orig` 25 MB, `thumb`/`view` 2 MB | `image/jpeg`, `image/png`, `image/webp` | A (B′ adds the default folder) |
| `/create/profile` | form | 16 KB | form | B′ |
| `/create/new`, `/create/<id>/topics`, `/topic`, `/expand`, `/regenerate`, `/text` | json | 64 KB | `application/json` | B′ |
| `/create/<id>/voice` | audio | 1 MB | `audio/webm`, `audio/ogg` | B′ |
| `/create/<id>/image` | image | 8 MB | `image/jpeg` | D′ (C reuses it) |
| `/create/<id>/focus` | json | 64 KB | `application/json` | D′ |
| `/create/<id>/highlight`, `/settings` | json | 64 KB | `application/json` | C |
| `/create/<id>/publish`, `/retry`, `/queue`, `/delete` | form | 16 KB | form | D′ |

JSON bodies must decode as a UTF-8 JSON object (else 400 «неверный запрос»). JSON replies
use the existing `_json` helper; errors are `{"error": "<Russian>"}` with 400, 403, 404,
409, 413, 415, 502 or 504. Every AI reply also carries `month` (the new month total as
text), so the sub row updates without a reload.

### 14.2 GET routes

- B′: `/` (302 to `/create`), `/create`, `/create/<id>`, `/create/profile`.
- D′: `/create/<id>/review`, `/create/<id>/status`, and `/create/<id>/file?name=<network>`
  (the crops). C extends `name` to its style images.

### 14.3 Rendering rules for the new pages

The rules of `factory.md` §14 apply. In addition:

- Each state has its own visible words: «Бросьте фото сюда», «Загрузка фото…», «Gemini
  подбирает темы…», «выбрано», «Gemini пишет тексты…», «расшифровка…», «Стоп · 0:07»,
  «длиннее лимита: 312 / 280 — сократите», «Бюджет ИИ на ноябрь исчерпан: …», «нет GEMINI_API_KEY в .env —
  темы, тексты и голос недоступны», «Не удалось получить темы от Gemini»,
  «сохранено». No two neighbouring states share their words; colour is never the only
  difference.
- A button that spends shows its bound («до $0.05») as text; the sub row shows the month.
- Busy buttons are disabled, look dimmed (slice A's `.btn:disabled` style) and keep their
  width; results replace their own section, never the page.
- No horizontal scroll from 390 to 1 920; long texts wrap (`overflow-wrap: anywhere`); the
  photo keeps its aspect ratio inside a fixed box; every target is at least 24 × 24 px.

## 15. Slices (build lanes)

Order: **A (built) → B′ (built) → D′ → C**. M can follow at any time.

- B′ added the ledger with the first paid call.
- **D′ comes before C** (operator's decisions of 2026-11-13), so the first real post leaves
  the panel sooner. The first revision put C first because Instagram refuses a 3:4 phone
  photo (aspect 0.75, `rules.py:26`). D′ removes that dependency by carrying the plain
  default crop of each network itself.
- C then adds the optional image work on top of D′'s crops.

The slices:

- **A: photos in Files.** Built (§6).
- **B′: «Создать» → topics → Gemini texts.** Built; pinned in §16.
- **D′: review, plain crops and send.** Pinned in §17. It builds §10 and, from §9.1, only
  the default crop of each network:
  - the crops: Instagram 4:5, Facebook and LinkedIn at the original ratio, X 16:9;
    automatic, centred, with an optional focus tap;
  - `/create/<id>/image`, `out/<network>.jpg`, the review page and `send.py`;
  - the publish thread and status, the queue with the offered rule, «Удалить черновик» and
    the Ctrl+C wait.

  C's first-revision acceptance item 1 (sizes from a 3 024 × 4 032 fixture) moves here as
  §17.5 item 1.
  - Live check: LC4, after the merge (§17.9).
- **C: images.** C keeps everything of §9 that D′ does not build:
  - the ratio choices beyond the default (Instagram 1:1 and 1.91:1; Facebook 4:5, 1:1 and
    16:9; LinkedIn 1.91:1 and 1:1; X original and 1:1);
  - the frame and the quote templates (§9.1) and the `quote` field in the expand schema;
  - the Nano Banana highlight styles (§9.2), the `img/<style>.jpg` files and
    `/create/<id>/highlight` and `/settings`;
  - the side-by-side strip and «Взять за основу» (§9.3), which makes a style result the
    base that D′'s crop function draws from.

  C reuses D′'s `MFAuthor.makeCrop`, `POST /create/<id>/image`, `out/<network>.jpg` and
  the review page. It extends them as §18 pins: an optional frame and quote in the crop
  spec, the ratio and `look` checks on the crop route, and the strip and card controls on
  the review page (D27). **Pinned acceptance: §18.5**, which governs; the four items
  below are its items 3, 5–6, 8 and 1. The first revision's acceptance, without its
  item 1:
  1. Frame and quote fit inside the image, with at most 4 quote lines (measured with a
     `Range`).
  2. A fake Gemini image is stored as `img/blur.jpg` and shown beside the original, with one
     reservation and one `ok` row. A text-only answer shows «Gemini не вернул картинку».
  3. Choosing a style as the base redraws every preview and re-posts every crop.
  4. Each ratio choice gives the exact integer size of its ratio, and passes
     `check_image`.
  - Live check: LC3, after the merge (§18.9). The operator provides one photo of
    themselves and a verdict on the face.
- **M: «Медиатека» layout** (cut from B′, §16.5). On `/files`:
  - a section «Все фото» on top: the newest photos across photo-lane folders, 60 per step,
    each with its chip and a «Пост» button posting `/create/new`;
  - the lanes moved below into a collapsed `<details>` «Очереди по расписанию», whose
    one-line explainer says that a queue is a folder a rule publishes from;
  - the new-folder cards inside it.
  Acceptance: every slice A and B′ test passes. «Все фото» lists `my-photos` and `city`
  photos newest first. «Пост» opens a draft. The closed section still contains every card
  (tests read the HTML). The visual check's `files` states run with the section open by a
  query parameter, so the ellipsis checks keep measuring the cards.

## 16. Slice B′: pinned acceptance (the lane is judged against this section)

**Builds:**

- Python: `drafts.py`, `profile.py`, `budget.py`, `prices.py`, `prompts.py`, `gemini.py`
  (topics, expand, regenerate, transcribe) and `photos.ensure_default`.
- Panel: the route kinds and routes of §14.1–14.2 marked B′; the pages of §8.1–8.7; the
  «Медиатека» label, the draft chip and the `author.js` export of §8.8; `create.js` and
  its CSS.
- Tests, fixture fakes and visual-check states (§16.4).
- `KEYS.md` (§12) and a README section «Создание постов в панели».

### 16.1 Acceptance list

Each item is observable by a test, a probe or a screenshot named in §16.4. Items 1–3
carry spec item 1, 4–7 item 2, 8–12 item 3, 13 item 4, 14 item 5, 15–16 item 6, 17 item 7,
19 item 8 and 20 item 9.

1. **Entry and tabs.** `GET /` answers 302 with `Location: /create`. Every page's tab bar
   reads, in order, «Создать», «Подключение», «Медиатека», «Правила», «Календарь»,
   «Охваты», «Подписчики», «Диалоги · выкл». On `/create`, «Создать» carries
   `aria-current="page"`. No tab reads «Файлы».
2. **Медиатека keeps slice A.** `/files` and `/files?folder=<f>` render everything slice A
   renders: lanes, cards with thumbs and photo counts, the «Фото» section with both
   upload buttons, the newest-first grid, «показать ещё», and the chips. Their heading is
   «Медиатека». Every existing test passes, except the two that pin what the
   specification changes: `test_root_redirects_to_connection` (now `/create`) and the
   tab-label list in `ShellTest.test_tab_bar_and_top_right` (now «Медиатека» and
   «Создать»). Those two are updated, not deleted. The visual check's existing states
   pass.
3. **Default folder.** With no `stock/my-photos`, the first `orig` upload to `folder=my-photos`
   creates `stock/my-photos/` (0700) with `folder.json` = `{"schema": 1, "title": "Мои
   фото", "lane": "photo"}` (0600) and stores the photo.
   - Two concurrent first uploads both get 200, and exactly one valid `folder.json` exists.
   - A pre-existing `my-photos` of lane `text` gives 409 «папка «my-photos» не из полосы
     фото-постов» and nothing is written.
   - No «Создать» page has a folder field or folder choice.
   - `python3 -m factory check` on the fixture reports no problem line about `my-photos`;
     its problem lines before and after the folder appears are the same.
4. **«Создать» page.** `/create` shows:
   - the drop zone «Бросьте фото сюда» with «Выбрать фото» (single file, `accept` JPEG,
     PNG, WebP);
   - the profile line;
   - «Недавние фото» (8 newest across photo-lane folders) and «Черновики · N» (10 newest),
     each only when non-empty;
   - the AI month in the sub row.

   In probe mode, `create.js` takes a generated JPEG through the drop path: three posts to
   `/files/photos?folder=my-photos`, then `POST /create/new`, then navigation to
   `/create/<id>`. The index gains one row named after the file. Two files dropped show
   «Перетащите одно фото», and no request is sent (fetch counted). A recent-photo button
   creates a draft without any `/files/photos` request.
5. **Automatic topics.** A new draft with the key has `topics_auto: "pending"`. Opening its
   page sends exactly one topics request (fake transport) and shows «Gemini подбирает
   темы…» while it is held, then 3–5 cards, each with a title and a line.
   - The request matches §8.4: URL, headers, `model` `gemini-3.8-flash`, `store` false,
     `thinking_level` `low`, `max_output_tokens` 2 000, the topics schema, a text block
     holding every non-empty profile field, and an image block with `resolution: "high"`
     and the base64 of the view copy.
   - Reloading the page twice sends no further request.
   - «Ещё темы · до $0.02» sends one request per click.
6. **Choosing or typing.** Tapping a card puts «<title> — <angle>» in the topic box, saves
   it (`draft.json` `topic` equals it) and shows «выбрано» on that card with
   `aria-pressed="true"`. Typing autosaves after 800 ms and shows «сохранено». With an
   empty box, «Развернуть» is disabled and «выберите тему или впишите свою» is visible.
7. **Voice.** With the probe's oscillator stream:
   - «Голос» records, and the button reads «Стоп · 0:0N» with `aria-pressed="true"`;
   - stopping posts the blob as `audio/webm` (or `audio/ogg`);
   - the fake transcript «Утренняя пробежка у моря» is appended to the topic box and to
     `draft.json`;
   - the transcription request has `model` `gemini-3.5-flash-lite`, `store` false and an
     audio block.

   After the call, a walk of the fixture root finds no file with an EBML or `OggS`
   signature. A fake 503 leaves the blob in the page and shows «Повторить расшифровку»;
   clicking it sends the same bytes again. The four permission and context states of §8.5
   each render their own words (probe stubs). Recording stops by itself at 2:00 (probe
   with a fake clock).
8. **Expand.** «Развернуть · до $0.05» sends one request matching §8.4: expand schema,
   `max_output_tokens` 6 000, the topic, the profile, the image. Four cards appear in the
   order X, LinkedIn, Instagram, Facebook, with «англ.», «англ.», «укр.», «укр.». Each
   shows the vendor's text in a textarea and the poster's count line, and `draft.json`
   holds the four texts with `source: gemini`.
9. **Edit.** Typing in a card autosaves to `/create/<id>/text` after 800 ms. `draft.json`
   then holds the NFC form with `source: edited`, and the count line shows the server's
   `check_text` counts. A 5 001-character text is refused with «текст длиннее 5 000
   знаков», and the stored text is unchanged.
10. **Nothing truncated.** A fake X text of 312 weighted characters is stored and rendered
    whole (equal to the vendor string after NFC) and its card reads «длиннее лимита:
    312 / 280 — сократите» in red with `role="alert"`, and no other line about the count. The same holds for an
    Instagram caption of 2 300 UTF-16 units and one with 31 hashtags, and for a LinkedIn
    text of 3 100 units after escaping. No code path shortens a text: a test feeds each
    through every route and compares bytes.
11. **Regenerate.** «Перегенерировать» on LinkedIn with the wish «короче» sends one request
    with the regenerate schema, `max_output_tokens` 2 500, LinkedIn's current text and the
    wish. Only `variants.linkedin` changes in `draft.json`; the other three are
    byte-identical.
12. **Expand again.** After an edit the button reads «Развернуть заново — правки пропадут ·
    до $0.05». Pressing it replaces all four variants.
13. **Draft.**
    - `content/drafts/<id>/draft.json` (0600, folder 0700) has the fields of §7.1, and
      `id` matches the poster's id pattern.
    - After a panel restart, `/create/<id>` shows the same topic, cards, texts and stored
      error.
    - `/create` lists the draft under «Черновики».
    - `/files?folder=my-photos` shows «черновик» on its photo; for a photo also named by a
      queued package it shows «в очереди».
    - The run writes nothing to `stock/*/*.json`, `content/packages/`, `rules.json`, the
      poster record or the X ledger (hashes before and after).
    - The fake transport sees only Gemini URLs, and the network guard sees no other
      connection.
14. **Profile.**
    - `/create/profile` saves the eight fields to `content/profile.json` (0600) and shows
      «Профиль сохранён»; `git check-ignore content/profile.json` holds.
    - A 601-character «Кто вы» is refused with its limit, and the form keeps the text.
    - Every topics, expand and regenerate request body contains every non-empty field.
    - With no profile, `/create` reads «Профиль автора не заполнен — темы и тексты будут
      общими» and the requests carry «not filled in».
    - The page works with JavaScript off.
15. **Ledger and month.**
    - Each paid call appends one `reserved` row before the fake transport is called (the
      fake asserts the row exists) and one settle row after.
    - The sub row reads «ИИ · ноябрь $X из $10.00» from the UTC-month total and updates
      from each reply's `month`.
    - Prices: a call on 2026-12-31 23:59 UTC uses $0.75 / $3.75; one on 2027-01-01 00:00
      UTC uses $1.50 / $7.50.
    - For every op, the button bound is at least the reserved bound with every field at
      its limit.
16. **Cap.** With the month at $9.99 and the cap at $10.00:
    - every spending control (topics, expand, regenerate, voice) shows «Бюджет ИИ на
      ноябрь исчерпан: «<действие>» стоит до $0.0N. Новые запросы — с 1 декабря, раньше —
      после того, как вы поднимете месячный лимит в файле .env.» instead of acting;
    - a forced POST to each route answers 409 with that text, and the fake transport saw
      zero requests;
    - the sub row is red with «· лимит».
    - Two threads each reserving a bound that fits alone but not together: exactly one
      passes.
    - A 503 settles `unknown`, and the reservation counts. A 429 settles `failed` and
      counts 0. A timeout settles `unknown`. An `incomplete` reply settles `ok` at its
      usage.
17. **Key.**
    - `GEMINI_API_KEY` is read from the env file per call and appears only in the
      `x-goog-api-key` header of captured requests: not in a URL or body.
    - With the key absent, every spending control reads «нет GEMINI_API_KEY в .env — темы,
      тексты и голос недоступны», no request is built, the draft gets `topics_auto:
      "manual"`, and upload, topic typing, profile and editing still work.
    - A canary key never appears in any page, JSON reply, captured log line, ledger row,
      draft or profile, including when the fake vendor echoes it in an error body.
    - `grep -riE "anthropic|claude" factory/ tests/ tools/ KEYS.md README.md` finds no
      code path, key name or model id.
18. **Errors and concurrency.**
    - A fake 503 on topics stores `error` and shows «Не удалось получить темы от Gemini»
      with one button, «Повторить · до $0.02» (the topics button is hidden while it shows),
      after a reload.
    - `incomplete` shows «ответ Gemini обрезан — повторите».
    - Invalid JSON, or 2 topics against `minItems` 3, shows «Gemini вернул неполный
      ответ — повторите».
    - A transport error shows «нет связи с Gemini — повторите».
    - A view copy with an injected Exif segment answers 409 with no request.
    - Two concurrent expand clicks on one draft: one request, and the other gets 409
      «уже выполняется».
    - A third concurrent AI call across drafts gets 409 «ИИ занят двумя запросами —
      подождите».
19. **Checks.** `python3 -I -B -m unittest discover -s tests -t .` passes, and so does
    `python3 tools/visual_check.py --out DIR` with every state of §16.2 at all seven
    widths. `git status --short --ignored` in the worktree shows nothing new after both.
20. **Live check.** LC1 (§19) ran with at most 6 real Gemini calls, a non-personal test
    image and clip, and a cumulative reserved bound under $0.10. Each call is in the
    ledger, and the lane's report lists every call.

### 16.2 UI states and widths for the visual critic

Every state below runs in `tools/visual_check.py` at 390, 900, 1000, 1100, 1200, 1279, 1280, 1440, 1600 and
1920, with the probe's existing checks: cut text, sideways scroll, overlaps, targets under
24 × 24, an alert below the first screen, and contrast. The visual critic frames each
state at **390, 900, 1440 and 1920** (the named widths, the width between them, and the
widest). Each state is defined by visible text that must be whole on the first screen at
every width (measured with a `Range`). States marked *anchor* load with `#texts` so the
cards are on the first screen at 390.

Two fixtures carry the states. FakeGemini runs in process in both.

- **«create»** is static: the data fixture, plus `my-photos` with 12 photos, five drafts
  (topics, own topic, texts, over limit, error) and a filled profile.
- **«create-live»** has one draft per width for each state that locks or changes a draft
  (topics loading, expand loading, voice, drop), because the visual check runs widths in
  parallel. Without it, one width's held request or `topics_auto` flip would change what
  another width shows.

| State | Setup | Defining text on the first screen |
|---|---|---|
| `create-empty` | Empty fixture with the key, no photos, no drafts, no profile | «Бросьте фото сюда», «Выбрать фото», «Профиль автора не заполнен — темы и тексты будут общими», «ИИ · ноябрь $0.00 из $10.00» |
| `create-start` | «create» at `/create` | «Бросьте фото сюда», «Недавние фото», «Черновики · 5» |
| `create-topics-loading` | «create-live»: the width's draft with `topics_auto: "pending"`; FakeGemini holds the request until teardown | «Gemini подбирает темы…» and the dimmed, disabled «Ещё темы · до $0.02» |
| `create-topics` | «create»: a draft with 5 topics, the second chosen | the five card titles, «выбрано»; «Развернуть · до $0.05» stands directly under the topic box: on the first screen from 1 000 px (probe: 1 000 × 700 and 1 280 × 800), and after a card tap on a narrow page, which scrolls it into view (probe in `create-behaviour`, every width) |
| `create-own-topic` | «create»: a draft with a typed topic, no topics, `topics_auto: "done"` | the typed topic in the box, «Предложить темы · до $0.02», «Развернуть · до $0.05» enabled |
| `create-voice` | «create-live»: the width's own-topic draft; probe: oscillator stream, «Голос» clicked, 1.2 s live | «Стоп · 0:01» (the timer shows once, in the button) |
| `create-expand-texts` | «create-live»: the width's topics draft with no texts; probe taps the last card, waits for «сохранено», clicks «Развернуть» and waits for the four texts | after the tap the box and «Развернуть» are on the screen with their margin kept after «сохранено»; after the texts arrive «Тексты» and the first card's editor are on the screen; from 1 000 px the page has not scrolled |
| `create-expand-loading` | «create-live»: the width's topics draft; probe clicks «Развернуть»; FakeGemini holds | «Gemini пишет тексты…» in the «Тексты» heading row (none in «Тема»), a dimmed, disabled «Развернуть · до $0.05» |
| `create-drop` (functional, not framed) | «create-live» at `/create`; probe passes a generated JPEG named `drop-<width>.jpg` to the drop handler | probe JSON: three upload posts, one `/create/new`, the navigation URL, and one new index row with that name |
| `create-texts` (*anchor*) | A draft with four texts within limits | «X · англ.», «LinkedIn · англ.», «Instagram · укр.», «Facebook · укр.», each count line (the 390 frame is scrolled until each card is whole) |
| `create-over-limit` (*anchor*) | A draft whose X text is 312 weighted characters | «длиннее лимита: 312 / 280 — сократите», the whole X text |
| `create-budget` | «create» fixture with the ledger at $9.99, the `create-topics` draft | «Бюджет ИИ на ноябрь исчерпан: …», the red «ИИ · ноябрь $9.99 из $10.00 · лимит» (the amounts once) |
| `create-error` | A draft with a stored `error` (topics, HTTP 503) | «Не удалось получить темы от Gemini», «Повторить · до $0.02» |
| `create-nokey` | «create» fixture whose env file has no `GEMINI_API_KEY`, the `create-topics` draft and `/create` | «нет GEMINI_API_KEY в .env — темы, тексты и голос недоступны»; the drop zone still active |
| `create-profile` | `/create/profile?saved=1` with every field filled | «Профиль автора», «Профиль сохранён», the eight labels (one column below 600 px: the first two on the first screen, the rest whole when scrolled to) |
| `files-mediateka` | «create» fixture at `/files` | tab «Медиатека» current, the card «Мои фото» with «12 фото» |
| `files-mine` | `/files?folder=my-photos` | «Фото» (the count «12 фото» stands once, in the sub row), the chip «черновик» on a drafted photo |

The existing states (`connection` … `files-photos-upload`) run as today and show the new tab
bar. Visual round 1 (decisions in force for the review page):

- every D′ form is posted by the browser itself: `Referrer-Policy` is `same-origin`, because
  `no-referrer` makes Chrome send `Origin: null` on form POSTs and the Origin check refuses it.
  The visual check submits «Да, опубликовать» and «В очередь» through Chrome at every width
  (`submit-publish`, `submit-queue`) and fails on a refusal;
- once a draft is sent the block heading reads «Публикация» (publishing, interrupted) or
  «Отправлено» (partial, published) and the cards section «Что ушло в сети»; only `draft` keeps
  «Проверка перед отправкой» and «Что уйдёт в сети»;
- the offered rule takes the first of 10:00, 13:00, 16:00, 19:00, 07:00 that passes the slot
  limits (§7.3 item 4) next to the active rules, and the form carries it (`rule_hour`); with none
  free no rule is offered. A refusal at the queue words the checks' lines in Russian
  (`send.rule_words`);
- «Проблем нет» shows only once all crops exist; the draft page's green primary is «Проверить и
  отправить →» as soon as every network has a text, otherwise «Развернуть»; «Да, удалить» is red;
- card heads and status rows name the account only where there is one («Facebook · kotleta»,
  «LinkedIn»), and «частично» in «Черновики» has the attention colour of «прервано».

The critic also checks that:

- the sticky bar never covers the defining text from 900 px up;
- busy buttons keep their width and look disabled;
- «выбрано», the loading lines and the error lines are text, not colour only;
- the voice timer and the loading lines do not shift the layout.

### 16.3 Not touched

- `poster/**`: no change at all.
- The factory core: `factory/{stock,ruleset,planner,runner,journal,checks,attention,cli,
  inputs,paths}.py` and `factory/panel/actions.py`.
- The pages Подключение, Правила, Календарь, Охваты, Подписчики and Диалоги. Their content
  is unchanged; they only show the new tab bar.
- The top-bar status items (bell, X meter, LinkedIn, timer). No AI item goes there.
- `/files` URL and parameters, folder cards, new-folder forms, `/rules/*`, `/img`,
  `/photo`, and the upload route except the `my-photos` creation.
- The snapshot's `state_key` and `build` (drafts and the ledger stay outside).
- No package is written; `content/packages/`, stock `*.json`, `rules.json`, the poster
  record and the X ledger are never written; nothing is published; no X spend.
- No new dependency (standard library only), no vendor but Google Gemini, no Anthropic
  code, key or model. The CSP is unchanged.
- C and D features: crops, frames, quote, highlight, review, publish, queue, draft
  deletion.
- The operator's running panel on port 8770 and the primary checkout. Tests and the
  visual check use port 0 and scratch fixtures.

### 16.4 Test plan and mocks

No test opens a non-loopback socket. The guard in `tests/base.py` turns any real Gemini
call into a failure. `GEMINI_API_KEY` joins `CANARIES` with a canary value, and
`AI_MONTHLY_CAP_USD` stays at its default in fixtures unless a test sets it.

| File | Covers (acceptance items) | Mocks |
|---|---|---|
| `tests/test_author_gemini.py` | Request shapes for the four ops; `store` false; key only in the header; the parse rules of §8.4 (completed via `steps`, via `output_text`, incomplete, failed, empty, bad JSON, wrong shape); usage → price on both sides of 2027-01-01; Exif refusal (5, 7, 8, 11, 15, 17, 18) | `FakeTransport` with scripted replies; a frozen clock |
| `tests/test_author_budget.py` | Reserve, settle, month total, cap refusal with zero sends, two-thread race, statuses per HTTP class, button bound ≥ reserved bound (15, 16) | No transport; temp state folder; threads |
| `tests/test_author_drafts.py` | Create, id pattern, per-field writes under the lock, `topics_auto` once, list cache key and rebuild, 500 cap, traversal and symlink refusals (5, 13) | Temp content folder |
| `tests/test_author_profile.py` | Limits, save and load, prompt block, empty profile (14) | Temp content folder |
| `tests/test_author_create.py` | Every route over `http.client` on port 0: statuses, Host, Origin, CSRF, length and type; `/` redirect and tab bar; default folder including the race and the wrong-lane refusal; recent photos and drafts lists; topics, expand, regenerate, text edits with `check_text` counts and over-limit texts; voice in and no audio on disk; budget and key states; canaries in pages, JSON and the captured log; Медиатека chip (1–18) | `server.make_server(..., ai_transport=FakeTransport)`; the panel fixture's «create» builder |
| Existing `tests/test_panel_server.py`, `tests/test_panel_tabs.py` | Updated only for the redirect and the tab labels (2) | — |
| `tools/visual_check.py` | The states of §16.2, plus probe-mode functional checks: the drop path (4), the voice path with an oscillator stream (7), `MFAuthor.makeCopies` and the slice A upload loop unchanged (2) | An in-process `FakeGemini` passed to `make_server`, which answers by op (taken from the schema or the audio block) and by draft id: canned Russian topics; English and Ukrainian texts, one X text of 312 weighted characters; a 503 for the error draft; a hold on an `Event` released at teardown for the loading states. The probe replaces `getUserMedia` with an `AudioContext` oscillator `MediaStream` and counts `fetch` calls |

`panel_fixture.build_create(root, key=True, ledger_usd=None, live_widths=())` adds the
following to `build_data`:

- `my-photos` with 12 photos stored through `photos.store`;
- the five static drafts of §16.2, or, with `live_widths`, one draft per width and state
  for the «create-live» states;
- a filled profile;
- optionally a ledger with one `ok` row of the given amount, in the current UTC month.

The project's checks run as written in `README.md` and `AGENTS.md`. The lane runs the
suite and the visual check one at a time.

### 16.5 What was cut from B′, and where it went

B′ as specified fits one lane only without the items below; acceptance items 1–7 of the
specification are whole in §16.1.

| Cut | Goes to | Why it can wait |
|---|---|---|
| «Медиатека» as "all photos on top, queue folders deeper", and a «Пост» button on each tile | Slice M (§15) | Spec item 1 asks for the rename, everything slice A shows, and a folder the operator never makes. Those are in B′. The re-layout changes the visual check's ellipsis states and every Files test, so it reviews better on its own |
| Both-language variants (`en+uk`), per-network on/off switches | §21 | The languages are fixed by the decisions; no one asked for switches |
| The `quote` line for the quote-on-photo template | C (§9.1) | Only C draws it |
| «Удалить черновик», removing drafts after send | D (§10.5) | B′ caps drafts at 500 and lists the 10 newest |
| AI month in the top bar | Replaced by the «Создать» sub row (D10) | Measured and simpler |
| Profile that learns from repeated edits | §21 | Not in the acceptance; needs a design for what counts as a repeated edit |
| Text-only posts (no photo) | §21 | The operator asked to start with photos; Instagram needs an image |

## 17. Slice D′: pinned acceptance (the lane is judged against this section)

Slice D′ is slice D of §10 plus one plain crop per network. It follows the operator's
decisions of 2026-11-13: send before images, so that the first real post leaves the panel
sooner, and with it a simple automatic crop for each network, without effects. Templates
and «highlight me» stay in C. The requirement it serves is the one of §1: press one button
that sends everything, with the fewest movements ("drop in a seed, get a finished result").
After the texts, the operator makes three movements: «Проверить и отправить →»,
«Опубликовать сейчас», «Да, опубликовать». The crops are made by themselves.

Read against `main` at `eb75f0a` on 2026-11-13. Every function named here exists at that
commit unless marked *new*.

**Builds:**

- Python: `factory/authoring/send.py` (*new*: crop contract, review checks, package
  writing, publish thread, status, queue and the offered rule, delete). `drafts.py` gains the
  states and fields of §17.2. `gemini.py`'s Exif walk moves to a shared helper with
  unchanged behaviour.
- Panel: the routes of §17.3. `views.create_review` (*new*). The draft page gains
  «Проверить и отправить →» and «Удалить черновик». `/create` gains the stage words of
  §17.2. `model.photo_uses` gains «опубликовано» for published drafts. The folder view's
  package rows gain `id="pkg-<id>"`. `serve` waits for a running publish on Ctrl+C.
- Browser: `author.js` gains `MFAuthor.makeCrop(bitmap, spec, focus)` next to `copy`.
  `static/send.js` (*new*) runs the review page: crops, focus, dialogs and status polling.
  `panel.css` gains the review styles.
- Tests, fixture fakes and visual-check states (§17.6, §17.8). README section «Отправка из
  панели».

### 17.1 Decisions

| # | Decision | Rejected options | Why |
|---|---|---|---|
| D18 | The crops are drawn in the browser on `<canvas>` from the **original** (`/photo?v=orig`, decoded with `createImageBitmap(blob, {imageOrientation: "from-image"})`), saved as JPEG and posted to the server. The server only checks and stores the bytes | Crops on the server; crops from the view copy | The standard library has no image codec (D1; §2 Machine). The view copy is at most 1 600 px on its long side (§6.6), so it cannot give 2 048. Canvas JPEGs carry no camera metadata (slice A, B2) |
| D19 | Sizes. **Instagram** 4:5 as exactly 4k × 5k with k = min(270, ⌊W/4⌋, ⌊H/5⌋), so 1 080 × 1 350 at most. **Facebook** and **LinkedIn** keep the original ratio, with the long side min(2 048, the original's long side). **X** 16:9 as exactly 16k × 9k with k = min(100, ⌊W/16⌋, ⌊H/9⌋), so 1 600 × 900 at most. Nothing is upscaled. JPEG quality is 0.9, then 0.8 and 0.7 while the file is above min(the network's byte limit, 8 MB) | Rounded sizes such as `round(w × 5 / 4)`; the ratio choices of §9.1 | Integer multiples keep Instagram at exactly 0.8, the edge of `IG_MIN_ASPECT` (`rules.py:26`), so rounding can never land at 0.7996. Measured on 2026-11-13 (O): `check_image` passes 1 080 × 1 350 on every network, and 1 536 × 2 048 and 1 600 × 900 everywhere except Instagram's ratio check for 1 536 × 2 048 (aspect 0.750 refused). A 3 024 × 4 032 fixture JPEG (`panel_fixture.make_photo`) takes 0.87 s to generate. The ratio choices stay in C |
| D20 | **Centre crop by default.** One tap on the source photo on the review page sets `focus` (fx, fy in 0..1). Only the cropped networks (Instagram, X) are redrawn. The window is the largest one of the ratio, centred on the focus and clamped inside the photo | Face detection; Gemini; drag-to-crop | The standard library has no face detection, and Gemini is outside D′ (no paid call, decision of 2026-11-13). Without the tap, a portrait centre crop to 16:9 can cut a head; the tap is the smallest fix, and it is optional. Drag-to-crop stays deferred (§21) |
| D21 | `send.review` runs the poster's own functions in the order of `cmd_publish` (`poster/cli.py:210-252`) on the snapshot's env, record and X month, and words each problem in Russian. A parity test against `poster publish --dry-run` keeps the two equal (§17.8). At publish time the poster's own pre-flight runs again and is the authority | Run `--dry-run` for each page and parse its English lines | Parsing would tie Russian words to English sentences, and the dry run also prints every request. The snapshot already holds the env, the record and the X month, rebuilt only when their files change (`model.state_key`), so a review page reads no extra store |
| D22 | Publishing runs in one background thread per content folder, guarded by `flock(content/drafts/.publish.lock, LOCK_EX \| LOCK_NB)`. It calls the injectable publish function, by default `factory.runner.poster_main`, which is `poster.cli.main` in this process. Progress is read from the poster record after a byte offset stored at the start. The outcome is written into the draft when the thread ends | A subprocess; an in-memory flag | The runner already calls the poster in-process (`runner.py:47`), and tests inject a fake transport the same way. A lock file is released by the kernel when the process dies, so after a crash or restart the panel can tell «прервано» from «идёт» without any GET writing |
| D23 | When every target is published, the draft stays, in state `published` and read-only, until «Удалить черновик» | Removing the draft at once (first revision, §10.3) | A removed draft would turn the page that shows the links into a 404 on reload. The «Медиатека» chip can read «опубликовано» for its photo. 500 drafts is far away, and deletion now exists |
| D24 | The targets are `config.PROFILES["kotleta"]` in poster order (`fb:kotleta`, `ig:kotleta`, `linkedin`, `x`). `make_server(..., publish=None, targets=None)` takes both for tests and for LC4. Nothing in the env file or the UI changes them. «В очередь» re-reads the rules file on the POST and refuses a folder that any rule, active or draft, reads with a destination outside these targets, before anything is written | Per-network switches; an env setting | Every decision names all four networks. A constructor parameter is enough for the fakes and for LC4's one-Page run (§17.9) |
| D25 | «В очередь» with no active rule reading the folder carries a checkbox, checked by default: «Публиковать из «<папка>» по правилу: пн, ср, пт в 10:00». One click queues the package, then creates the rule and starts it through `checks.activation_problems`. A refused start saves the rule as a draft and shows why on «Правила» | A second click after queuing; a rule created without the checks | It costs one movement fewer. The checks are exactly what `factory rule start` runs, and the refusal display already exists (`views.rules(ctx, refusal=…)`) |
| D26 | Any problem disables both buttons, including a LinkedIn token and the X month, even for «В очередь» | Queue despite publish-time problems (the runner skips X by itself) | The pinned specification says so. The looser queue is deferred (§21) |

### 17.2 Draft states and fields

`draft.json` keeps every field of §7.1. `drafts.validate` accepts these additions:

```json
{
  "state": "draft | publishing | partial | published",
  "focus": [0.5, 0.35],
  "refused": {"lines": ["x: X budget: …"], "ts": "2026-11-13T10:05:00Z"},
  "publish": {
    "package": "packages/2026-11-13-my-photos-3f2a.json",
    "targets": ["fb:kotleta", "ig:kotleta", "linkedin", "x"],
    "attempts": [{"started": "…Z", "ended": "…Z", "targets": ["fb:kotleta", "…"],
                  "offset": 18234, "exit": 1,
                  "outcome": {"fb:kotleta": {"status": "published", "url": "https://…"},
                              "linkedin": {"status": "failed", "error": "HTTP 401 …"}}}]
  }
}
```

- `focus` is optional; when absent it means (0.5, 0.5). Each value is a number from 0 to 1,
  stored with 3 decimals.
- `refused` is present only after the poster refused a first attempt (exit 2). It is cleared
  by the next publish or queue.
- `publish` exists from the first «Да, опубликовать» on. There are at most 20 attempts. A
  status is one of `published`, `failed`, `unknown` and `interrupted`. `url` and `error` are
  at most 500 characters, stored redacted.
- The files are `out/<network>.jpg` (0600, in `out/`, 0700). `out/` must be a real
  directory, not a symlink.
- **Interrupted** is a display state, never a stored `state`. A draft shows as
  interrupted in two cases:
  - it is in `publishing`, this panel's publisher thread is not working on it, and the
    publish lock can be taken (the panel or its process died). The probe takes the lock
    and releases it at once, and it runs only for such a draft. GETs never write;
  - its last attempt's outcome holds an `interrupted` target, because the publish function
    raised in this process. The thread then stored `partial` with that outcome.

  Its targets without a record row after the attempt's offset read «прервано — проверьте
  аккаунт». A later retry or delete POST, which holds the lock, first stores the outcome
  read from the record.
- **Stage words** on «Создать» → «Черновики» (§8.2): `публикуется`, `частично`,
  `опубликован` and `прервано` (in `--red`), next to B′'s words.
- **Chip** in «Медиатека»: a draft in `published` gives «опубликовано», and any other draft
  gives «черновик»; stock packages still win (§8.8).
- **Read-only once sent.** `GET /create/<id>` of a draft not in `draft` answers 303 to its
  review page. The topic, text, AI, image and focus POSTs answer 409 «черновик уже
  отправлен».
- B′'s refusal at 500 drafts reads «черновиков уже 500 — удалите ненужные».

### 17.3 Routes

The header checks of §14.1 and `do_POST` apply unchanged to every new POST: Host 421;
route 404; Origin 403 (foreign, or absent for non-form kinds); Content-Length 411/400/413;
Content-Type 415; CSRF (a form field, or the header before any body byte). Form refusals
render the review page with 409 and the refusal at the top, the way `_write` renders Rules.

| Route | Kind, limit | Does |
|---|---|---|
| `GET /create/<id>/review[?folder=F]` | page | The review (§17.4). `folder` picks the queue folder shown; the default is the draft's folder |
| `GET /create/<id>/status` | JSON, `no-store`, redacted | `{"state", "interrupted", "done", "total", "line", "targets": [{"target", "network", "status", "text", "url"?}]}`. `status` is `published`, `failed`, `unknown`, `waiting` or `interrupted`. It reads `draft.json`, plus the record tail after the offset only while the draft is `publishing` |
| `GET /create/<id>/file?name=<network>` | image, `no-store` | Streams `out/<network>.jpg` after a sniff (JPEG only), like `/photo`. Any other name is 404 |
| `POST /create/<id>/image?network=N&fx=…&fy=…` | image, 8 MB, `image/jpeg` | Checks the crop and stores it (§17.5 item 3) |
| `POST /create/<id>/focus` | JSON, 64 KB | `{fx, fy}`. Under `.lock`: saves `focus` and deletes `out/instagram.jpg` and `out/x.jpg` |
| `POST /create/<id>/publish` | form, 16 KB: `seen` | Publish now (§17.5 items 8–9) |
| `POST /create/<id>/retry` | form, 16 KB | Re-runs the poster for the failed targets of the last attempt |
| `POST /create/<id>/queue` | form, 16 KB: `folder`, `rule`, `seen` | Queue, and optionally the rule (§17.5 items 13–15) |
| `POST /create/<id>/delete` | form, 16 KB | Deletes the draft (§17.5 item 16) |

The GET dispatcher matches `/create/<id>/(review|status|file)` before the draft-page
catch-all (`server.py:208`), which today would read `<id>/review` as an id and answer 404.

**Security.** Each promise below names the server-side check that keeps it; §17.8 tries
the hostile input.

| Threat | Server-side check | Hostile test |
|---|---|---|
| A foreign site publishes, queues or deletes from the operator's browser | The `csrf` form field (the page's token, which a foreign origin cannot read), a foreign `Origin` refused (403), Host checked (421). Image and focus need `Origin` and the `X-CSRF-Token` header before any body byte | Each new POST with `Origin: http://evil.example`, without the token, and with a wrong `Host`: 403/421; nothing written, and the fake poster is not called |
| A double post | The publish lock (one at a time); the package is put in place with `os.link`, which fails on an existing name; retry only for `failed` targets; `unknown` and interrupted targets are never retried by the panel; the poster refuses an `unknown` target itself | Two concurrent publishes: one 409. Retry after a partial: no request for published targets. A second `/publish` on a sent draft: 409 |
| Path traversal | Draft ids by §7.1 (`Store.path`); `name` in `/file` only one of four network names; `out/` and the draft folder must be real directories; the queue folder through `photos.folder_path` and the snapshot's photo-lane folders | `/create/<id>/file?name=../../.env`, `folder=../x`, an `out/` symlinked to a scratch folder: 404/409; nothing read or written outside |
| A GET changes state | «Прервано» is derived; status and review only read | Hashes of `content/` before and after a series of GETs on every state |
| Key values in pages, JSON, logs, drafts, packages | The poster's `Out` redacts its output; the panel redacts again before storing a line and in `_json`/`_page`; the record's `error` is redacted by the poster | A canary token echoed by a fake vendor error: in no page, status reply, log line, draft or package |
| Publishing what the operator did not see | The review shows the full text and the crop of every target. Its publish and queue forms carry `seen`, the SHA-256 of the targets' texts and crop bytes as rendered. Under the draft lock the server recomputes it and refuses a mismatch with 409 «черновик изменился после проверки — проверьте ещё раз». The package is written from those same files | A text edited or a focus tapped in a second tab after the review was rendered: 409, nothing written. Otherwise the package texts and images are byte-identical to the review's |

### 17.4 The review page

`GET /create/<id>/review`, tab «Создать». The row under the top bar reads, on the left,
«Отправка · черновик от 13 нояб., 10:04», and on the right the AI month (§11.5, as on every
«Создать» page). The page is one column at every width, at most 1 240 px wide and centred,
in this order:

1. **The action block**, always first, so that its words are on the first screen at every
   width:
   - the heading row: «Проверка перед отправкой» and, in state `draft`, «← Изменить
     тексты» (a link to `/create/<id>`);
   - **the crop line** (`role="status"`), shown only while a crop is missing:
     «Готовлю картинки: Instagram, X…». It is one line, not one problem per network. On
     failure it becomes `role="alert"` «Не удалось подготовить картинку для Instagram:
     <причина>», with «Повторить»;
   - in state `draft`:
     - either «Проблем нет · 4 сети» (`k-ok`), or `role="alert"` «Отправить нельзя —
       исправьте:» with one line per problem, each starting with the network name;
     - the poster's earlier refusal, when stored: «Постер отказал до отправки — ничего не
       опубликовано:» with its lines;
     - the row «Опубликовать сейчас» (green, primary) and «В очередь». Both are disabled
       while any problem is listed or any crop is missing; they stay dimmed and keep their
       width;
     - the queue line: «Папка: <select>» (photo-lane folders without problems). Next to it
       is either the rule line «Правило «city-main»: пн, ср, пт в 10:00 · ближайшая
       публикация из папки: пт, 13 нояб., 10:00 · перед этим постом в очереди 3», or the
       checkbox of D25. With JavaScript, changing the select loads `?folder=<f>`;
   - in the other states, the **status block**: the heading line (`role="status"`), one
     row per target, and the actions of that state:

     | State | Heading line | Rows | Actions |
     |---|---|---|---|
     | `publishing`, live | «Публикуется… 1 из 4 · не закрывайте панель» | «Facebook · fb:kotleta — опубликовано · открыть в Facebook», «Instagram · ig:kotleta — ждём…» | none |
     | `partial` | «Опубликовано в 2 из 4 сетей» | links; «ошибка: <ошибка>»; «неизвестно — проверьте аккаунт» | «Повторить упавшие: LinkedIn, X» (dialog), «Удалить черновик» |
     | `published` | «Опубликовано во всех 4 сетях» («Опубликовано в Facebook» for a single target) | four links | «Удалить черновик» |
     | interrupted | «Публикация прервана — проверьте аккаунт» | the rows from the record, «прервано — проверьте аккаунт» for the rest | «Повторить упавшие» only for rows marked `failed`; «Удалить черновик» |

2. **The source photo**, in state `draft` only: the view copy in a box 160 px tall
   (`object-fit: contain`), a 24 px ring at the focus, and the hint «Нажмите на фото, чтобы
   сдвинуть центр кадра (Instagram и X)». A tap maps the point through the contained box
   to (fx, fy), posts `/focus`, and reloads.
3. **«Что уйдёт в сети»**: one card per target in poster order, in a grid of
   `repeat(auto-fill, minmax(min(100%, 280px), 1fr))`. Each card holds:
   - the head «Facebook · fb:kotleta · укр.»;
   - the crop from `/create/<id>/file?name=<network>`, in a box 240 px tall
     (`object-fit: contain`, no layout shift);
   - the size line in mono, «1 536 × 2 048 · 0.3 МБ»;
   - the full text (`white-space: pre-wrap`, `overflow-wrap: anywhere`; nothing is
     clipped);
   - the count line from `gemini.present` (empty when the text is over its limit, because
     that fact stands once, in the problem list);
   - on X: «этот пост в X: $0.215 · после него ноябрь $0.645 из $5.00»;
   - on LinkedIn, when the token has under 7 days left, the non-blocking note «токен
     LinkedIn истекает через 3 дн. — войдите заново: python3 -m poster login linkedin».
4. **«Удалить черновик»** at the bottom in states `draft`, `partial`, `published` and
   interrupted.

**Dialogs.** Each is a native `<dialog>` opened with `showModal()`, so the page behind is
inert. Each holds its own POST form with the `csrf` field:

| Opened by | Text | Buttons |
|---|---|---|
| «Опубликовать сейчас» | «Опубликовать в 4 сети сейчас?» / «Facebook, Instagram, LinkedIn и X. Это нельзя отменить.» (the count by `strings.plural`) | «Да, опубликовать» (green), «Отмена» |
| «Повторить упавшие» | «Повторить публикацию в LinkedIn и X?» | «Да, повторить», «Отмена» |
| «Удалить черновик» | «Удалить черновик?» / «Тексты и картинки черновика пропадут. Фото останется в «Медиатеке», опубликованные посты — в сетях.» | «Да, удалить», «Отмена» |

**The problems, in Russian, from the poster's own checks** (D21). Each line starts with
«Facebook:», «Instagram:», «LinkedIn:» or «X:».

| Poster step (`cmd_publish`) | Line |
|---|---|
| no variant for a target | «нет текста — нажмите «Развернуть»» (stricter than the poster, which skips the target) |
| record latest is `unknown` | «прошлая попытка закончилась неизвестно — проверьте аккаунт» |
| `t.missing(env)` | «нет FB_PAGE_KOTLETA_TOKEN в .env» (names only, joined with «, ») |
| `check_text` errors | the `problems` of `gemini.present` (one counting rule; «текст пуст» included) |
| `check_image(network, sniff(out))` errors | «картинка 1 536 × 2 048 не подходит: соотношение сторон 0.750 вне 0.8–1.91», «…: нужен JPEG», «…: больше 5 МБ», «…: больше 36 152 320 пикселей», «…: не читаются размеры» |
| `linkedin.token_problems` errors | «токен истёк или истекает в ближайшие 10 минут — войдите заново: python3 -m poster login linkedin»; «LINKEDIN_TOKEN_EXPIRES_AT не читается — войдите заново: …» |
| `xapi.estimate` + the X month against `X_MONTHLY_CAP_USD` | «этот пост стоит $0.215, за ноябрь уже $4.900 из $5.00 — не помещается в лимит» |
| `config.load_settings` error | «.env: <message>» (the poster's message names a variable, never a value) |

A missing crop is not on this list; it is the crop line. A missing crop on a forced POST
answers 409 «картинки ещё не готовы».

### 17.5 Acceptance list

Each item is observable by a test, a probe or a screenshot named in §17.6–§17.8. The
specification's items map as follows:

| Specification item | Acceptance items |
|---|---|
| 1 (crops) | 1–3 |
| 2 (review) | 4–6 |
| 3 (publish now) | 7–12 and 17 |
| 4 (queue) | 13–15 |
| 5 (delete) | 16 |
| 6 (checks) | 18 |
| 7 (keys) | 19 |
| Fences | 20 |

1. **Crop sizes.**
   - For a draft whose original is a 3 024 × 4 032 JPEG, the review page makes and posts four
     JPEGs and stores them as `content/drafts/<id>/out/<network>.jpg` (0600). Instagram is
     1 080 × 1 350, Facebook and LinkedIn are 1 536 × 2 048, and X is 1 600 × 900.
   - Each file sniffs as JPEG, `poster.rules.check_image(network, sniff(path))` returns no
     error, and the marker walk finds no APP1 `Exif` segment.
   - An EXIF-6 original stored 4 032 × 3 024 gives the same portrait sizes.
   - A 320 × 240 original gives 192 × 240, 320 × 240, 320 × 240 and 320 × 180 (nothing is
     upscaled).
   - `MFAuthor.makeCrop`'s window for X on 3 024 × 4 032 at the centre is (0, 1 166, 3 024,
     1 701), and the probe reports it.
2. **Focus.**
   - A probe tap at (0.5, 0.2) of the source photo stores `focus: [0.5, 0.2]`, deletes the
     Instagram and X crops, and reloads. The page makes them again: the X window is now
     (0, 0, 3 024, 1 701), and its file differs from the centre crop (SHA-256). The
     Facebook and LinkedIn files are untouched (same mtime).
   - A crop posted with the old `fx`/`fy` answers 409 «кадр изменился — обновите страницу»,
     and nothing is stored.
3. **The crop route.** `POST /create/<id>/image` runs the header checks of §17.3, then
   answers 409 with nothing written when:
   - the body is not a JPEG by sniffing;
   - it carries an APP1 `Exif` segment;
   - `check_image` refuses it;
   - its ratio is not the network's: Instagram exactly 4:5, X exactly 16:9, Facebook and
     LinkedIn within 1 % of the view copy's ratio from the photo index;
   - its size is over 1 080 × 1 350 or 1 600 × 900, or its long side is over 2 048 or below
     the view copy's long side;
   - the draft is not in `draft`.

   An accepted crop is written to `out/.up-<random>` and moved into place with
   `os.replace` under `.lock`. Making crops sends nothing outside the machine: the fake
   transports see no request, and the AI ledger and the X ledger are byte-identical before
   and after.
4. **Review page.**
   - The draft page shows «Проверить и отправить →» once a text exists for every target's
     network. It stands on its own row directly under the «Тексты» heading row, outside
     that flex row, and is hidden while «Gemini пишет тексты…» shows. So it is on the first
     screen with `#texts` at 390 px and in the right column from 1 000 px. It leads to
     `/create/<id>/review`.
   - The review has the heading «Проверка перед отправкой». For each target in poster order
     it shows the network name, the target id, the language word, the full text (equal to
     the draft text, nothing clipped), the crop with its size line, and the count line from
     `gemini.present`.
   - The X card reads «этот пост в X: $<estimate> · после него <месяц> $<month + estimate>
     из $<cap>», from `xapi.estimate(text, True, settings)` and the snapshot's X month.
5. **Checks exactly as the poster.**
   - `send.review` runs, per target, the steps of `cmd_publish` in its order, and words them
     as in §17.4.
   - A parity test over the matrix of §17.8 builds, for each case, the package `send` would
     write and runs `poster.cli.main([... "publish", P, "--targets", T, "--dry-run"])` on the
     same env and state. The review lists a problem for a target exactly when the dry run
     names that target in its refusal lines, and it is clean exactly when the dry run exits
     0.
   - `send` is stricter on purpose in two cases, which the test asserts apart:
     - a missing crop: the review blocks it, while the dry run blocks only Instagram's
       (Facebook, LinkedIn and X would go out as text-only posts);
     - a missing text: the review blocks it, while the dry run skips the target.
6. **Problems block.**
   - Any problem disables both buttons and is listed under «Отправить нельзя — исправьте:»
     (`role="alert"`). The block is whole on the first screen at all ten widths.
   - Missing variables are shown by name only.
   - A forced `POST /publish` or `/queue` with a problem answers 409 with the same list.
     Nothing is written: no package, no media, no record row, no ledger row. The fake
     poster and the fake transport saw nothing.
7. **Confirmation.**
   - «Опубликовать сейчас» opens the dialog of §17.4.
   - While it is open, Tab cycles only inside it, and a click outside it reaches nothing
     behind: probe on `document.activeElement` and a click on «В очередь» behind it, with no
     form submitted.
   - «Отмена» and Escape close it, and nothing is posted.
8. **Package.** «Да, опубликовать» posts `/create/<id>/publish`.
   - Under the publish lock and the draft's `.lock`, the server checks the form's `seen`
     against the draft as it is now (§17.3, Security), then re-runs `send.review`.
   - It writes the media and then the package:
     - the media are `content/packages/media/<id>/<network>.jpg`, byte-identical to
       `out/`, prepared under a dot-name and renamed into place;
     - the package is `content/packages/<id>.json`, written as a temporary dot-file and put
       into place with `os.link`, so an existing name refuses.
   - The package has `schema` 1, `id` = the draft id, `theme` = the topic, one variant per
     target `{"text", "image": "media/<id>/<network>.jpg"}`, and `meta` holding
     `approved_by_operator` = today's local date, `source` = `"panel"` and `photo`.
   - `poster.package.load(path, paths.library)` loads it without problems; if it does not,
     both are removed and the answer is 409.
   - The draft becomes `publishing` with its first attempt, and the answer is 303 to the
     review page.
9. **One publish at a time.**
   - The publish function is called once, in a background thread, with exactly
     `["--env-file", E, "--state-dir", S, "publish", P, "--targets",
     "fb:kotleta,ig:kotleta,linkedin,x", "--library", L]`. E, S and L are the panel's own
     `paths.env_file`, `paths.poster_state` and `paths.library`, so the poster and the
     panel cannot resolve different folders. It also gets the panel's clock. Output is
     captured, and only redacted lines are stored.
   - While a held fake runs, a second «Да, опубликовать» on the same draft or on another
     draft answers 409 «публикация уже идёт — дождитесь конца». Nothing new is written,
     and the fake was still called only once.
10. **Status.**
    - In `publishing`, `send.js` polls `GET /create/<id>/status` every 3 s and updates the
      rows in place.
    - Rows read «опубликовано · открыть в <сеть>» (the record's URL, `target="_blank"
      rel="noopener"`), «ошибка: <redacted error>», «неизвестно — проверьте аккаунт» or
      «ждём…».
    - When `state` leaves `publishing`, the page reloads once.
    - A status read uses only the record bytes after the attempt's `offset`. A test fills
      the record before the offset with unparseable lines, and the status stays correct.
11. **Outcomes.**
    - **Exit 0:** the draft is `published`, with «Опубликовано во всех 4 сетях» and four
      links.
    - **Exit 1:** the draft is `partial`, with «Опубликовано в 2 из 4 сетей», the links,
      the errors and «Повторить упавшие: LinkedIn, X». Its dialog posts `/retry`, which
      calls the poster with `--targets linkedin,x` on the same package file. The draft is
      then `published`, and the scripted transport saw no second Facebook or Instagram
      request. An `unknown` target is never retried by the panel.
    - **Exit 2 on a first attempt:** the package and media are removed, the draft is back in
      `draft`, and it shows «Постер отказал до отправки — ничего не опубликовано:» with
      the poster's lines. An exit 2 on a retry keeps `partial` and shows the lines the same
      way.
12. **Crash.**
    - (a) The publish function raises after writing a record row for Facebook. Facebook
      keeps its link, the other targets read «прервано — проверьте аккаунт», and the heading
      reads «Публикация прервана — проверьте аккаунт». The panel log gets one redacted line.
    - (b) A fixture draft is left in `publishing` with no live publisher and a free lock,
      as after a killed panel. After a panel start its review reads the same, and
      «Черновики» on `/create` shows «прервано». No GET writes (hashes of `content/` before
      and after).
    - (c) On Ctrl+C during a held publish, `serve` prints «panel: ждём окончания
      публикации…» and returns only after the thread has ended. A test raises
      `KeyboardInterrupt` from `serve_forever` and releases the fake after 0.2 s.
13. **Queue.**
    - «В очередь» posts `/create/<id>/queue` with `folder` (a photo-lane folder from the
      snapshot, checked again on the server; default the draft's folder).
    - Under `panel.write_lock` and `.lock`, the server checks `seen` as for publishing,
      re-runs `send.review` and writes:
      - `stock/<folder>/media/<id>/<network>.jpg`;
      - `stock/<folder>/<NNN>-<id>.json`, by the same link method. `NNN` is 1 + the
        largest three-digit prefix in the folder, and the server refuses at 999.
    - It loads the file with `poster.package.load`, removes the draft, and answers 303 to
      `/files?folder=<folder>&queued=<id>#pkg-<id>`.
    - That page shows the package row (`id="pkg-<id>"`) with the chip «в очереди» on its
      photo. For each variant, `GET
      /img?folder=<folder>&file=<NNN>-<id>.json&ref=media/<id>/<network>.jpg` answers 200
      `image/jpeg`.
    - `python3 -m factory check` prints no problem line naming the file, and its problem
      lines equal those before the queue.
    - A duplicate id against the stock or `content/packages/` answers 409, and nothing is
      written.
14. **Existing rule.** With `?folder=city` on the data fixture (`city-main`, active, Mon,
    Wed, Fri 10:00 Europe/Berlin, `NOW` Wed 2026-11-11 10:40), the queue line reads
    «Правило «city-main»: пн, ср, пт в 10:00 · перед этим постом в очереди N · ближайшая
    публикация из папки: пт, 13 нояб., 10:00 · этот пост выйдет: <date>». N is the folder's
    `ready` count from the snapshot plan; the two dates come from that plan, not from the rule's
    raw slots (the planner skips a slot that breaks a limit): «ближайшая» is the first planned
    slot (shown when N > 0), «этот пост» the first slot after the planned ones that breaks no
    limit. No checkbox is shown.
15. **The offered rule.** With no active rule reading the folder, the checkbox of D25 is
    shown and checked. Queuing with it creates a rule:
    - its id is the folder name, or `<folder>-2` … `<folder>-9` if taken;
    - its fields are `folder`, the four targets, `mon`, `wed`, `fri`, `10:00`, the machine
      zone, `status` `active` and `active_since` now;
    - it is checked by `checks.activation_problems` on inputs loaded after the package is
      written, and written by `fruleset.write` against the loaded revision.

    Then:
    - **Passes** (a fixture without `city-main`): `rules.json` holds the active rule, and
      `python3 -m factory plan --rule my-photos --days 14` lists `<NNN>-<id>.json` in a slot.
    - **Refused** (the data fixture: `city-main` at the same hours breaks the minimum gap):
      the package stays queued, the rule is saved as `draft`, and the answer is the Rules
      page with 409. On the new rule's row it shows «Пост в очереди «Мои фото». Правило
      сохранено черновиком, но не запущено:» and the checks' lines.
    - **Unchecked:** `rules.json` is byte-identical.
16. **Delete.**
    - «Удалить черновик» (draft page and review page) opens its dialog. «Да, удалить» posts
      `/create/<id>/delete`. Under `.lock` the folder is renamed to a dot-name and removed,
      and the answer is 303 to `/create`.
    - The photo is still listed in «Недавние фото» and «Медиатека».
    - `content/packages/`, the stock and the poster record are byte-identical.
    - Deleting answers 409 «идёт публикация» while a publish runs. It is allowed in
      `draft`, `partial`, `published` and interrupted.
17. **Sent drafts across the panel.**
    - `GET /create/<id>` of a sent draft answers 303 to its review.
    - Every edit POST answers 409 «черновик уже отправлен».
    - «Черновики» shows the stage words of §17.2.
    - The photo of a published draft carries «опубликовано» in «Медиатека».
18. **Checks.** `python3 -I -B -m unittest discover -s tests -t .` passes. `python3
    tools/visual_check.py --out DIR` passes with every state of §16.2 and §17.6 at all ten
    widths. `git status --short --ignored` in the worktree shows nothing new after both.
19. **Keys.** Canary values (`tests/base.py` `CANARIES`) never appear in any page, JSON
    reply, status row, captured panel log, draft, package, crop file name, or test output.
    This includes a fake vendor error body that echoes a token: the poster records it
    redacted, and the panel redacts again before storing or answering.
20. **No real publishing, no spend.**
    - Every test and the visual check run the poster through `poster.cli.main` with a
      `FakeTransport`, or through a fake publish function. `tests/base.py`'s network guard
      sees no non-loopback connection.
    - The X ledger rows written in tests live in each test's scratch state folder.
    - No Gemini request is made by D′ code.

### 17.6 UI states and widths for the visual critic

Every state runs in `tools/visual_check.py` at the ten widths (390, 900, 1000, 1100, 1200,
1279, 1280, 1440, 1600, 1920), with the probe's existing checks: cut text, sideways scroll,
overlaps, targets under 24 × 24, an alert below the first screen, and contrast. The
probe's check of the defining text gains the dialog: its title and buttons are whole and
inside the viewport, and focus is inside it.

The visual critic frames each state at **390, 900, 1440 and 1920**: 390 is the named phone
width, 1440 the named desktop, 900 a width between them, and 1920 the widest. Each state is
defined by visible text that must be whole on the first screen at every width (measured
with a `Range`). The cards are judged scrolled until each is whole.

Four fixtures carry the states. They are separate from B′'s, so B′'s states and counts stay
as they are. All use the data fixture's env and record:

- **«send»** (static): `my-photos` with one 3 024 × 4 032 photo and 12 small ones, and these
  drafts:
  - `ready`: four texts, and crops stored by the fixture at the D19 sizes, so the static
    frames do not wait on the canvas;
  - `publishing`: published to Facebook, held. At fixture start the visual check reads
    `csrf` and `seen` from its rendered review page and posts `/publish` once, against a
    `FakePoster` that writes the Facebook row and waits on an `Event` released at
    teardown;
  - `partial`: Facebook and Instagram published with URLs; LinkedIn failed «HTTP 401 …»;
    X failed;
  - `published`;
  - `queue-me` and `rule-me`. Setup queues `queue-me` with the rule checkbox off (the
    `queued` frame), then `rule-me` with it on (the `rule-refused` frame). The refused rule
    is saved as a draft, so `review` still offers a rule.
- **«send-problems»**: an env without `FB_PAGE_KOTLETA_TOKEN` and with
  `LINKEDIN_TOKEN_EXPIRES_AT` in the past, plus a draft whose X text is 312 weighted
  characters.
- **«send-crash»**: one draft left in `publishing` with a Facebook row in the record and
  no publisher.
- **«send-live»**: one draft per width for each state that changes a draft (crops, focus),
  because widths run in parallel.

| State | Setup | Defining text on the first screen |
|---|---|---|
| `send-draft` | «send», `/create/<ready>#texts` | «Проверить и отправить →» on the first screen; «Удалить черновик» whole when scrolled to (the bottom link row) |
| `review` | «send», `/create/<ready>/review` | «Проверка перед отправкой», «Проблем нет · 4 сети», «Опубликовать сейчас», «В очередь», «Папка», «Публиковать из «Мои фото» по правилу: пн, ср, пт в 16:00» (the queue offering the first free hour, since `city-main` holds 10:00) |
| `review-rule` | «send», `…/review?folder=city` | «Правило «city-main»: пн, ср, пт в 10:00 · ближайшая публикация из папки: пт, 13 нояб., 10:00» (the queue with an existing rule) |
| `review-problems` | «send-problems» | «Отправить нельзя — исправьте:», «X: длиннее лимита: 312 / 280 — сократите», «Facebook: нет FB_PAGE_KOTLETA_TOKEN в .env», «LinkedIn: токен истёк…»; both buttons dimmed and disabled |
| `review-crops` | «send-live»; the probe holds the first `/image` fetch | «Готовлю картинки: Facebook, Instagram, LinkedIn, X…», buttons disabled. Then, released, probe JSON: four sizes, the X window and one reload |
| `review-focus` (functional) | «send-live»; probe taps (0.5, 0.2) | probe JSON: the stored focus, new X and Instagram crops, unchanged Facebook and LinkedIn |
| `review-confirm` | «send», `ready`; probe clicks «Опубликовать сейчас» | «Опубликовать в 4 сети сейчас?», «Это нельзя отменить.», «Да, опубликовать», «Отмена»; focus inside the dialog; nothing posted |
| `review-publishing` | «send», `publishing` | «Публикуется… 1 из 4 · не закрывайте панель», «Публикация» (the heading), «Facebook · kotleta — опубликовано», «Instagram · kotleta — ждём…» |
| `review-partial` | «send», `partial` | «Отправлено» (the heading), «Опубликовано в 2 из 4 сетей», «LinkedIn — ошибка: HTTP 401 …», «Повторить упавшие: LinkedIn, X» |
| `review-published` | «send», `published` | «Отправлено» (the heading), «Опубликовано во всех 4 сетях», four «открыть в …» |
| `review-interrupted` | «send-crash» | «Публикация прервана — проверьте аккаунт», «Публикация» (the heading), «Instagram · kotleta — прервано» (the instruction stands once, in the line) |
| `review-delete` | «send», `published`; probe clicks «Удалить черновик» | «Удалить черновик?», «Да, удалить», «Отмена»; nothing posted |
| `queued` | «send» after setup queued `queue-me` to `my-photos` | `/files?folder=my-photos&queued=<id>#pkg-<id>`: the row `<NNN>-<id>.json` with «в очереди» and its image from `/img` |
| `rule-refused` | «send»: setup posts `/queue` for `rule-me` with the rule (helper `post_page`) | Rules page, 409: «Пост в очереди «Мои фото». Правило сохранено черновиком, но не запущено:» and the gap line |
| `send-start` | «send», `/create` | «Черновики · N» with «публикуется», «частично», «опубликован» |

The critic also checks that:

- the sticky bar never covers the defining text from 900 px up;
- disabled buttons keep their width and look disabled;
- statuses differ by words, never by colour alone;
- the 240 px crop boxes do not shift the layout when an image arrives;
- no dialog leaves the viewport at 390 × 844.

### 17.7 Not touched

- `poster/**`: no change at all. The panel calls `cli.main`, `package.load`, `rules`,
  `config`, `linkedin.token_problems`, `xapi.estimate` and `state` as they are.
- The factory core: `factory/{stock,ruleset,planner,runner,journal,checks,attention,cli,
  inputs,paths}.py` and `factory/panel/actions.py`. D′ calls `checks.activation_problems`,
  `fruleset.parse_rule`/`write`, `finputs.load`, `fstock` and `runner.poster_main`.
- The bell and its attention items (an item for an interrupted publish is deferred, §21).
- B′'s Gemini routes, prompts, budget and ledger. `gemini.py` changes only by moving its
  Exif walk into a shared helper, and every B′ test passes unchanged.
- The pages Подключение, Календарь, Охваты, Подписчики and Диалоги. On Правила, only the
  existing refusal block is reused for D25. In «Медиатека», only the row anchor and the
  chip of §17.2 change.
- `/img`, `/photo`, the upload route, `/files` parameters and the snapshot's `state_key`
  and `build`.
- The CSP: crops are same-origin images; canvas reads a same-origin blob; no `blob:` URL is
  shown.
- No new dependency, no vendor call, no Anthropic code, no Gemini call.
- C's features: ratio choices, frame, quote, highlight, side by side, base switch.
- The operator's running panel on port 8770 and the primary checkout. Tests and the visual
  check use port 0 and scratch fixtures. No real publishing: LC4 runs after the merge
  (§17.9).

### 17.8 Test plan and mocks

No test opens a non-loopback socket (`tests/base.py` guard). The poster's network is always
mocked: either `poster.cli.main(argv, transport=FakeTransport([...]), sleep=lambda s:
None, ...)`, the way `tests/test_factory_tick.py:261` does it, or a fake publish function.
Scripted four-target replies reuse the shapes of `tests/test_cli.py`
(`test_partial_failure_four_lines_exit_1_and_x_last`, `ig_success()`).

| File | Covers (items) | Mocks |
|---|---|---|
| `tests/test_author_send.py` (*new*) | Routes over `http.client` on port 0, with header checks and hostile input (`Origin: http://evil.example`, a missing token, `name=../../.env`, `folder=../x`, an `out/` symlinked to a scratch folder: 403/404/409, nothing written outside). Crop checks with `make_photo` bytes at the D19 sizes and wrong ones, Exif from `make_exif6`, the old focus (3). Review lines (4–6). Package, thread, 409, status offset, outcomes, retry, exit 2, crash and restart, Ctrl+C (8–12). Queue with `factory.cli.main(["check"])` and `(["plan", "--rule", …])` in process, `/img`, the rule passed, refused and unchecked (13–15). Delete (16). Sent drafts (17). A `seen` mismatch after an edit in a second tab (8, 13). Canaries (19). Ledgers unchanged by crops (3, 20) | `server.make_server(..., publish=FakePoster(...), targets=None)`; `FakeTransport` |
| `tests/test_author_send.py` `ParityTest` | Item 5. Cases: clean; X 281 weighted; X two cashtags; Instagram 2 201 units; 31 hashtags; 21 mentions; LinkedIn 3 001 after escaping; empty Facebook text (both block; the poster names no target); missing `FB_PAGE_KOTLETA_TOKEN`; missing `X_ACCESS_SECRET`; LinkedIn expired; LinkedIn expiry unreadable; X month at $4.90 of $5.00; a 3:4 Instagram file placed in `out/`; a PNG placed in `out/`; a record row `unknown` for `ig:kotleta`. The intended stricter cases (missing crop, missing text) are asserted separately | `--dry-run` uses `DryRunTransport`; nothing is sent |
| `tests/test_author_drafts.py` | The new states and fields, the limits of §17.2, and the stage words | Temp content folder |
| `tests/panel_fixture.py` | `build_send(root, *, problems=False, crash=False, live_widths=())`, and `FakePoster(script, hold=None, raise_after=None)`. The latter calls `poster.cli.main` with a scripted `FakeTransport`, optionally waits on `hold`, or raises after a given record row | — |
| `tools/visual_check.py` | The states of §17.6. `start()` gains `publish=` and `targets=` | The in-process `FakePoster` |

The project's checks run as `AGENTS.md` and `README.md` give them, one at a time through the
gate wrapper.

### 17.9 LC4, after the merge (not in this lane)

LC4 checks the panel's publish path end to end with the real poster. It runs only after the
merge, and only with the operator's go-ahead. It is free: it uses Facebook only, and the
post is deleted at once.

- **Page:** the main profile's Facebook Page (`fb:kotleta`). The operator chose that Page
  for the factory's live schedule test, with the post deleted within minutes and the other
  networks untouched. The go-ahead question repeats the choice.
- **Inputs:** a generated, non-personal image (`panel_fixture.make_photo(3024, 4032, …)`)
  and a typed one-line Ukrainian text. No Gemini call is made.
- **Setup:**
  - an in-process panel on port 0, with `targets=("fb:kotleta",)` and the default publish
    function (the real poster and the real transport);
  - the repository's env file, read in place, never copied or printed;
  - `MF_CONTENT_DIR` in the stage's scratch folder;
  - the operator's default poster state, so the record stays honest (X is not targeted, so
    the X ledger is untouched).
- **Steps:**
  1. Upload the image through `/files/photos` into `my-photos`, with its thumb and view
     copies made by the probe as in LC1. Then `POST /create/new` and `/create/<id>/text`
     for Facebook.
  2. Open `/create/<id>/review` in the cached headless Chrome through a DevTools session,
     as the visual check's live states do, until the crop line is gone. So the crop comes
     from the browser's canvas.
  3. Read the problems block: it must say «Проблем нет · 1 сеть».
  4. `POST /create/<id>/publish` with the `csrf` and `seen` fields of that page.
  5. Poll `/status` until `published` (at most 3 minutes).
  6. Read the URL and post id from the record, then run `python3 -m poster delete --target
     fb:kotleta --post-id <id>`.
- **Report:**
  - the draft id, the HTTP statuses, the record rows (`published`, then `deleted`) and how
    many minutes the post was visible;
  - the review and published screenshots at 390 and 1440;
  - the AI ledger's row count before and after, which must be equal. The draft page, whose
    script would send the automatic topics request, is never opened.

  No key, Page id or token appears. If the delete fails, the report says so at once and
  the operator deletes the post by hand.

After LC4 passes, the operator's first real post from the panel goes to all four networks.
That post is their own action through the review page, not a check.

### 17.10 What was cut from D′, and where it went

| Cut | Goes to | Why it can wait |
|---|---|---|
| Ratio choices, frame, quote, Gemini highlight, side by side, base switch | C (§9, §15) | Decision of 2026-11-13: plain crops now, templates and highlight later |
| An attention-bell item for an interrupted publish | §21 | «прервано» shows on the review page and in «Черновики» on `/create`, the panel's first page |
| Re-publishing an interrupted target from the panel | §21 | It risks a double post; the poster's `--force-target` exists for the rare case |
| Per-network switches; queuing despite publish-time problems | §21 | The specification blocks both buttons on any problem (D26) |
| Editing texts after a partial publish | §21 | A sent draft is read-only; the operator retries or deletes |
| Choosing the offered rule's days and hours on the review page | Правила | The rule is saved and editable there |

## 18. Slice C: pinned acceptance (the lane is judged against this section)

Slice C adds the optional image work of §9 on top of D′'s plain crops. The requirement it
serves is the operator's of 2026-11-11 (§1): maybe put an effect on the photo, or make the
main person, the operator, stand out somehow. Their later decisions shape it:

- 2026-11-08: photos always get code templates (quote on the photo, frame, crop per
  network), plus optional AI effects through Gemini;
- 2026-11-11 and 2026-11-12: Gemini highlights the main person (blurred background, glow or
  outline), with several styles to choose from, inside the shared $10 a month;
- 2026-11-13: D first, then C (form answer at 06:59 UTC); D′ with plain automatic crops
  first, templates and «highlight me» in C afterwards (answer at 07:06 UTC to the form
  asked at 07:01, which is the time §1's table gives). Both times were read in the primary
  record.

Everything C adds is optional, so the fewest movements stay as they are. With no C
control touched, D′'s plain crops go out unchanged (item 12). A styled post costs one
paid click (a style) and one free click («Взять за основу»). A quote or a frame costs one
free choice per network.

Read against `main` at `4dd221f` on 2026-11-13. Every function named here exists at that
commit unless marked *new*.

**Where §9 and the merged code disagree, the code governs**, as the brief for this
section requires. Each case is a decision below, and §9 stays as the first revision's
plan:

- **The controls go on the review page, not the draft page** (§9.3). See D27.
- **Instagram 1.91:1 is 955 × 500, not 1 080 × 566** (§9.1). See D28.
- **Settings are stored at the top level, not per variant** (§7.1). See D29. This one
  conflicts with B′ code rather than D′ code.
- **A change deletes crops, and the page re-makes them** (§9.1). See D30.
- **A focus tap deletes every crop that is not at the original ratio**, where D′ deletes
  only Instagram and X (`send.py:604-606`). See D35.

**Builds:**

- **Python.**
  - `send.py`: the ratio choices and their sizes (`crop_size`, `crop_problem` and
    `store_crop` take the network's chosen ratio and the base); the settings write; the
    style files.
  - `gemini.py`: the `highlight` op, the `quotes` of the expand schema, and the Russian 4xx
    wording.
  - `prompts.py`, `prices.py` and `budget.py`: the image model, its price and its bound.
  - `drafts.py`: the fields of §18.2.
  - `poster/http.py`: `vendor_message` reads a JSON array; this is the one poster change.
- **Panel.**
  - `server.py`: the routes of §18.3.
  - `views.create_review`: the «Фото» section and the card controls (§18.4).
  - `strings.py`: every new Russian string.
- **Browser.**
  - `author.js`: `MFAuthor.makeCrop(bitmap, spec, focus)` takes the optional `spec.frame`
    and `spec.quote`. `MFAuthor.cropSize` takes the ratio, and `MFAuthor.layoutTemplate`
    is *new*.
  - `send.js`: the base as the crop source, the style calls, the settings posts and the
    `look` value on each crop post.
  - `panel.css` and `probe.js`.
- **Tests, fixture fakes and visual-check states** (§18.6, §18.8). A README section
  «Картинки: шаблоны и стили».

### 18.1 Decisions

| # | Decision | Rejected options | Why |
|---|---|---|---|
| D27 | The ratio, frame and quote controls, the style strip and «Взять за основу» live on the **review page**: the strip in a «Фото» section that replaces D′'s source box, the per-network controls on each card. The draft page stays as B′ and D′ left it | The draft page's photo as the strip (§9.3) | D′ put the crops, the focus tap and the previews on the review page (`views.py:1437-1467`, `send.js:99-190`). So C's controls sit next to what they change, and the draft page keeps its measured first screen (§8.3: the topic box and «Развернуть» on a 700 px screen) |
| D28 | Every fixed ratio a:b gives exactly a·k × b·k, with k = min(⌊capW/a⌋, ⌊capH/b⌋, ⌊W/a⌋, ⌊H/b⌋) for a base of W × H. The cap box (capW, capH) is Instagram 1 080 × 1 350, X 1 600 × 1 600, and Facebook and LinkedIn 2 048 × 2 048. «как у фото» keeps the base's ratio with the long side min(cap, the base's long side), where the cap is 1 600 for X and 2 048 for Facebook and LinkedIn. **1.91:1 is 191:100**. Nothing is upscaled | 1.91:1 as 1 080 × 566 (§9.1) | This extends D′'s own rule (`send.py:76-87`, `author.js:65-75`; D19), which keeps the poster's aspect checks exact. 1 080 × 566 is 1.908, not 1.91. Spec item 4 asks for the exact integer size of the ratio. 955 × 500 is exactly 1.91, which `check_image` accepts (`IG_MAX_ASPECT`, `rules.py:26`; `955/500 <= 1.91` is True, O). Instagram upscales it about 13 % for display; §21 names the trigger to revisit |
| D29 | The draft keeps `base`, `look`, `quotes`, `who` and `highlight_error` **at the top level** (§18.2) | `image`, `template` and `quote` inside each variant (§7.1) | B′ code replaces a variant's whole dict on every edit, expand and regenerate (`server.py:498-499`, `gemini.py:286-288`). A choice stored inside it would vanish on the next keystroke |
| D30 | A change of ratio, frame, quote or base deletes the affected `out/<network>.jpg` under `.lock`, and the reply reloads the page. D′'s `missing` path (`send.js:235-237`) then re-makes the crops. Each crop POST carries `look`, a 12-hex digest of that network's base, ratio, frame, quote place and quote text. `store_crop` refuses a mismatch with D′'s «кадр изменился — обновите страницу». An absent `look` means the default look, so D′'s posts and tests stay valid | Redrawing in place without a reload; a version counter | It is the mechanism D′ already uses for the focus (`send.py:584-585`, `:593-608`), so one path makes every crop. The digest refuses a crop drawn from a stale page (a second tab, or a crop chain still running when the base changed). `seen` already makes the published bytes the reviewed ones (`send.py:288-299`) |
| D31 | The quote is laid out with the canvas's own `measureText`, so what is measured is what is drawn. The font starts at 6 % of the width and steps down by 1 px to max(10 px, 2.5 % of the width). The text is at most 4 lines. A quote that does not fit fails that crop with a reason; it is never cut | Line breaking by a hidden DOM element; truncating the quote | The canvas measure is exact for the pixels. The panel never shortens operator text (§8.6). The `Range` measurement of spec item 1 checks the result (item 3) |
| D32 | **Highlight request and bound.** It is §9.2's request with `"resolution": "high"` on the image block, timeout 180 s, model `gemini-nano-banana-2.1`. The bound counts prompt bytes + 512 + **2 240** image tokens at $1.50/MTok, plus **1 680 + 1 000** output tokens at **$30.00/MTok** (G11). The worst case, with `who` at 120 four-byte characters, is ≈ $0.086, so the button reads **«до $0.09»**. Settling prices every output and thought token at $30.00 | 1 120 image tokens and text at $7.50 (the first revision's sums) | The photo's token count and the split of the usage by modality are G17, unconfirmed. Charging every output token at the image rate errs on the safe side. If a reply bills more than reserved, the ledger keeps the actual (the month stays honest). LC3 measures it, and the constants change in review |
| D33 | **Gemini 4xx in Russian.** The line stays «Не удалось получить <что> от Gemini (HTTP <код>): <причина>» (B′ tests assert `HTTP 429`, `HTTP 400`; `test_author_create.py:227-231`). But `<причина>` now comes from a Russian table by status, never from the vendor. The reduced vendor message goes to one redacted panel-log line. `vendor_message` reads a JSON array as its first object (`poster/http.py:183-204`) | Showing the reduced English message (B′, `gemini.py:269-273`); a Gemini-only parser | The live test of 2026-11-13 saw «(HTTP 402): [{ "error": { "code": 402, …» on the draft page. The array fell through to the raw-body branch (`poster/http.py:203-204`), reproduced (O) with a synthetic body of that shape. Fixing the shared reducer helps every caller (`http.check`, `poster/http.py:212`, used by all four network clients). Only Google sends a top-level array, so the network clients' messages do not change |
| D34 | A failed highlight is stored as `highlight_error`, never as `error` | Reusing `error` with `op: "highlight"` | `drafts.validate` accepts only the B′ ops (`drafts.py:131`). The draft page's banner prices its retry by `bounds[error["op"]]` (`views.py:1219`), which has no `highlight` |
| D35 | A focus tap deletes the crops of every target network whose ratio is not «как у фото». The hint names those networks; with none, the hint and ring are hidden and the tile is not a button | D′'s fixed Instagram and X (`send.py:604-606`, `strings.py:459`) | With C, Facebook and LinkedIn can be cropped too. The live test of 2026-11-13 (one target, `fb:kotleta`) showed the fixed «(Instagram и X)» hint for networks that were not sent |

### 18.2 Draft fields

`draft.json` keeps every field of §7.1 and §17.2. `drafts.validate` accepts these, each
optional:

```json
{
  "base": "blur",
  "look": {"instagram": {"ratio": "1:1", "frame": "white", "quote_at": "bottom"}},
  "quotes": {"x": "Small steps, fresh angles.", "instagram": "Маленькі кроки — нові кути."},
  "who": "мужчина в синей куртке",
  "highlight_error": {"style": "glow", "text": "Gemini не вернул картинку",
                      "model_text": "…", "ts": "2026-11-13T10:05:00Z"}
}
```

- `base` is `orig` (the default when absent), `blur`, `glow` or `outline`. A style is
  accepted only while `img/<style>.jpg` exists.
- `look.<network>`:
  - `ratio` is one of that network's choices, the first being the default:
    - Instagram: `4:5`, `1:1`, `1.91:1`;
    - Facebook: `orig`, `4:5`, `1:1`, `16:9`;
    - LinkedIn: `orig`, `1.91:1`, `1:1`;
    - X: `16:9`, `orig`, `1:1`.
  - `frame` is `none` (the default), `white`, `black` or `gold` (`#e8c47c`);
  - `quote_at` is `none` (the default), `top` or `bottom`.

  An absent network has the defaults, which are D′'s crops.
- `quotes.<network>` is one line of at most 140 characters, NFC, with no line break.
  Expand writes all four (§18.5 item 4); `/settings` writes one. Text edits and regenerate
  never touch it.
- `style_rev.<style>` is 8 hex, written under `.lock` each time `img/<style>.jpg` is
  replaced. While that style is the base it joins the look digest, so a crop token or an
  in-flight crop drawn from the previous bytes answers 409 after a same-style regeneration,
  and the replaced base deletes every crop. A draft without it, and the original as base,
  keep the five-part digest.
- A generated style passes the same marker walk as the view copy and the crops
  (`jpeg_exif`): an Exif APP1 or an unreadable header answers 502, stored as
  `highlight_error`, and replaces nothing.
- `who` is at most 120 characters, saved with each highlight call and sent in its prompt.
- `highlight_error` is cleared by the next highlight success. `text` and `model_text` are
  redacted, at most 500 and 300 characters.
- Files:
  - `img/<style>.jpg` (0600, in `img/`, 0700, a real directory, not a symlink);
  - `out/<network>.jpg`, as in D′.

  «Удалить черновик» removes both, with the draft folder.
- `drafts.stage` and the «Черновики» stage words are unchanged.

### 18.3 Routes

The header checks of §14.1 and §17.3 apply unchanged. Both new POSTs go through
`_create_write`, so a sent draft answers 409 «черновик уже отправлен» (`server.py:478-479`).

| Route | Kind, limit | Does |
|---|---|---|
| `POST /create/<id>/settings` | JSON, 64 KB | Either `{base}`, or `{network, ratio?, frame?, quote_at?, quote?}`. Under `.lock` it validates by §18.2, saves, and deletes `out/<n>.jpg` for each network whose `look` digest changed: all target networks for a new base, one for a card. It answers `{base, look, missing}`. Refusals: 400 for an unknown key or value; 409 «сначала создайте этот стиль» for a base without its file; 409 «впишите цитату» for a place other than `none` with an empty quote; 409 «цитата — не больше 140 знаков» |
| `POST /create/<id>/highlight` | JSON, 64 KB | `{style, who}`: one Gemini call (§18.5 items 5–7). It answers `{style, width, height, url, month}`. Refusals are 409 (budget, key, busy), 502 (vendor or reply) and 504 (no connection or timeout), each `{error, month}` |
| `POST /create/<id>/image?…&look=<12 hex>` | image, 8 MB (D′) | D′'s checks. The ratio, the size and the «как у фото» reference come from the network's `look` and the base (item 1). `look` must equal the stored digest; absent means the default look |
| `GET /create/<id>/file?name=<n>` | image, `no-store` (D′) | `name` is one of the four networks (`out/`) or the three styles (`img/`), sniffed as JPEG, as `crop_file` does (`send.py:517-528`). Any other name answers 404 |
| `GET /create/<id>/review?style=<s>` | page (D′) | `style` picks the result shown in the right tile. By default that is the base if it is a style, else the newest result |

The POST route regex (`server.py:93`) gains `settings|highlight`. The GET regex stays
`review|status|file`.

**Security.** Each promise names the server-side check that keeps it; §18.8 tries the
hostile input.

| Threat | Server-side check | Hostile test |
|---|---|---|
| A foreign site spends on a style or changes a look | JSON kind: `Origin` required and equal to the panel's, `X-CSRF-Token` checked before any body byte (`server.py:394-419`) | `/highlight` and `/settings` with `Origin: http://evil.example`, without the token, with a wrong `Host`: 403/421; the ledger and the draft are byte-identical; the fake transport saw nothing |
| Path traversal through a style or file name | `style` and `name` only from fixed tuples; `img/` and `out/` must be real directories (D′'s `_real_dir`, `send.py:402-414`) | `name=../../.env`, `style=../x`, an `img/` symlinked to a scratch folder: 400/404/409, nothing read or written outside |
| Personal data kept by Google, or camera metadata sent | Only the view copy, checked by `gemini.image` (`gemini.py:101-114`: JPEG, no Exif APP1). `"store": false`; no file name; `who` only as prompt text. The key's project must have billing on (G10, §20 item 1) | The captured request has `"store": false`, no `name` field and the view copy's base64; an injected Exif view copy answers 409 with no request |
| Key values in pages, JSON, logs, drafts | `_json` and `_page` redact; the JSON body is redacted before use (`server.py:471`); `vendor_message` and the model's text part are redacted before storing or logging | A canary key inside a 402 array body and inside a text-only answer: in no page, JSON reply, log line, ledger row or draft |
| Spending without the operator | One call per click; reservation before sending; refusal above the cap; no retry by itself; `.ai.lock` per draft and two calls at once (`gemini.py:190-198`) | Month at $9.99: 409 and zero requests; two clicks on one draft: one request and 409 «уже выполняется»; a reload during a held call sends nothing |
| A style result published unseen | A new result changes nothing until «Взять за основу». A base change deletes every crop, so «Проблем нет» and both buttons wait for the new crops, which the review shows. `seen` covers their bytes | `/publish` with the `seen` of the page before the switch: 409 «черновик изменился после проверки — проверьте ещё раз» |

### 18.4 The review page in C (state `draft`)

Order: D′'s action block (unchanged, first), then **«Фото»**, then the cards, then
«Удалить черновик». In the other states nothing of C is shown.

**«Фото»** (`<section id="photo">`, replacing D′'s `send-source`, `views.py:1437-1443`):

1. **Heading row**: «Фото» and the status line (`role="status"`). The status line reads
   «Gemini рисует «Размыть фон»… до 3 минут» while a call runs.
2. **Two equal tiles side by side at every width** (`grid-template-columns: 1fr 1fr`, at
   most 2 × 320 px). Each tile has its label as text above a 160 px box (`object-fit:
   contain`):
   - the left tile is «Оригинал» (the view copy);
   - the right tile is the shown style («Размыть фон», «Свечение» or «Контур») from
     `/create/<id>/file?name=<s>`. With no result it reads «Здесь появится фото со стилем —
     выберите стиль ниже».

   Under the base tile stands the word «основа»; under the other, when it holds an image,
   «Взять за основу». Under the right tile with a result is «Заново · до $0.09».
   The focus ring and tap sit on the base tile only (D35).

   The base is always one of the two tiles. When the base is a style and `?style=` shows
   another result, the base takes the left tile (name, «основа», focus ring, no «Заново»)
   and the original is a chip «Оригинал» (a link to `?style=<base>#photo`, the plain pair
   again); then «Взять за основу» stands under the right tile only.
3. **Style chips**: one chip for each of «Размыть фон», «Свечение» and «Контур» except
   the styles the tiles show, which their labels already name.
   - A style with a result is a link to `?style=<s>#photo`.
   - A style without a result is a button «Свечение — создать · до $0.09» that spends
     (§18.5 item 5).
4. **«Кто главный на фото (необязательно)»**: one input, at most 120 characters, with the
   placeholder «например: мужчина в синей куртке». Its value is saved with the next call.
5. **Notices** (`role="alert"`, at most one line each):
   - no key: «нет GEMINI_API_KEY в .env — стили фото недоступны»;
   - the budget refusal «Бюджет ИИ на ноябрь исчерпан: «Стиль фото» стоит до $0.09. …»;
   - the stored `highlight_error` as ««Свечение»: <text>» (the failed style named once)
     with «Повторить · до $0.09». A text-only answer adds the line «Ответ Gemini:
     «<model_text>»». While it shows, no other button starts that style's call: its chip
     and its «Заново» step aside for «Повторить».

   With no key or past the cap, the spending chips are disabled and carry the reason in
   `title`. The «Создать» pages' `_author_state` is unchanged (`views.py:1080-1097`), so
   no B′ page gains a highlight notice.
6. **Focus hint**: «Нажмите на фото-основу, чтобы сдвинуть центр кадра (Instagram и X)».
   It names the cropped target networks by `S.names_and`.

**Card controls** (state `draft`, on every card under the size line):

- One wrapping row of three label-and-select pairs, each pair unbreakable:
  - «Кадр»: «как у фото», «4:5», «1:1», «1.91:1», «16:9», as the network allows;
  - «Рамка»: «нет», «белая», «чёрная», «золотая»;
  - «Цитата»: «нет», «внизу», «вверху».
- While «Цитата» is not «нет», a second row: «Текст цитаты» (input, at most 140, the
  stored quote or empty) and «Применить».
- A «Кадр» or «Рамка» change posts `/settings` at once. A «Цитата» change posts at once
  only when a quote is stored; otherwise it opens the second row, and «Применить» posts
  the place and the text together. «Применить» posts an edited quote. The reply reloads the
  page, which re-makes the crop.
- While the crop line runs or a POST is in flight, every C control and «Взять за основу»
  is disabled and keeps its width (D30's race).

**Template drawing** (`author.js`, after the crop is drawn, on the same canvas):

- **Frame**: four filled rectangles inside the edges, `f = max(16, round(0.025 × short
  side))` px wide, in `#ffffff`, `#000000` or `#e8c47c`. The output size never changes.
- **Quote band**: `rgba(0, 0, 0, 0.6)`, inside the frame, across the inner width.
  - Its centre is the middle of the top or bottom third of the area inside the frame,
    clamped inside it.
  - The text is white `600` `system-ui, sans-serif`, line height 1.25, with padding of
    0.5 em, centred.
  - Line width is at most min(0.86 W, inner width − 2 × padding), and there are at most
    4 lines (D31).
- `MFAuthor.layoutTemplate(W, H, frame, quote)` returns `{inset, band: [x, y, w, h],
  font, lines: [{text, x, y, w}], fits}`. `makeCrop` draws from it, and `send.js` records
  it in `MFSend.results` for the probe.
- A word longer than the line is broken between characters; nothing else changes the
  text.
- With `frame` `none` and no quote, `makeCrop` runs D′'s path unchanged.
- A quote that does not fit fails the crop through D′'s `failed()` (`send.js:85-96`):
  «Не удалось подготовить картинку для Instagram: цитата не помещается в 4 строки —
  сократите». A ratio whose k is 0 fails the same way: «фото слишком маленькое для 1.91:1».

**Source of every crop:** `D.source`. This is `/photo?…&v=orig` for the base `orig`
(`views.py:1481`), or `/create/<id>/file?name=<style>`. It replaces `D.orig`
(`send.js:108`).

### 18.5 Acceptance list

Each item is observable by a test, a probe or a screenshot named in §18.6–§18.8. The
specification's items map as follows:

| Specification item | Acceptance items |
|---|---|
| 1 (frame and quote fit, `Range`) | 3 |
| 2 (fake image stored and shown; text-only answer) | 5, 6 |
| 3 (base redraws every preview, re-posts every crop) | 8 |
| 4 (exact sizes, `check_image`) | 1 |
| 5 (budget guard, bound on every button) | 7 |
| 6 (errors in Russian, never raw JSON; the `vendor_message` fix and its test) | 9 |
| 7 (A, B′ and D′ tests; visual check) | 12, 13 |
| Fences (fake Gemini only, no spend) | 14 |
| This design's own | 2, 4, 10, 11 |

1. **Ratio choices and sizes.**
   - `send.crop_size(network, ratio, W, H)` and `MFAuthor.cropSize(network, ratio, W, H)`
     agree. The probe compares the browser's values with this table, and the test compares
     Python's:

     | Network | Choice | 3 024 × 4 032 | 320 × 240 | style 1 536 × 2 048 |
     |---|---|---|---|---|
     | Instagram | 4:5 (default) | 1 080 × 1 350 | 192 × 240 | 1 080 × 1 350 |
     | Instagram | 1:1 | 1 080 × 1 080 | 240 × 240 | 1 080 × 1 080 |
     | Instagram | 1.91:1 | 955 × 500 | 191 × 100 | 955 × 500 |
     | Facebook | как у фото (default) | 1 536 × 2 048 | 320 × 240 | 1 536 × 2 048 |
     | Facebook | 4:5 | 1 636 × 2 045 | 192 × 240 | 1 536 × 1 920 |
     | Facebook | 1:1 | 2 048 × 2 048 | 240 × 240 | 1 536 × 1 536 |
     | Facebook | 16:9 | 2 048 × 1 152 | 320 × 180 | 1 536 × 864 |
     | LinkedIn | как у фото (default) | 1 536 × 2 048 | 320 × 240 | 1 536 × 2 048 |
     | LinkedIn | 1.91:1 | 1 910 × 1 000 | 191 × 100 | 1 528 × 800 |
     | LinkedIn | 1:1 | 2 048 × 2 048 | 240 × 240 | 1 536 × 1 536 |
     | X | 16:9 (default) | 1 600 × 900 | 320 × 180 | 1 536 × 864 |
     | X | как у фото | 1 200 × 1 600 | 320 × 240 | 1 200 × 1 600 |
     | X | 1:1 | 1 600 × 1 600 | 240 × 240 | 1 536 × 1 536 |

   - Every crop the page makes for the first and third columns sniffs as JPEG.
     `check_image(network, sniff(path))` returns no error, and the marker walk finds no
     `Exif` APP1.
   - `POST /image` refuses, with 409 and nothing written:
     - a crop whose ratio is not the look's;
     - a fixed ratio over its cap box;
     - a «как у фото» crop more than 1 % off the base's ratio. The base is the view copy's
       index size for `orig` (`send.py:530-539`) and the sniffed `img/<style>.jpg` for a
       style;
     - a «как у фото» crop whose long side is over its cap or under min(cap, the base's
       long side).
2. **Settings and redraw.**
   - A card's select change posts `/settings`. The stored `look` changes, and only that
     network's `out/` file is deleted: the other three keep their mtime.
   - The page reloads, makes one crop (one `/image` POST) and reloads once more.
   - A crop posted with the previous `look` digest answers 409 «кадр изменился — обновите
     страницу».
   - Unknown keys or values answer 400, and a sent draft answers 409. In each case nothing
     is written.
   - While a crop, settings or highlight request runs, the saved-style links are as inert as
     the buttons: dimmed, out of the tab order (`aria-disabled`), no navigation; their width
     is unchanged and they come back afterwards.
3. **Frame and quote fit, measured with a `Range`** (spec item 1). The `review-template`
   probe covers the four networks' template crops and runs `layoutTemplate` on every size of
   item 1's first column. It uses four quotes: a short Russian one, 140 Russian
   characters, 140 × «а» with no space, and an English one. Every one fits on every size. It
   reports:
   - **numerically:** `lines.length ≤ 4`; each line's `measureText` width ≤ min(0.86 W,
     inner width − 2 × padding); the band inside `[f, W − f] × [f, H − f]`; the font at
     least max(10, 0.025 W);
   - **with a `Range`:** the probe lays the returned lines out as DOM text at the same
     coordinates and font in a W × H box (`white-space: pre`, one absolutely positioned
     span per line). For each line it reads `Range.getClientRects()` over its text node:
     exactly one rect, lying inside the band, and the band inside the box minus the frame.
     The count of line rects is the quote's line count, at most 4;
   - **in the pixels:** the probe draws one crop with each of the three frame colours and
     decodes the JPEGs. In each, the pixel at (f/2, f/2) is within 12 of that colour per
     channel, so the frame is drawn inside the image;
   - **at the limit:** a 140-character quote on a 191 × 100 crop gives `fits: false`. The
     crop line shows «Не удалось подготовить картинку для Instagram: цитата не помещается
     в 4 строки — сократите», and no `/image` POST is sent.
4. **Quotes from «Развернуть».**
   - The expand schema gains a required `quotes` object with the four network keys
     (`prompts.py:35`). The prompt asks for one line per network, at most 90 characters,
     in that network's language, with no hashtags or links.
   - The captured request equals `prompts.SCHEMAS["expand"]`. `draft.json` `quotes` holds
     the four lines, NFC.
   - A reply without `quotes` is still accepted and stores none. B′'s
     `test_steps_last_output_and_output_text` sends one (`test_author_gemini.py:39-40`).
     Any other extra key stays invalid (`:53`).
   - A quote over 140 characters or with a line break is not stored; the texts are.
   - Regenerate and text edits leave `quotes` byte-identical.
   - An expand that changes the quote of a network whose `quote_at` is not `none` deletes
     that network's crop.
   - «Развернуть · до $0.05» is unchanged. The worst-case bound with the schema and prompt
     lines added is $0.0403 now and $0.0807 from 2027-01-01, so the buttons stay $0.05 and
     $0.09 (O, `budget.bound` on 2026-11-13).
5. **A style result** (spec items 2 and 5).
   - «Размыть фон — создать · до $0.09» posts `/create/<id>/highlight` `{style: "blur",
     who}`.
   - The fake transport receives exactly one request. Its URL and headers are §8.4's,
     `model` is `gemini-nano-banana-2.1` and `store` is false.
   - The input is the style instruction of §9.2 + «The main person is the most prominent
     person in the photo.» + the `who` line when given + «Do not add text, logos or other
     people.», then the view copy's base64 with `"resolution": "high"`.
   - `response_format` is `{"type": "image", "mime_type": "image/jpeg", "aspect_ratio":
     "3:4", "image_size": "2K"}`. 3:4 is the nearest of §9.2's list to the fixture's 3:4
     view copy (nearest by |log r − log c|).
   - When the fake is called, the ledger's last row is `reserved` with `op: "highlight"`
     and `price` equal to the reserved bound. After it there is one `ok` row priced by D32.
   - The fake's 1 536 × 2 048 JPEG is stored as `img/blur.jpg` (0600, `img/` 0700) and
     served by `/file?name=blur`.
   - The page shows it in the right tile beside «Оригинал». Both images are loaded, the
     tiles share a top and have equal widths (±1 px) at all ten widths, and the sub row's
     month changes to the reply's `month`.
   - `who` is saved in `draft.json`.
6. **No image in the answer** (spec item 2).
   - A completed reply with only a text block shows «Gemini не вернул картинку», «Ответ
     Gemini: «<text>»» and «Повторить · до $0.09». After a reload it is shown again from
     `highlight_error`.
   - It settles `ok` at the reported usage, and nothing is written under `img/`.
   - An image block that is not a JPEG by sniffing gives «Gemini вернул картинку не в JPEG
     — повторите». One over 8 MB decoded gives «Gemini вернул слишком большую картинку —
     повторите». Both settle `ok`.
   - `incomplete` and `failed` replies give §8.4's messages.
   - A result arriving after the draft was sent is not stored, and the answer is 409
     «черновик уже отправлен».
7. **Every Gemini call is guarded and priced on its button** (spec item 5).
   - Every spending control shows its bound as text: the three create chips, «Создать
     заново», «Повторить», and B′'s four.
   - `budget.button("highlight")` is at least `budget.bound` for every style with `who` at
     120 four-byte characters, and reads $0.09.
   - With the month at $9.99, the chips are disabled, «Бюджет ИИ на ноябрь исчерпан:
     «Стиль фото» стоит до $0.09. …» shows once, and a forced POST answers 409 with that
     text. The transport sees zero requests.
   - With no key: «нет GEMINI_API_KEY в .env — стили фото недоступны» and zero requests.
   - Two concurrent clicks on one draft give one request and 409 «уже выполняется». A
     third concurrent AI call across drafts gives 409 «ИИ занят двумя запросами —
     подождите».
   - A 503 settles `unknown`, and the reservation counts. A timeout settles `unknown` (504).
     A 402 settles `failed` and counts 0 (every 4xx, `gemini.py:263`; §11.1 lists six codes,
     and the code governs).
   - A test wraps the fake transport for every op (topics, expand, regenerate, voice,
     highlight). Each request finds a `reserved` row of its op written after the previous
     request; none is sent without one.
8. **«Взять за основу» redraws everything** (spec item 3). On a draft with `img/blur.jpg`
   and D′'s crops:
   - «Взять за основу» under «Размыть фон» posts `/settings` `{base: "blur"}` once. All
     four `out/` files are deleted.
   - The page reloads, fetches `/create/<id>/file?name=blur` as the source and posts four
     crops, then reloads once more.
   - All four files differ from before (SHA-256) and have the third column's sizes of item
     1. Every card's `<img>` shows the new bytes. «основа» stands under «Размыть фон», and
     «Проблем нет · 4 сети» returns.
   - «Взять за основу» under «Оригинал» goes back the same way.
   - A crop posted from the old base answers 409. While the four crops are being made, the
     strip and the card controls are disabled.
   - A new result for the base style («Заново») also deletes all four crops.
9. **Gemini errors in Russian, never raw JSON** (spec item 6).
   - `vendor_message(Response(402, {}, b'[{"error": {"code": 402, "message": "x"}}]'))`
     returns «x; code 402». An empty array or an array of non-objects falls back as today.
     An object body gives the same answer as before (test `VendorMessageTest`).
   - The 4xx reason table is:

     | Status | `<причина>` |
     |---|---|
     | 400 | «Gemini не принял запрос — подробности в журнале панели» |
     | 401, 403 | «ключ GEMINI_API_KEY не принят — проверьте ключ и доступ к Gemini API» |
     | 402 | «закончились предоплаченные кредиты Gemini — пополните баланс в Google AI Studio» |
     | 404 | «модель недоступна для этого ключа» |
     | 413 | «запрос слишком большой» |
     | 429 | «Gemini просит подождать — повторите позже» |
     | other 4xx | «Gemini отклонил запрос — подробности в журнале панели» |

     `<что>` is B′'s word (`gemini.py:25`) or «картинку» for a highlight. 5xx and transport
     errors keep B′'s lines.
   - A fake 402 with the array body gives «Не удалось получить тексты от Gemini (HTTP 402):
     закончились предоплаченные кредиты Gemini — пополните баланс в Google AI Studio» on
     expand (on the draft page), and the same line with «картинку» on a highlight (on the
     review page).
   - The page's visible text, the JSON `error`, and the stored `error.text` and
     `highlight_error.text` contain none of `[{`, `{"`, `"error"` or `prepayment`.
   - The panel log has exactly one redacted line, «panel: gemini <op> HTTP 402: <reduced
     message>».
   - B′'s `test_vendor_failure_settlement_stored_error_redaction_and_retry` passes
     unchanged.
10. **Focus with C's ratios.**
    - With Facebook at 4:5, a tap deletes the Instagram, Facebook and X crops, and
      LinkedIn's keeps its mtime. The hint reads «… (Instagram, Facebook и X)».
    - With every target at «как у фото» (for example `targets=("fb:kotleta",)`), the hint
      and ring are absent, and the base tile is an `<img>`, not a button.
11. **Storage.**
    - Draft fields outside §18.2 are refused by `validate`.
    - `img/` and `out/` symlinked to a scratch folder are refused, with nothing written
      there.
    - «Удалить черновик» removes `img/`.
    - No GET writes (hashes of `content/` before and after every C state's GETs).
    - `git check-ignore content/drafts/d/img/blur.jpg` holds.
12. **D′ unchanged by default.**
    - A draft with no C field makes byte-identical crops through the default path and
      through `makeCrop` with `frame: "none"` and no quote (probe, same bitmap).
    - Every D′ test in `tests/test_author_send.py` passes unchanged; that file is not
      edited (another lane changes it).
    - D′'s visual states and their defining text pass. The package format, publish, queue,
      retry, status and delete are unchanged.
13. **Checks.**
    - `python3 -I -B -m unittest discover -s tests -t .` passes, with HOME and TMPDIR
      outside the checkout.
    - `python3 tools/visual_check.py --out DIR` passes every state of §16.2, §17.6 and §18.6
      at all ten widths.
    - `git status --short --ignored` in the worktree shows nothing new after both.
14. **No real call, no spend.**
    - Every Gemini request in tests and in the visual check goes to `FakeTransport` or
      `FakeGemini`, and `tests/base.py`'s guard sees no other connection.
    - No stage reads a real key: fixtures carry the canary env.
    - LC3 is not run (§18.9).
    - The X ledger, the poster record, `content/packages/` and the stock are unchanged by C
      (hashes), except through D′'s own publish and queue states.

### 18.6 UI states and widths for the visual critic

Every state runs in `tools/visual_check.py` at the ten widths (390, 900, 1000, 1100, 1200,
1279, 1280, 1440, 1600, 1920) with the probe's existing checks: cut text, sideways scroll,
overlaps, targets under 24 × 24, an alert below the first screen, and contrast. The
panel ships one theme, dark (`color-scheme: dark`, `panel.css:32`), and Russian UI.

The visual critic frames each state at **390, 900, 1440 and 1920**, as in §17.6. Each state
is defined by visible text that must be whole on the first screen at every width (measured
with a `Range`). The C states load with `#photo`, or with `#send-cards-h` for the card
states, because D′'s action block comes first and fills a 390 px screen. Cards are judged
scrolled until each is whole.

**Measurement** (2026-11-13, O): `main` at `4dd221f`, Chrome for Testing 156.0.8078.4
headless shell at device scale 1, the «send» fixture's `ready` review page. Placeholders
were injected for the card row (the three pairs with their longest options) and the chip row
(four labels, «Оригинал» and the three create chips, one more than C shows):

| Viewport | Card columns | Card inner width | Card row lines | Chip row lines |
|---|---|---|---|---|
| 390 | 1 | 340 px | 2 | 3 (widest chip 262 px) |
| 900 | 2 | 400 | 2 | 1 |
| 1 000 | 3 | 286 | 2 | 1 |
| 1 100 | 3 | 319 | 2 | 1 |
| 1 200 | 4 | 254 | 3 | 1 |
| 1 279, 1 280, 1 440, 1 600, 1 920 | 4 | 272 | 3 | 1 |

The pairs measured 143, 131 and 132 px. No pair or chip overflowed its box, and no page
scrolled sideways. The narrowest card (254 px at 1 200) holds one pair per line. The quote
row (a text input that shrinks beside «Применить») was not measured; `review-template`
measures it.

Three fixtures carry the states, separate from B′'s and D′'s, so their states and counts
stay as they are. FakeGemini runs in process:

- **«images»** (static): `my-photos` with the 3 024 × 4 032 photo, and these drafts:
  - `plain` (four texts, D′ crops, no style);
  - `styled` (as `plain`, plus `img/blur.jpg` 1 536 × 2 048 and four quotes);
  - `based` (base `blur`, crops at the third column's sizes).

  Variants of the fixture: `ledger_usd=9.99`, and `key=False`.
- **«images-live»**: per width, one draft for each state that changes a draft or holds a
  call. They are `tpl`, `ratio`, `hold`, `hl`, `text`, `e402`, `base` and `x402`. FakeGemini
  answers each by its draft: a 1 536 × 2 048 JPEG, a held call, a text-only answer, or a
  402 with the array body.

| State | Setup | Defining text on the first screen |
|---|---|---|
| `review-styles-empty` | «images», `plain`, `#photo` | «Фото», «Оригинал», «основа», «Здесь появится фото со стилем — выберите стиль ниже», «Размыть фон — создать · до $0.09», «Свечение — создать · до $0.09», «Контур — создать · до $0.09», «Кто главный на фото (необязательно)» |
| `review-styles` | «images», `styled`, `?style=blur#photo` | «Оригинал» with «основа», «Размыть фон» with «Взять за основу» and «Заново · до $0.09», the chips «Свечение — создать · до $0.09» and «Контур — создать · до $0.09» (no chip repeats the shown style) |
| `review-based` | «images», `based`, `#photo` | «основа» under «Размыть фон», «Взять за основу» under «Оригинал», «Нажмите на фото-основу, чтобы сдвинуть центр кадра (Instagram и X)» |
| `review-template` | «images-live», `tpl-<w>`. Four quotes stored. Looks: Instagram 1:1, white frame, quote at the bottom; X 1:1, black frame, quote at the top; LinkedIn 1.91:1, gold frame; Facebook 16:9, quote at the bottom. No crops stored, so the page makes them. `#send-cards-h` after the reload | The selected options («1:1», «белая», «внизу», «1.91:1», «золотая», «16:9»), the quote inputs, and the size lines «1 080 × 1 080», «1 600 × 1 600», «1 910 × 1 000», «2 048 × 1 152». Probe JSON: item 3 |
| `review-ratio` (functional) | «images-live», `ratio-<w>`: the probe changes each select through the UI in turn and waits for each redraw | Probe JSON: every choice's size equals item 1's first column, and every `/image` answered 200 |
| `review-highlight-loading` | «images-live», `hold-<w>`, `#photo`: the probe clicks «Размыть фон — создать · до $0.09»; FakeGemini holds until teardown | «Gemini рисует «Размыть фон»… до 3 минут»; the chips, «Взять за основу» and the card controls dimmed and disabled |
| `review-highlight` | «images-live», `hl-<w>`: the probe clicks; the fake answers the JPEG | «Размыть фон» tile with its image beside «Оригинал», «Взять за основу». Probe JSON: item 5 |
| `review-highlight-text` | «images-live», `text-<w>`: the probe clicks; text-only answer | ««Размыть фон»: Gemini не вернул картинку», «Ответ Gemini: «…»», «Повторить · до $0.09»; one button for `blur` |
| `review-highlight-402` | «images-live», `e402-<w>`: the probe clicks; 402 array | ««Размыть фон»: Не удалось получить картинку от Gemini (HTTP 402): закончились предоплаченные кредиты Gemini — пополните баланс в Google AI Studio». Probe: none of item 9's raw fragments in `document.body.innerText` |
| `create-error-402` | «images-live», `x402-<w>`: the draft page with a topic; the probe clicks «Развернуть · до $0.05»; 402 array | The same line with «тексты», and «Повторить · до $0.05» (the live test's surface) |
| `review-base` (functional, then framed) | «images-live», `base-<w>`: the probe clicks «Взять за основу» under «Размыть фон» | Probe JSON: item 8 (one `/settings`, four `/image`, two reloads, four new hashes, X 1 536 × 864). Frame: «основа» under «Размыть фон», «Проблем нет · 4 сети» |
| `review-based-other` | «images», `based` (also holds a «Свечение» result), `?style=glow#photo` | «основа» under «Размыть фон» (the left tile, with the focus ring), «Взять за основу» under «Свечение» only, the chip «Оригинал» |
| `review-styles-budget` | «images» with the ledger at $9.99, `plain`, `#photo` | «Бюджет ИИ на ноябрь исчерпан: «Стиль фото» стоит до $0.09. …» once; the red «ИИ · ноябрь $9.99 из $10.00 · лимит»; the chips disabled |
| `review-styles-nokey` | «images» without the key, `styled`, `#photo` | «нет GEMINI_API_KEY в .env — стили фото недоступны»; the chips disabled; «Взять за основу» still enabled |

The critic also checks that:

- the two tiles stand side by side with equal widths at every width;
- no tile label, chip, select or quote input is cut (`scrollWidth` against `clientWidth`,
  and `Range` rects for the labels);
- disabled controls keep their width and look disabled;
- «основа» and the loading and error lines are words, not colour only;
- neither the 160 px tiles nor the 240 px crop boxes shift the layout when an image
  arrives;
- the sticky bar never covers the defining text from 900 px up (the anchor jump uses the
  existing `scroll-padding-top`).

### 18.7 Not touched

- `poster/**`, except `vendor_message` reading an array (D33) and its test. Its other
  callers (`http.check`) keep their output for every object body.
- The factory core and `factory/panel/actions.py`.
- B′:
  - routes, prompts, budget and ledger, except the expand schema's `quotes` (item 4) and
    the 4xx reason (item 9);
  - the draft page's layout and the «Создать» page. `_author_state` and `_create_notice`
    are unchanged.
- D′:
  - the package format, publish, retry, queue with the offered rule, delete, status, the
    dialogs and `seen`;
  - the crop route, except the ratio, base and `look` checks;
  - `tests/test_author_send.py`, which is not edited (another open lane changes its
    `test_partial_then_retry_only_the_failed_targets`).
- `.env`, `KEYS.md` and `KEYS.local.md`. There is no new key; `GEMINI_API_KEY` and
  `AI_MONTHLY_CAP_USD` are reused.
- The CSP: style images are same-origin `<img>` and canvas sources. No new dependency, no
  Anthropic code, no new vendor.
- The operator's running panel on port 8770 and the primary checkout. No real Gemini call,
  no publishing, no paid API in any stage of this lane.

### 18.8 Test plan and mocks

No test opens a non-loopback socket (`tests/base.py` guard).

| File | Covers (items) | Mocks |
|---|---|---|
| `tests/test_author_images.py` (*new*) | Item 1's table through `crop_size` and `check_image` on `make_photo` crops; the crop route's ratio, base and `look` checks (1). The settings route over `http.client` on port 0 with the header checks and the hostile input of §18.3 (2, 11). Expand with and without `quotes` (4). The highlight route: request shape, reserve before send, the `ok` row, the file and its route, text-only, non-JPEG, oversize, `incomplete`, a result after sending (5, 6). Budget, key, concurrency, 503, timeout and 402 settlements, and the reserve-before-every-request wrapper over all five ops (7). Base switch deletions and the stale-crop 409 (8). `VendorMessageTest`, and the Russian lines on expand and highlight with the log line and canaries (9). Focus deletions and the hint (10). Validation and storage (11) | `server.make_server(..., ai_transport=FakeTransport)`; `FakeGemini` |
| `tests/panel_fixture.py` | `build_images(root, *, key=True, ledger_usd=None, live_widths=())`. `FakeGemini` answers requests whose `response_format.type` is `image` by draft: a fixed-seed `make_photo(1536, 2048)` JPEG, text only, PNG, a 402 with `[{"error": {"code": 402, "message": "Your prepayment credits are depleted.", "status": "RESOURCE_EXHAUSTED"}}]`, or a hold. All of these are synthetic, not vendor observations | — |
| `tools/visual_check.py`, `static/probe.js` | The states of §18.6, with their probe JSON checks (1, 3, 5, 8, 9, 10) | The in-process `FakeGemini` |
| Existing B′ and D′ tests | Unchanged and passing (12) | — |

The project's checks run as `AGENTS.md` and `README.md` give them, one at a time through the
gate wrapper. A page-body assertion on status digits strips the panel's random CSRF token
first, as the other lane's `assertNoPosterWords` helper does (the token can contain
«402»).

### 18.9 LC3, after the merge (not in this lane)

LC3 (§19) settles G17: the photo's token count on the image model, the full `aspect_ratio`
list, the place of the image block in the reply, and whether the operator's face is kept.

- It needs the operator's photo, their go-ahead and Gemini credits. The shared key
  answered 402 «prepayment credits are depleted» on 2026-11-13 around 16:2x UTC.
- It is one «Размыть фон» through the review page, bounded at $0.09.
- The report gives the `usage` numbers against D32's bound, and the operator's verdict on
  the face. If the face is changed or refused, §21's code "spotlight" is the fallback.

No stage of this lane makes a real Gemini call.

### 18.10 What was cut from C, and where it went

| Cut | Goes to | Why it can wait |
|---|---|---|
| The strip and chips on the draft page (§9.3) | Review page (D27) | The crops and focus already live there; the draft page's first screen is measured and full |
| An «Оригинал» chip in the chip row (§9.3) | Dropped | The left tile always shows the original |
| Instagram 1.91:1 at 1 080 × 566 | §21 | Not an exact ratio; 955 × 500 is (D28) |
| Showing the vendor's English reason on the page | §21 (the panel log keeps it) | Spec item 6: Russian, never raw JSON (D33) |
| Per-modality settlement of image tokens | §21 | The usage fields are G17; every output token is charged at the image rate meanwhile (D32) |
| A different base per network; several kept results per style; drag-to-place a quote; custom colours and fonts | §21 | Not asked; one base, three frame colours and two quote places cover the decision of 2026-11-08 |

## 19. Unconfirmed facts and live checks

Every live check needs the operator's OK. B′'s LC1 is pre-approved by the pinned
specification within its limits.

| Id | Settles | Cheapest check | Cost |
|---|---|---|---|
| LC1 | G12–G16; the reply shape and `usage` on the real key; the typical costs of §11.2 | Below | < $0.10, at most 6 calls |
| LC2 | Merged into LC1 on 2026-11-12 (transcription now runs on a public-domain clip) | — | — |
| LC3 | G17; the image block's place in the reply; the real `usage` against D32's bound | After C's merge, with the operator's photo, go-ahead and Gemini credits (the key answered 402 on 2026-11-13): one «Размыть фон» on a photo of the operator at 2K through the review page. If `aspect_ratio` is refused, drop the field. If Gemini refuses or changes the face, build the code "spotlight" of §21 (§18.9) | bound $0.09, typical ≈ $0.06 |
| LC4 | The panel's publish path end to end with the real poster (D′) | After the merge and the operator's go-ahead: one photo post from the review page to the main profile's Facebook Page only, then `python3 -m poster delete` (§17.9) | free |
| LC5 | B6; folder upload and the microphone from Windows; transcription of the operator's own voice | The operator opens `http://localhost:8770/` after the merge, drops two phone photos on «Создать», and dictates a topic | ≈ $0.002 |

**LC1 (slice B′):**

- **Inputs** (never the operator's photos or voice):
  - a public-domain or CC0 photograph without people, such as a street or landscape from
    Wikimedia Commons;
  - a public-domain spoken clip of at most 10 seconds in Russian or Ukrainian, OGG/Opus
    or WebM, from Wikimedia Commons.

  Both are stored in the lane's scratch folder only, and their licences are recorded in
  the report.
- **Setup:**
  - The panel runs in-process on port 0 with the real `UrllibTransport`.
  - The env file is the repository's, read in place, never copied or printed.
  - `MF_CONTENT_DIR` is a scratch folder.
  - The factory state is the operator's default, so the rows land in the real ledger and
    the month total stays honest.
  - The photo is uploaded through `/files/photos` into `my-photos`, as the browser does
    (copies made by the probe).
  - A short test profile (about 5 lines, no personal data) is saved through
    `/create/profile`.
- **Calls,** through the panel's own routes:
  1. topics;
  2. expand on the first topic;
  3. regenerate X with «короче»;
  4. voice with the clip.

  Two more calls are allowed only to retry a shape failure after its reply was read and
  the code adjusted. Examples: `v1beta` with `Api-Revision` refused → `v1` (G12); text not
  found in `steps` → `output_text` (G13).
- **Guard:** the driver adds up the reserved bounds and stops before the sum would pass
  $0.10. With a short profile the four planned calls bound to about $0.06.
- **Report**, per call:
  - op, model, HTTP status, interaction `status`;
  - the `usage` numbers, and whether `total_tokens` equals input + output + thought (G14);
  - reserved bound, settled price, ledger `rid`;
  - which parse path found the text;
  - the four texts and the transcript, which are not personal.

  Also the month total before and after. The key, and the image or audio bytes, never
  appear.

If B6 fails (the panel is reached by a WSL address), voice stays off with its message and
the rest works.

## 20. Open items for the operator (non-blocking)

1. **Gemini billing.** The key's Google Cloud project has, or will have, an active billing
   account (answered 2026-11-12). Until then, photos and voice fall under the unpaid
   terms (G10). LC1 uses non-personal inputs, so it does not depend on this.
2. **Profile.** About 5–10 lines in «Профиль автора» after B′ is merged.
3. **Cap.** `AI_MONTHLY_CAP_USD` stays at the decided 10.00 unless the operator changes
   it.
4. **LC3 photo and verdict** (C), and **the go-ahead and the Page for LC4** (D′). The
   default Page is the main profile's Facebook Page, the one the operator chose for the
   factory's live schedule test. The post is deleted at once, and the other networks are
   untouched (§17.9).
5. **Gemini credits.** The shared key answered 402 «prepayment credits are depleted» on
   2026-11-13 around 16:2x UTC. Until the credits are topped up, topics, texts, voice and
   C's styles answer with C's Russian 402 line (§18.5 item 9), and LC3 cannot run. A
   «highlight me» photo goes to Google, so the billing of item 1 applies to it too.

No question here changes the design; each has a default above.

## 21. Deferred — not currently justified

| Item | Why deferred | Trigger to build |
|---|---|---|
| Code "spotlight" highlight (darken or blur outside an oval the operator places) | The operator chose Gemini for highlighting | LC3 shows a refusal or a changed face |
| Drag-to-crop | One click for the focus point plus ratio choices covers the crops | Operator asks for finer crops |
| Another Gemini text model (`gemini-4-hydrogen`) or a model picker | 3.8 Flash costs about $0.02 a post, is stable, and is the report's choice (D7) | A deprecation notice for 3.8 Flash, poor texts in LC1 or use, or the operator asks |
| Claude (Anthropic API) for texts | Removed by the operator's decision of 2026-11-12; no Anthropic key in this project | None |
| `gemini-3.5-transcribe` | Needs a Files API upload first; Flash-Lite takes inline audio | Poor transcripts of mixed Russian and Ukrainian |
| Generating all highlight styles at once | Spends on results nobody asked for | Operator asks |
| Audio playback before transcription; keeping recordings | The transcript is what gets checked; recordings are personal data | Operator asks |
| Both-language variants (`en+uk`) and per-network on/off switches | Languages are fixed by the decisions; all four networks are wanted | Operator asks |
| Profile that learns from repeated edits (the research's "self-updating profile") | Needs a rule for what counts as repeated; the operator can edit the profile | Operator asks, or the same edit recurs in many drafts |
| Topics from trends (Google Search grounding) | Topics from the photo and profile answer "suggest a topic" | Operator asks for trend topics |
| Text-only posts | The operator starts from photos; Instagram needs an image | Operator asks |
| HEIC decoding | No decoder in the browser on Windows or in the standard library | Operator's phone cannot export JPEG |
| Several photos per post, carousels | The poster publishes one image per network | Poster gains carousels |
| Video (topic → recording → automatic edit → Reels and Shorts) | A separate task in the research plan, with its own probe and design | That task's design |
| Alt text | Not asked; the poster does not send it (`poster.md` §17) | Operator asks |
| "Publish at a chosen time" for one post | The queue and the rules cover scheduling | Operator asks |
| "Next in queue" placement | File order decides; reordering is deferred in `factory.md` §18 | Frequent reordering |
| Editing queued packages in the panel | Approval happens on the review page | Operator asks |
| Batch generation for a whole folder | AGENTS rule 1: no bulk paid generation without a confirmed budget | Operator confirms a batch budget |
| Prompt caching, Files APIs | Small prompts, one photo per call | Larger prompts or many photos per call |
| Price overrides in the env file | Prices come from official pages with dates; a change is a code change | Prices change often |
| Server-side image processing | Needs pip or a system tool | A dependency is accepted |
| No-JS authoring beyond the profile form; multipart parsing | The steps need JS (D9) | — |
| AI key state on the Connection tab | Its state shows where it is used («Создать») | Operator asks |
| A CLI for the AI ledger | The «Создать» sub row shows the month | The ledger needs auditing outside the panel |
| An attention-bell item for an interrupted publish (D′) | «прервано — проверьте аккаунт» shows on the review page and in «Черновики» on `/create`, the panel's first page | An interrupted publish goes unnoticed |
| Re-publishing an interrupted or `unknown` target from the panel (D′) | The poster may have sent it; a second post is the worse outcome. `python3 -m poster publish … --force-target T` covers the rare case | The first interrupted publish, or the operator asks |
| Per-network switches on the review page; queuing despite publish-time problems (X month, LinkedIn token) (D′) | The specification blocks both buttons on any problem (D26); the runner already skips X over budget for queued posts | A problem on one network blocks a post the operator wants on the others |
| Editing texts after a partial publish (D′) | A sent draft is read-only; retry and delete cover it | Operator asks |
| Face-aware automatic crop (D′) | No detector in the standard library; Gemini is outside D′. A centre crop plus one tap covers it | Centre crops cut heads often enough that the operator taps on most posts |
| Instagram 1.91:1 at 1 080 × 566 (C) | Not an exact ratio; 955 × 500 is exactly 1.91 and passes the poster's check (D28) | The operator finds 1.91:1 posts soft on Instagram |
| The vendor's English reason on the page (C) | Spec item 6: errors in Russian, never raw JSON; the reason table covers the documented statuses, and the panel log keeps the reduced message (D33) | A 4xx worded «Gemini не принял запрос» or «Gemini отклонил запрос» recurs and the log is not enough |
| Per-modality settlement of image-model tokens (C) | The usage fields per modality are unconfirmed (G17); charging every output token at the image rate errs on the safe side (D32) | LC3 shows the fields |
| A different base per network; several kept results per style; drag-to-place a quote; custom frame colours, fonts or quote places (C) | One base, three colours and two places cover the decision of 2026-11-08 | Operator asks |
| Style controls on the draft page (C) | The crops, the focus and the previews live on the review page (D27) | Operator asks to style before the texts |

## 22. Sources

Google, read 2026-11-12 (`ai.google.dev` redirects to `aistudio.google.com/docs`):
[Models](https://ai.google.dev/gemini-api/docs/models) ·
[Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) ·
[Gemini 3.5 Flash-Lite](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) ·
[Pricing](https://ai.google.dev/gemini-api/docs/pricing) ·
[Structured output](https://ai.google.dev/gemini-api/docs/structured-output) ·
[Thinking](https://ai.google.dev/gemini-api/docs/thinking) ·
[Interactions](https://ai.google.dev/gemini-api/docs/interactions) ·
[Interactions API reference](https://ai.google.dev/api/interactions-api-v1) ·
[Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding) ·
[Media resolution](https://ai.google.dev/gemini-api/docs/media-resolution) ·
[Audio understanding](https://ai.google.dev/gemini-api/docs/audio).
Read 2026-11-11: [Transcription](https://ai.google.dev/gemini-api/docs/transcribe) ·
[Image generation](https://ai.google.dev/gemini-api/docs/image-generation) ·
[Nano Banana 2.1](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1) ·
[Terms](https://ai.google.dev/gemini-api/terms).

Browser and codecs: [File drag and drop](https://developer.mozilla.org/en-US/docs/Web/API/HTML_Drag_and_Drop_API/File_drag_and_drop)
and [MediaRecorder()](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/MediaRecorder)
and [RFC 6716](https://www.rfc-editor.org/rfc/rfc6716) (2026-11-12);
[getUserMedia](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia) ·
[Secure contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) ·
[webkitdirectory](https://developer.mozilla.org/en-US/docs/Web/API/HTMLInputElement/webkitdirectory) ·
[createImageBitmap](https://developer.mozilla.org/en-US/docs/Web/API/Window/createImageBitmap) ·
[toBlob](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/toBlob) (2026-11-11).

Project: `docs/design/poster.md` (limits, ledger, record) · `docs/design/factory.md`
(stock, approval, panel §11, §14, §18) · `docs/design/panel-brief.md` (named widths) ·
the seed-to-result research report of 2026-11-12 (§5.2, §5.3, §5.5, §6; kept outside the
repository).
