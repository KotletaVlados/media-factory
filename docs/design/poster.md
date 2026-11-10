# Poster: one post package → Facebook Page, Instagram, X, LinkedIn

Design document. Status: ready to build. Written 2026-11-09, before any poster code existed.
Vendor documentation was read 2026-11-08 and 2026-11-09; every external fact below cites
its page and says whether the page confirms it. Facts the docs do not settle are marked
**UNCONFIRMED** and name the cheapest check that settles them (§14).

## 1. Originating requirement

The operator collects the API keys of their accounts and asked for a platform to post with
(2026-11-08). Decisions taken on 2026-11-08:

1. Own poster in this repository: one post → all chosen networks, no subscription.
2. The operator gives posts to an assistant in chat (text + image); the assistant runs the
   poster. No bot, no web UI.
3. Start with the "kotleta" set: a Facebook Page, the Instagram business account linked to
   it, an X account, and the operator's personal LinkedIn profile.
4. X is paid per use: hard cap USD 5 per calendar month; above it the poster refuses and asks.
5. First live check: a test post on a test Page, then delete it.

Addendum (2026-11-08), in summary: the operator picks a theme and a photo (fresh or from
prepared ones); the theme is split into quotes or otherwise reworked, and each network gets
its own version, tailored in length and context, so the post is not duplicated.

The addendum makes the unit of work a **post package** (one theme → one text and one image
choice per network), adds per-network validation before any call, adds an image library,
and keeps text generation and scheduling out of the tool for now.

### 1.1 Validation against the requirement

| Requirement | Where the design meets it |
|---|---|
| A posting platform the operator does not pay a subscription for | Local CLI, standard library only (§4) |
| Operator gives posts in chat; the assistant runs it | The assistant writes a package file and runs `publish` (§5, §6) |
| Post is tailored per network, not duplicated | One variant per network with its own text and image (§5) |
| Character count tailored per network | Pre-flight limits from vendor docs, refusal with the count, never truncation (§8) |
| Prepared photos or a fresh photo | Image library by name, or a direct path (§5.3) |
| Kotleta set first; other Pages by name | Profiles and targets (§5.4) |
| X ≤ USD 5 per calendar month, refuse and ask above | Local ledger checked before any X call (§11.2) |
| First live check on a test Page, then delete | `delete` command and smoke plan (§6, §14) |
| Secrets never shown | Single redacting output path, tests with canary secrets (§12, §13) |

## 2. Scope

Built:

- `python3 -m poster` (Python 3.12, standard library only; the system Python has no pip and
  nothing here needs a dependency).
- Targets: Facebook Page text and text+image; Instagram image+caption (text-only refused);
  X text and text+image; LinkedIn personal profile text and text+image.
- Commands: `publish` (with `--dry-run`), `delete` (Facebook Page posts), `login linkedin`,
  `records`, `status`, `check-staging` (diagnostic for the Instagram image path).
- Local state outside git: post record and X spending ledger.
- Offline unit tests with HTTP mocked.
- A short Russian README section (written by the build stage, outline in §15).

Not built: see §17 "Deferred — not currently justified".

## 3. Vendor facts

Legend: **C** = confirmed on the cited official page; **U** = UNCONFIRMED (see §14 for the check).

### 3.1 Facebook Page

| # | Fact | Status | Source |
|---|---|---|---|
| F1 | Text post: `POST /{page_id}/feed` with `message`; response `{"id": "<page_post_id>"}`. Needs a Page access token with `pages_manage_posts` and `pages_read_engagement`. | C | [Pages API — Posts](https://developers.facebook.com/documentation/pages-api/posts) |
| F2 | Photo post: `POST /{page_id}/photos`; response `{"id": "<photo_id>", "post_id": "<page_post_id>"}`. | C | same page |
| F3 | Upload by `url` or as `multipart/form-data` (field name does not matter, "historically people have used `source`"). `caption` is the photo text; `message` is "Deprecated. Please use the caption param instead." | C | [Graph API Reference v27.0: Page Photos](https://developers.facebook.com/docs/graph-api/reference/page/photos/) |
| F4 | File types ".jpeg, .bmp, .png, .gif, .tiff"; "Files can not exceed 10MB."; "For .png files, we recommend not exceeding 1MB or the image may appear pixelated." | C | same page |
| F5 | Unpublished upload: add `published=false`. "After you upload an unpublished photo, Facebook stores it in a temporary upload state, which means it will remain on Facebook servers for about 24 hours. If you do not publish these photos within 24 hours, we delete them." `temporary=true` is only for scheduled posts. | C | same page |
| F6 | Photo node has `images` ("The different stored representations of the photo"); "An app can delete any photos it published" via `DELETE /{photo_id}`, returns `success`. The page names the legacy `publish_pages` permission for Page photos. | C (permission wording dated) | [Graph API Reference: Photo](https://developers.facebook.com/docs/graph-api/reference/photo/) |
| F7 | Delete a post: `DELETE /{page_post_id}` → `{"success": true}`. | C | [Pages API — Posts](https://developers.facebook.com/documentation/pages-api/posts) |
| F8 | Permalink: `https://www.facebook.com/{page_post_id}`. | C | same page |
| F9 | Current Graph API version in all examples: `v27.0`. | C | same pages |
| F10 | Page post text length limit. | **U** — Meta documents none (Posts guide and Page Photos reference checked). Not enforced; the API's own error is reported. | — |

### 3.2 Instagram (Instagram API with Facebook Login)

| # | Fact | Status | Source |
|---|---|---|---|
| I1 | Host `graph.facebook.com`; token: Facebook Page access token; permissions `instagram_basic`, `instagram_content_publish` (plus `pages_read_engagement`). | C | [Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing), [IG User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) |
| I2 | "We cURL media used in publishing attempts, so the media must be hosted on a publicly accessible server at the time of the attempt." `image_url`: "required for images … the image must be on a public server." No upload-by-bytes path for images (resumable upload is "For resumable video uploads"). | C | same pages |
| I3 | Image specs: "Format: JPEG", "File size: 8 MB maximum", "Aspect ratio: Must be within a 4:5 to 1.91:1 range", width scaled into 320–1440. "JPEG is the only image format supported." | C | IG User Media; Content Publishing |
| I4 | Caption: "Maximum 2200 characters, 30 hashtags, and 20 @ tags." | C | IG User Media |
| I5 | Flow: `POST /{ig_user_id}/media` (`image_url`, `caption`) → container id; `GET /{container_id}?fields=status_code` (`EXPIRED` after 24 h, `ERROR`, `FINISHED`, `IN_PROGRESS`, `PUBLISHED`); "We recommend querying a container's status once per minute, for no more than 5 minutes."; `POST /{ig_user_id}/media_publish` with `creation_id` → `{"id": "<media_id>"}`, optional `config_issue` such as `CAPTION_NOT_ATTACHED`. | C | [IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container), [media_publish](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish), Content Publishing |
| I6 | Publishing limit: the guide says 100 API-published posts per 24 h, the `media_publish` and `content_publishing_limit` references say 50. Irrelevant at this volume; not checked locally. | C (inconsistent) | Content Publishing; [content_publishing_limit](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit) |
| I7 | IG Media `permalink`: "Permanent URL to the media." Deleting IG media needs `instagram_manage_contents`, which the current tokens were not granted. | C | [IG Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media) |
| I8 | An unpublished Page photo's `images[].source` URL is fetchable anonymously, is JPEG for a JPEG upload, and is accepted by Instagram as `image_url`. Deleting an unpublished photo with the Page token works. | **U** (U1) | — |

### 3.3 X (API v2, OAuth 1.0a user context)

| # | Fact | Status | Source |
|---|---|---|---|
| X1 | Create: `POST https://api.x.com/2/tweets`, JSON `{"text": …, "media": {"media_ids": ["…"]}}`, 201 with `data.id`. Security: OAuth 2.0 user token or `UserToken` (OAuth 1.0a). | C | [Create or Edit Post](https://docs.x.com/x-api/posts/create-post) |
| X2 | Upload: `POST https://api.x.com/2/media/upload`, `application/json` (`media` base64) or `multipart/form-data`; required `media`, `media_category` (`tweet_image`); response `data.id`, `media_key`, optional `processing_info`. Security includes `UserToken`. Simple upload is "images only". | C | [Upload Media](https://docs.x.com/x-api/media/upload-media), [Media introduction](https://docs.x.com/x-api/media/introduction) |
| X3 | Image: JPG, PNG, GIF, WEBP, ≤ 5 MB; up to 4 photos per post. | C | [Media best practices](https://docs.x.com/x-api/media/quickstart/best-practices) |
| X4 | OAuth 1.0a: HMAC-SHA1 header with the 7 `oauth_*` fields; signature over method, base URL and collected query/body parameters; signing key = percent-encoded consumer secret `&` token secret. Only form-encoded bodies are signed (RFC 5849 §3.4.1.3.1, which the X page cites), so JSON and multipart bodies are not part of the signature. | C | [Authorizing a request](https://docs.x.com/fundamentals/authentication/oauth-1-0a/authorizing-a-request), [Creating a signature](https://docs.x.com/fundamentals/authentication/oauth-1-0a/creating-a-signature), [RFC 5849 §3.4.1.3.1](https://datatracker.ietf.org/doc/html/rfc5849#section-3.4.1.3.1) |
| X5 | Prices (pay-per-use, per request): Post: Create $0.015; Post: Create (with URL) $0.200; Content: Manage (deleting or hiding posts) $0.005; Media Metadata $0.005. Changelog 2026-04-16: "`POST /2/tweets` is now $0.015 per post, and Posts containing a URL are $0.20 per Post". | C | [Pricing](https://docs.x.com/x-api/getting-started/pricing), [developer.x.com rate card](https://developer.x.com/#pricing), [Changelog](https://docs.x.com/changelog) |
| X6 | "Do failed requests count? No. Only successful responses that return data are billed." Spending limits per billing cycle can be set in the Developer Console. | C | [Usage and Billing](https://docs.x.com/x-api/fundamentals/post-cap), Pricing |
| X7 | Price of `POST /2/media/upload`: no line item on either official price list (35 items on the rate card, none for upload). | **U** (U2) | — |
| X8 | Whether a post with attached media is billed as "with URL". | **U** (U3) | — |
| X9 | Which strings make a post "with URL" for billing. | **U** (U4) | — |
| X10 | Counting: 280 weighted; twitter-text v3: code points in 0–4351, 8192–8205, 8208–8223, 8242–8247 weigh 1, all others 2; every emoji (including ZWJ sequences) counts 2; every URL counts 23; NFC first. Cyrillic is in the weight-1 range. | C | [Counting characters](https://docs.x.com/fundamentals/counting-characters), [twitter-text config v3](https://github.com/twitter/twitter-text/blob/master/config/v3.json) |
| X11 | "Self-serve customers: Posts created via the API are limited to a maximum of 1 cashtag per post." | C | [Manage Posts](https://docs.x.com/x-api/posts/manage-tweets/introduction) |
| X12 | Post URL form used in X's own payload examples: `https://x.com/i/web/status/{id}`. | C | [Account Activity API payload example](https://docs.x.com/x-api/account-activity/introduction) |

### 3.4 LinkedIn (personal profile)

| # | Fact | Status | Source |
|---|---|---|---|
| L1 | `POST https://api.linkedin.com/rest/posts`; headers `Linkedin-Version: YYYYMM` and `X-Restli-Protocol-Version: 2.0.0`; body `author`, `commentary`, `visibility: PUBLIC`, `distribution {feedDistribution: MAIN_FEED, targetEntities: [], thirdPartyDistributionChannels: []}`, `lifecycleState: PUBLISHED`, `isReshareDisabledByAuthor: false`; image posts add `content.media.id = urn:li:image:…`. 201, post id in the `x-restli-id` header. `w_member_social`: "Post, comment, and like posts on behalf of an authenticated member." "The Posts API replaces the ugcPosts API." | C | [Posts API (Oct 2026)](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-10) |
| L2 | Images: `POST /rest/images?action=initializeUpload` with `initializeUploadRequest.owner` = person URN → `uploadUrl`, `image`; "JPG, GIF, and PNG", "less than 36,152,320 pixels"; with only `w_member_social`, `GET /rest/images` is forbidden (no status polling). Upload: "Use a PUT method … requires a valid OAuth token in the 'Authorization' header." | C | [Images API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2026-10), [Vector Asset API — Upload the Image](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/vector-asset-api?view=li-lms-2026-10#upload-the-image) |
| L3 | `commentary` is "little" text: reserved characters `\| { } @ [ ] ( ) < > # \ * _ ~` must be backslash-escaped "even if those characters are not used in one of the supported elements"; hashtags via `{hashtag\|\#\|tag}`. | C | [little Text Format](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format?view=li-lms-2026-10) |
| L4 | Text limit: "The maximum length of the text of a UGC Post is 3000 characters." The Posts API schema states no number but returns `FIELD_LENGTH_TOO_LONG`. | C for ugcPosts, **U** for `/rest/posts` (U7) | [UGC Post API](https://learn.microsoft.com/en-us/linkedin/compliance/integrations/shares/ugc-post-api), [Post API schema](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/post-api-schema?view=li-lms-2026-10) |
| L5 | Versions: latest `202610`, active until 2027-10-15; every call must name a version; versions live ≥ 1 year. | C | [Versioning](https://learn.microsoft.com/en-us/linkedin/marketing/versioning), [Migrations](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/migrations) |
| L6 | Delete: `DELETE /rest/posts/{encoded urn}` → 204, idempotent. | C | Posts API |
| L7 | OAuth: `GET https://www.linkedin.com/oauth/v2/authorization` (`response_type=code`, `client_id`, `redirect_uri`, `state`, `scope`); code lives 30 minutes; `POST https://www.linkedin.com/oauth/v2/accessToken` (form: `grant_type=authorization_code`, `code`, `client_id`, `client_secret`, `redirect_uri`); "all access tokens are issued with a 60-day lifespan"; "Programmatic refresh tokens are available for a limited set of partners"; requesting a different scope "invalidates" earlier tokens. Redirect URLs must be absolute, without `#`, query ignored, and "Add the redirect (callback) URL via HTTPS to your server." The Developer Portal also has a token generator. | C | [Authorization Code Flow](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow) |
| L8 | Person URN: Share on LinkedIn says to get it via Sign In with LinkedIn using OpenID Connect; scopes `openid`, `profile`; `GET https://api.linkedin.com/v2/userinfo` returns `sub`. Products: "Share on LinkedIn" grants `w_member_social`; "Sign in with LinkedIn using OpenID Connect" grants `openid`/`profile`. | C | [Share on LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin), [Sign In with LinkedIn using OpenID Connect](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2) |
| L9 | The self-serve Share on LinkedIn guide (updated 2025-02-05) still shows `/v2/ugcPosts` + `/v2/assets`; whether `/rest/posts` and `/rest/images` accept a member token from a Share-on-LinkedIn-only app is not stated. | **U** (U6) | — |
| L10 | `http://localhost:<port>/…` accepted as a registered redirect URL (the doc only says HTTPS). | **U** (U5) | — |
| L11 | Member rate limit for shares: 150 requests per member per day. | C | Share on LinkedIn |

### 3.5 Decision (a): how a local image reaches Instagram

Instagram only takes a public `image_url` (I2). Options:

| Option | Cost / new infra | Coupling | Verdict |
|---|---|---|---|
| **A. Stage the image as an unpublished photo on the Instagram account's linked Page (`published=false`), pass its `images[].source` CDN URL, delete the photo after `media_publish`** | None; same Page token | Independent of the Facebook target's result and image | **Chosen** |
| B. Reuse the published Facebook photo of the same package | None | Fails when Facebook fails or when the Facebook variant uses another image or none (the addendum makes that normal) | Rejected |
| C. External hosting (object storage, an image host, another project's server) | New account or cost, or a dependency on another project's server | — | Rejected |
| D. Temporary public tunnel from this machine | New dependency, exposes a local port | — | Rejected |
| E. Instagram resumable upload | Documented for video only (I2) | — | Not applicable |

Cleanup: after `media_publish` returns (success or definite failure) or after any failure
once the photo exists, `DELETE /{photo_id}` with the Page token, then read back
`GET /{photo_id}` and expect an error. If the delete fails, the post record keeps
`staging_photo_id` with `cleanup: "failed"`, the summary says so, and Meta's own rule
removes unpublished photos within about 24 hours (F5), so a failed cleanup heals itself.
Nothing appears on the Page: unpublished photos create no feed story (checked in the smoke
stage, §14 U1).

## 4. Module layout

One package at the repository root, flat, standard library only.

```
poster/
  __init__.py      version string
  __main__.py      calls cli.main()
  cli.py           argparse, commands, summary, exit codes, the single redacting output path
  config.py        env-file path resolution, parse, atomic write-back; target/profile registry;
                   prices, cap, API versions; state directory
  redact.py        Redactor: secret registry + pattern masks
  http.py          Request/Response; UrllibTransport (HTTPS only, no redirects, timeouts);
                   DryRunTransport; multipart encoder; ApiError with redacted body
  package.py       load and validate a package; resolve images (library name or path)
  rules.py         per-network text counting and limits; image sniffing (format, size,
                   width/height for JPEG/PNG/GIF/WEBP; BMP/TIFF format only)
  facebook.py      text post, photo post, delete post, stage/unstage unpublished photo
  instagram.py     staging → container → status → publish → permalink → cleanup
  xapi.py          OAuth 1.0a signer, media upload, create post
  linkedin.py      little-format escaping, image upload, create post, login flow
  state.py         post record and X ledger (JSON Lines, flock)
tests/
  base.py          network guard, temp env file and state dir
  test_*.py        see §13
```

Every target module exposes one function `publish(variant, target, ctx) -> Result`; `ctx`
carries the transport, clock/sleep, redactor, ledger and record writer, so tests and dry-run
swap them without patching.

## 5. Post package

### 5.1 Format

A package is one JSON file (standard library parser; YAML would need a dependency) that the
assistant writes after the operator approves the texts. Default folder
`content/packages/` in the repository root (git-ignored, §11.4).

```json
{
  "schema": 1,
  "id": "2026-11-09-halving",
  "theme": "Why the halving matters (free text for people; not sent anywhere)",
  "variants": {
    "facebook":  {"text": "Long-form text for the Page …", "image": "halving-chart.jpg"},
    "instagram": {"text": "Caption … #bitcoin", "image": "halving-square.jpg"},
    "x":         {"text": "One sharp quote from the theme"},
    "linkedin":  {"text": "Professional angle …", "image": "photos/2026-11-09/desk.png"}
  },
  "meta": {"source": "chat", "approved_by_operator": "2026-11-09"}
}
```

Rules:

- `schema` must be `1`. Unknown top-level or variant keys are refused (typos such as `txt`
  fail loudly). A later schema version adds fields deliberately.
- `id`: optional, `[a-z0-9][a-z0-9._-]{0,79}`; defaults to the file name without `.json`.
  It keys the post record and re-runs (§11.1).
- `variants` keys are networks: `facebook`, `instagram`, `x`, `linkedin`. At least one.
- `text`: required, non-empty after trimming; normalised to Unicode NFC (X counts NFC, X10)
  and otherwise sent exactly as written. The dry-run shows the normalised text.
- `image`: optional. Absent or `null` means a text-only post for that network. A network
  may use a different image from the others or none.
- `meta`: optional free-form object for provenance (who wrote it, when approved). The
  poster ignores it. A future text generator records itself here without a schema change.
- `theme` is for people and the record; it is never published.

A theme split into several quotes is several packages, one per publication; nothing in the
format ties them to a date. Scheduling and series spread over days are undecided and left
out (§17); a later `publish_at` field would be a schema-2 addition read by a scheduler that
calls the same `publish`.

### 5.2 Which targets a package reaches

The CLI chooses accounts (`--profile` or `--targets`); the package chooses networks.
For each selected target, the variant of its network is used. A selected target with no
variant is reported `skipped (no variant)`; a variant whose network has no selected target
is reported `unused variant` (warning). A package never names accounts, so the same file
works for a test Page and for the kotleta profile.

### 5.3 Image library and paths

- A value without `/` is a library name, resolved in the library folder: default
  `content/images/` in the repository root, override `--library DIR` or `MF_IMAGE_LIBRARY`.
- A value containing `/` is a path; relative paths resolve against the package file's folder.
- The file must exist and be a regular file. `..` is allowed in paths (the operator's own
  files); library names may not contain `/` or start with `.`.
- Prepared photos are copied into the library by the assistant. The library is
  git-ignored.

### 5.4 Targets and profiles

Targets are derived from the env-file variable names (values are never needed to list them):

| Target | Built from | Network |
|---|---|---|
| `fb:<name>` | `FB_PAGE_<NAME>_ID`, `FB_PAGE_<NAME>_TOKEN` | Facebook Page |
| `ig:<name>` | `IG_<NAME>_USER_ID`, plus `FB_PAGE_<NAME>_ID`/`_TOKEN` (token and staging Page) | Instagram |
| `x` | `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` | X |
| `linkedin` | `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_TOKEN_EXPIRES_AT`, `LINKEDIN_PERSON_URN` | LinkedIn |

Profiles (constant in `config.py`):

| Profile | Targets |
|---|---|
| `kotleta` | `fb:kotleta`, `ig:kotleta`, `linkedin`, `x` |

`--targets` accepts any derived target, comma-separated (for example `fb:kotleta`, or `fb:<name>` for any other Page in the env file).
Execution order inside a run: Facebook, Instagram, LinkedIn, X — the paid target last, so an
interrupted run has not spent money on a package whose free targets failed to start.

## 6. CLI

```
python3 -m poster [--env-file PATH] [--state-dir DIR] [--debug] <command> …

publish PACKAGE (--profile NAME | --targets T[,T…]) [--dry-run] [--library DIR]
                [--force-target T]
delete  --target fb:NAME --post-id ID
login   linkedin [--port 8765] [--timeout 600]
records [--last N] [--package ID]
status
check-staging --page NAME IMAGE [--ig-container ig:NAME]
```

- `--profile`/`--targets` is required for `publish`; there is no default account set, so a
  mistyped command cannot post to every network.
- `--dry-run`: runs the full pre-flight and the real request builders against a
  `DryRunTransport` that records each request and returns synthetic ids. No socket is
  opened, no state file is written or created. Output per target: target, every request
  (method, URL with query secrets masked, header names with `Authorization: [redacted]`,
  form/JSON fields in full except secrets, file parts as name/type/bytes/dimensions, base64
  media as `<base64 of N bytes from FILE>`), the exact text, the counts against limits, and
  for X the price estimate and the month total.
- `--force-target T`: publish `T` even though the record shows it `published` or `unknown`
  for this package id (§11.1). Never needed in the normal flow.
- `delete`: only Facebook Page posts, and only ids the post record shows as published by
  this tool to that target. First reads `GET /{page_post_id}?fields=id` with the Page token
  (must answer 200, otherwise nothing is deleted), sends `DELETE /{page_post_id}`, reads back
  `GET /{page_post_id}?fields=id` expecting the does-not-exist answers of §9.1, appends a
  `deleted` event.
- `records`: the last N post-record entries (time, package, target, status, id, URL).
- `status`: X month spend, cap and remaining; worst-case posts left at current prices;
  LinkedIn token expiry in days; for each target whether its variable names are present
  (names only).
- `check-staging`: the diagnostic for decision (a): stages IMAGE as an unpublished photo on
  Page NAME, prints the `images[].source` host, size and type from an anonymous GET (no
  token, no cookies), confirms the photo did not become a Page post: it reads
  `GET /{page_id}/published_posts?limit=10` before staging and again after the CDN check, and
  looks at the staging upload answer (`/feed` is not used: a Page token without
  `pages_read_engagement` or Page Public Content Access gets HTTP 400, code 10 there; the
  smoke run of 2026-11-09 confirmed it). A photo that became a post is listed under its post
  id, not its photo id (seen in the smoke run),
  so the check compares the two listings and does not look for the photo id. Step 3 prints
  `yes`, `NO (new post <id>)` (a new id in the second listing, or a `post_id` in the upload
  answer, F2) or, when either listing answers with an error, `unreadable (HTTP n, code c)`; an
  unreadable edge never reads as `NO`, and it fails the check. Then it deletes the photo and reads back. With `--ig-container`, it also creates an Instagram
  container from that URL and polls it to `FINISHED`, and never calls `media_publish`
  (the container expires unpublished after 24 hours, I5).

Exit codes: `0` all selected targets published (or already published); `1` at least one
target failed or ended `unknown` at run time; `2` usage error or pre-flight refusal (nothing
was sent).

Example run summary (text only, one line per target; ids shortened here):

```
package 2026-11-09-halving  profile kotleta
  fb:kotleta  published  https://www.facebook.com/<page_post_id>
  ig:kotleta  published  https://www.instagram.com/p/<code>/   staging photo removed
  linkedin    FAILED     401 Unauthorized: token expired — run: python3 -m poster login linkedin
  x           published  https://x.com/i/web/status/<id>   X month $0.230 of $5.00
exit 1
```

## 7. Env-file handling

- Path: `--env-file` > `MF_ENV_FILE` > `<repository root>/.env`, where the root is the parent
  of the `poster/` folder. Credentials and settings come only from the env file; the process
  environment supplies only `MF_*`, `HOME` and `XDG_STATE_HOME`, so a stray shell export
  cannot change which account is used. A checkout without its own
  `.env` passes `--env-file`.
- Parse: lines `NAME=VALUE`; `#` comments and blank lines kept; optional matching single or
  double quotes around a value are removed; no interpolation. A malformed line is reported by
  line number only, never by content.
- Required names per target are checked before any call; missing ones are named
  (`missing FB_PAGE_KOTLETA_TOKEN`), values never shown.
- Write-back (only `login linkedin`): update or append `LINKEDIN_ACCESS_TOKEN`,
  `LINKEDIN_TOKEN_EXPIRES_AT` (UTC ISO-8601), `LINKEDIN_PERSON_URN`; every other line is kept
  byte for byte; the new content goes to a temporary file in the same folder created with
  mode `0600`, `fsync`, then `os.replace`. No backup copy is written (it would duplicate
  secrets). The path is resolved with `os.path.realpath` first, so a symlinked env file
  keeps its link and the real file is replaced.
- Optional non-secret settings read from the same file (defaults in code):

| Name | Default | Meaning |
|---|---|---|
| `META_GRAPH_VERSION` | `v27.0` | Graph API version (F9) |
| `LINKEDIN_API_VERSION` | `202610` | `Linkedin-Version` header (L5) |
| `X_MONTHLY_CAP_USD` | `5.00` | Operator's cap; raising it is a deliberate edit of the env file |
| `X_PRICE_POST` | `0.015` | X5 |
| `X_PRICE_POST_WITH_URL` | `0.200` | X5 |
| `X_PRICE_POST_WITH_MEDIA` | `0.200` | U3: treated as "with URL" until confirmed |
| `X_PRICE_MEDIA_UPLOAD` | `0.015` | U2: no official line item; counted until confirmed |

`KEYS.md` lists every name the code reads.

## 8. Pre-flight validation

Pre-flight runs for every selected target before any network call. If any target fails
pre-flight, **nothing is sent** and the run exits `2` with every problem listed; the
assistant fixes the package and runs again. Reason: a package is one publication; sending
three networks and fixing the fourth later produces exactly the duplicated, out-of-step
series the operator wants to avoid. Run-time failures are isolated per target (§9.6).
Text is never truncated; a refusal shows the count, the limit and how it was counted.

| Check | Facebook | Instagram | X | LinkedIn |
|---|---|---|---|---|
| Text | non-empty; no length limit (F10), count shown | ≤ 2200 (counted in UTF-16 units, conservative), ≤ 30 hashtags, ≤ 20 @mentions (I4) | weighted ≤ 280 (§8.1); ≤ 1 cashtag (X11) | escaped commentary (§9.5) ≤ 3000 UTF-16 units (L4, conservative) |
| Image required | no | **yes**: "Instagram needs an image; this variant has none" | no | no |
| Formats | JPEG, BMP, PNG, GIF, TIFF (F4) | JPEG only (I3) | JPEG, PNG, WEBP, static GIF (X3) | JPEG, PNG, GIF (L2) |
| Size | ≤ 10 000 000 bytes (F4; decimal MB, conservative); PNG > 1 MB → warning (F4) | ≤ 8 000 000 bytes (I3) | ≤ 5 000 000 bytes (X3) | no documented byte limit |
| Dimensions | — | aspect w/h between 0.8 and 1.91 (I3) | — | width×height < 36 152 320 (L2) |
| Account | target variables present | target variables present | variables present; **budget** (§11.2) | token present and not expiring within 10 minutes; warning under 7 days |

Format comes from magic bytes, not the file name. Dimensions come from the JPEG SOFn
marker, PNG IHDR, GIF logical screen, WEBP VP8/VP8L/VP8X header.

### 8.1 X weighted length (conservative twitter-text v3)

1. NFC-normalise.
2. Tokens starting `http://` or `https://` up to whitespace: 23 each (X10).
3. Bare domain-like tokens (`label.label` ending in a 2+ letter TLD, optional path): count
   `max(23, own weighted length)`, because X may or may not link them; either way the true
   count is not higher.
4. Every other code point: weight 1 in 0–4351, 8192–8205, 8208–8223, 8242–8247, else 2.
   `©` and `®` count 2 (they are emoji). No emoji-sequence folding: a ZWJ sequence counts
   more than X's 2, never less.

The result is never below X's own count, so a post that passes here passes at X. The
dry-run prints both "weighted 247/280" and the rule used.

## 9. Request flows

Common: HTTPS only; redirects are not followed (urllib would forward `Authorization` to the
redirect host); timeouts 30 s for API calls, 120 s for uploads; `User-Agent: media-factory-poster/<version>`;
JSON responses parsed; non-2xx becomes `ApiError(status, short redacted vendor message)`.

### 9.1 Facebook Page (`fb:<name>`)

Text: `POST https://graph.facebook.com/{v}/{page_id}/feed`, form body `message`,
`access_token`. Result id = `page_post_id`; URL `https://www.facebook.com/{page_post_id}` (F8).

Text + image: `POST …/{page_id}/photos`, multipart: `source` (file), `caption`,
`access_token` (F3). Record `post_id` (used by `delete`) and `photo_id`.

Delete: first `GET …/{page_post_id}?fields=id` with the same Page token must answer 200
(otherwise nothing is sent and the command reports why). Then `DELETE …/{page_post_id}?access_token=…`
→ `success: true` (F7). Then the read-back `GET …/{page_post_id}?fields=id` must fail with a
does-not-exist answer. F7 documents only the DELETE answer; the read-back answers are
**observed**, not documented (smoke 2026-11-09, `docs/smoke/2026-11-09-facebook-page.md` §3): deleted
Page posts, text and photo, answered HTTP 400, code 10 ("Object does not exist, cannot be loaded
due to missing permission"); a bare photo node answered code 100, subcode 33. Gone is therefore
HTTP 404, code 100 with subcode 33, or code 10 — code 10 only after the 200 pre-read, because the
same token could read the post a moment before, so a permission problem is ruled out. Staging
photos (no pre-read) count only 404 and code 100/33. Any other answer (190, a 5xx, a cut-off)
proves nothing: the command reports `deletion not confirmed` with the HTTP status and code and
does not mark the post `deleted`.

### 9.2 Instagram (`ig:<name>`)

1. Stage: `POST …/{page_id}/photos` multipart `source`, `published=false`,
   `access_token` → `photo_id` (F5).
2. `GET …/{photo_id}?fields=images` → choose the entry with the largest `width`; its
   `source` is the `image_url`. The URL is never logged in full (host only).
3. `POST …/{ig_user_id}/media` form `image_url`, `caption`, `access_token` → `container_id` (I5).
4. `GET …/{container_id}?fields=status_code,status`: if not `FINISHED`, poll once per minute
   for at most 5 minutes (I5). `ERROR`/`EXPIRED`/timeout → target fails.
5. `POST …/{ig_user_id}/media_publish` form `creation_id`, `access_token` → `media_id`.
   A `config_issue` (for example `CAPTION_NOT_ATTACHED`) is shown as a warning on a
   published result.
6. `GET …/{media_id}?fields=permalink` → URL (I7).
7. Cleanup in `finally` once step 1 succeeded: `DELETE …/{photo_id}`, read back (§3.5).

Sleep and clock are injected; tests run the polling instantly.

### 9.3 X (`x`)

1. Budget pre-flight (§11.2) already passed.
2. If an image: reserve `X_PRICE_MEDIA_UPLOAD` in the ledger, then `POST
   https://api.x.com/2/media/upload` JSON `{"media": "<base64>", "media_category":
   "tweet_image"}` with the OAuth 1.0a header (signature over method + URL only, X4).
   `data.id` is the media id. If `processing_info` is present and its state is not
   `succeeded`, the target fails (simple upload is for images, X2).
3. Reserve the post price (§11.2), then `POST https://api.x.com/2/tweets` JSON
   `{"text": …}` plus `"media": {"media_ids": [id]}` when an image was uploaded.
   201 `data.id` → URL `https://x.com/i/web/status/{id}` (X12).
4. Each reservation is settled `ok` on success, `failed` on a definite error response
   (X6: failed requests are not billed), and stays `reserved` (counted) on a timeout or
   connection error.

OAuth 1.0a header (X4): `oauth_consumer_key` = `X_API_KEY`, `oauth_token` =
`X_ACCESS_TOKEN`, nonce = 32 random bytes base64 with non-word characters removed,
timestamp = now, method HMAC-SHA1, version 1.0, key =
`pct(X_API_SECRET)&pct(X_ACCESS_SECRET)`.

### 9.4 LinkedIn (`linkedin`)

Headers on every `/rest/*` call: `Authorization: Bearer <token>`,
`Linkedin-Version: <LINKEDIN_API_VERSION>`, `X-Restli-Protocol-Version: 2.0.0`.

1. If an image: `POST https://api.linkedin.com/rest/images?action=initializeUpload`
   `{"initializeUploadRequest": {"owner": "<LINKEDIN_PERSON_URN>"}}` → `uploadUrl`,
   `image` (L2).
2. `PUT <uploadUrl>` with the file bytes and the Bearer header, expect 201. The poster sends
   the token only if the `uploadUrl` host is `linkedin.com` or ends with `.linkedin.com`.
   No status polling (forbidden for `w_member_social`, L2).
3. `POST https://api.linkedin.com/rest/posts` with the L1 body, `author` =
   `LINKEDIN_PERSON_URN`, `commentary` = escaped text (§9.5), and
   `content.media.id` = the image URN when present. Post URN from `x-restli-id` (kept in
   the record; it is what a later delete needs). The record's URL
   `https://www.linkedin.com/feed/update/<urn>/` is a convenience link: the API pages do not
   document a permalink format, so the URN, not the URL, is the reference.

### 9.5 LinkedIn commentary escaping

`#word` (word = Unicode letters, digits, `_`) becomes `{hashtag|\#|word}` (L3 template).
Every other reserved character `| { } @ [ ] ( ) < > # \ * _ ~` gets a backslash. Mentions
are not supported (they need URNs). The dry-run shows the operator's text and the escaped
form with both counts.

### 9.6 Partial failure

Each target runs in its own `try`; any exception becomes that target's `failed` result with
a redacted message and the run continues. Results and record entries are written as each
target finishes, so a crash mid-run leaves an accurate record. Publish calls are never
retried automatically (they are not idempotent). A timeout or connection error after a
publish request was sent records `unknown` and the message tells the assistant to look
at the account before re-running with `--force-target`. The same holds for a reply that is
cut off or unreadable (`IncompleteRead`, connection reset, a 2xx without the post id) and for
an HTTP 5xx on the final publish call (Facebook post, Instagram `media_publish`, X create post,
LinkedIn post): the vendor may have acted before it failed, so the result is `unknown`, and an
X reservation stays counted in the ledger. A 4xx on that call is a definite refusal and stays
`failed`. A 5xx on an earlier step (staging, container, media upload) publishes nothing and
stays `failed`.

## 10. LinkedIn login flow

Prerequisites (operator, once, in the LinkedIn Developer Portal → the app):
Products "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect" (L8);
Auth tab → Authorized redirect URLs → exactly `http://localhost:8765/callback`
(or the `--port` used).

`python3 -m poster login linkedin`:

1. Prints: "Register this exact redirect URL in the LinkedIn app (Auth tab → Authorized
   redirect URLs): http://localhost:8765/callback". Reads `LINKEDIN_CLIENT_ID` and
   `LINKEDIN_CLIENT_SECRET` (presence only shown).
2. Binds `127.0.0.1:8765` (fixed, because the registered URL must match; if busy it stops
   and says to pick `--port` and register that URL instead).
3. Prints the authorization URL: `https://www.linkedin.com/oauth/v2/authorization?response_type=code&client_id=…&redirect_uri=…&state=<32 random bytes>&scope=openid%20profile%20w_member_social`.
   The scope never changes between logins (L7: a different scope invalidates earlier tokens).
   The assistant runs this command in the background and relays the URL to the operator,
   who clicks Allow.
4. Serves exactly one `GET /callback`; checks `state` with `hmac.compare_digest`; handles
   `error`/`error_description`; answers a plain "Done, you can close this tab" page that
   echoes nothing; times out after `--timeout` seconds (code lifetime is 30 minutes, L7).
5. `POST https://www.linkedin.com/oauth/v2/accessToken` (form, L7) → `access_token`,
   `expires_in`.
6. `GET https://api.linkedin.com/v2/userinfo` → `sub` → `urn:li:person:<sub>` (L8).
7. Access probe (U6): `POST /rest/images?action=initializeUpload` for the person URN. It
   creates an unused upload slot and publishes nothing. 2xx → "versioned Posts API reachable";
   403 → warning naming the ugcPosts fallback (§17).
8. Writes the three variables (§7) and prints "LinkedIn connected; token valid until
   <date> (60 days)". `status` and every `publish` warn when fewer than 7 days remain;
   renewal is the same command (L7: no refresh token for self-serve apps).

The poster runs inside WSL2 and the browser on Windows. WSL2 normally forwards Windows
`localhost` to WSL2 listeners; that is not vendor-documented here, so U5 checks it together
with the redirect URL.

## 11. Local state

Location: `--state-dir` > `MF_STATE_DIR` > `${XDG_STATE_HOME:-~/.local/state}/media-factory/poster/`.
Folder mode `0700`, files `0600`. It is outside every checkout on purpose: one ledger per
machine user, so runs from every checkout share one X budget.
A test asserts the default resolves outside the repository root.

### 11.1 Post record — `posts.jsonl`

Append-only JSON Lines, one event per target outcome:

```json
{"ts":"2026-11-09T10:15:02Z","package":"2026-11-09-halving","target":"fb:kotleta","network":"facebook","status":"published","post_id":"<page_post_id>","url":"https://www.facebook.com/<page_post_id>","extra":{"photo_id":"<photo_id>"}}
{"ts":"2026-11-09T10:15:40Z","package":"2026-11-09-halving","target":"ig:kotleta","network":"instagram","status":"published","post_id":"<media_id>","url":"https://www.instagram.com/p/<code>/","extra":{"staging_photo_id":"<id>","cleanup":"deleted"}}
{"ts":"2026-11-09T10:16:05Z","package":"2026-11-09-halving","target":"linkedin","network":"linkedin","status":"failed","error":"401 Unauthorized: token expired"}
```

Statuses: `published`, `failed`, `unknown`, `deleted`. No secrets, no request bodies, no
CDN or upload URLs. The latest event per (package, target) is its state. `publish` skips a
target whose state is `published` (prints its URL as "already published") and refuses one
in `unknown` unless `--force-target`; `failed` targets are retried by simply re-running.
This makes "fix the failing network and run again" safe, and a future scheduler can use the
same state.

### 11.2 X ledger — `x-ledger.jsonl` (+ `x-ledger.lock`)

```json
{"ts":"2026-11-09T10:16:20Z","month":"2026-11","rid":"<uuid4>","op":"media_upload","price":"0.015","package":"2026-11-09-halving","status":"reserved"}
{"ts":"2026-11-09T10:16:21Z","month":"2026-11","rid":"<uuid4>","status":"ok","x_id":"<media_id>"}
```

- Month = UTC calendar month of the reservation.
- Month total = sum of `price` over reservations whose latest status is `reserved` or `ok`
  (not `failed`). Money is `decimal.Decimal`, prices stored as strings.
- Estimate per X post: `X_PRICE_MEDIA_UPLOAD` if an image, plus `X_PRICE_POST_WITH_URL`
  when the text contains a URL-like token (§8.1 rules 2–3, U4), else
  `X_PRICE_POST_WITH_MEDIA` when an image is attached, else `X_PRICE_POST`.
  Defaults: text $0.015, text with link $0.200, image $0.215, image with link $0.215.
- Pre-flight: under an exclusive `fcntl.flock` on the lock file, when month total plus
  estimate exceeds `X_MONTHLY_CAP_USD`, the package is refused (exit 2) with: estimate,
  month total, cap, and "ask the operator; to publish without X, drop the x variant or use
  --targets".
- Each X request appends `reserved` under the lock before it is sent and `ok`/`failed` after.
- The ledger only knows the poster's own calls; X's Developer Console stays the source of
  truth. Recommended backstop for the operator: set the Console spending limit to $5 (X6).

At the defaults, $5 allows at least 23 X posts with an image or 333 text-only posts per
month; once U2/U3 are settled from the Console the operator can lower the two image prices.

### 11.3 Dry-run and state

Dry-run reads the ledger and record (to show the month total and "already published")
but never creates the state folder or writes either file.

### 11.4 Git-ignore entries

Existing `.gitignore` keeps `.env` and `.env.*` (`!.env.example`). The build stage adds:

```
content/
__pycache__/
*.pyc
*.local.md
```

`content/` holds the package files (unpublished texts) and the image library. State needs
no entry because it lives outside the repository. `*.local.md` holds machine-specific
notes that stay local.

## 12. Errors and redaction

- One output path: everything the CLI prints (stdout and stderr) passes through
  `Redactor.redact()`. Top-level `except Exception` prints the redacted message; a traceback
  is printed only with `--debug`, also redacted.
- Secret registry: every env-file value of 8 or more characters whose name contains
  `TOKEN`, `SECRET` or `KEY`, except `LINKEDIN_TOKEN_EXPIRES_AT` (a date `status` must show)
  — this covers all Meta, X and LinkedIn credentials, including `LINKEDIN_ACCESS_TOKEN` — plus
  runtime secrets: OAuth `state`, authorization `code`, LinkedIn `uploadUrl`, Instagram
  staging CDN URL. Each value is replaced in its raw and percent-encoded forms by
  `[redacted:NAME]`.
- Pattern masks for anything not registered: `access_token=…`, `client_secret=…`,
  `code=…`, `Bearer …`, `oauth_signature="…"`, any `Authorization:` header value, and
  32+ character base64/hex runs inside vendor error bodies.
- Vendor errors are reduced before printing: Graph `error.message`, `code`,
  `error_subcode`, `fbtrace_id`; X `title`, `detail`, `type`; LinkedIn `message`, `status`,
  `serviceErrorCode` — at most 500 characters, then redacted. Request bodies and headers are
  never printed outside dry-run, and dry-run masks secret fields.
- IDs (Page id, IG user id, post ids) are not secret and stay readable, so post URLs work.
- Files: env file stays `0600`; state files `0600`; nothing secret is written to state.
- Missing variables are named, never shown; malformed env lines are reported by number.

## 13. Offline test plan

Run from the repository root: `python3 -B -m unittest discover -s tests -t .`
(`-B` keeps `__pycache__` out of the checkout). No test reads the real env file, opens a
non-loopback socket, or needs credentials.

`tests/base.py`: sets `HOME`, `XDG_STATE_HOME`, `MF_STATE_DIR`, `MF_ENV_FILE`,
`MF_IMAGE_LIBRARY` to temporary folders; writes a fake env file whose secret values are
unique canary strings; patches `socket.socket.connect` to raise for any address other than
`127.0.0.1`; provides `FakeTransport` (scripted responses, records every request) and
tiny generated images (JPEG/PNG/GIF/WEBP headers with chosen dimensions, BMP/TIFF magic).
After each test it asserts no canary appears in captured stdout/stderr or in any file
under the state folder.

| File | Cases |
|---|---|
| `test_config.py` | path precedence (flag > `MF_ENV_FILE` > repo default, default not opened in tests); parse comments/blank/quotes/`=` in value; malformed line reported by number without content; write-back updates and appends, keeps other bytes identical, mode `0600`, atomic replace; target/profile derivation from names; missing-variable messages name only the variable |
| `test_redact.py` | canaries masked in raw and percent-encoded form inside exception text, URLs with `access_token`, `Authorization` headers, vendor error bodies; generic patterns; `--debug` traceback redacted |
| `test_package.py` | schema 1 accepted; unknown keys refused; empty text refused; id default and pattern; library vs path resolution; missing file; NFC normalisation; `meta` ignored; target/variant matching (`skipped (no variant)`, `unused variant`) |
| `test_rules.py` | X: 280 ASCII passes, 281 refused with count; Cyrillic weight 1; CJK and emoji weight 2; ZWJ sequence never under X's count; `https://` URL = 23; bare domain = max(23, length); 2 cashtags refused. Instagram: 2200/2201, 31 hashtags, 21 mentions, no image refused, PNG refused, aspect 0.79 and 1.92 refused. LinkedIn: 3000 counted on escaped text; pixel limit. Facebook: long text passes, 10 MB limit, PNG > 1 MB warning. Image sniffing reads the right dimensions. Text sent equals text validated (no truncation anywhere) |
| `test_oauth1.py` | signature equals the worked example on X's "Creating a signature" page (its published sample values, copied into the test with the page URL); header field order and quoting; JSON and multipart bodies excluded from the signature |
| `test_facebook.py` | text → `POST /v27.0/{page}/feed` form `message` + `access_token`; photo → multipart `/photos` with `source` part and `caption`; URLs from ids; delete → pre-read `GET` (200 required, else nothing is sent), `DELETE`, read-back; 404, code 100/33 and (post with 200 pre-read) code 10 count as gone, any other read-back error (190, 5xx, cut-off) is `deletion not confirmed` with its code; version from `META_GRAPH_VERSION` |
| `test_instagram.py` | full happy path request sequence and fields; status `IN_PROGRESS` then `FINISHED` with instant sleep; `ERROR`, `EXPIRED` and 5-minute timeout fail the target; staging photo deleted on success and on every failure after step 1; cleanup failure recorded and reported; `config_issue` warning |
| `test_xapi.py` | upload body (`media` base64, `media_category=tweet_image`); post body with `media_ids`; OAuth header on both; price classification (text, URL, image, image+URL); over-cap refusal happens before any request (transport saw zero calls, exit 2); reservation written before send; definite 4xx settles `failed` and is excluded; timeout stays counted; month rollover at UTC midnight; cap and prices read from env |
| `test_linkedin.py` | escaping of every reserved character; hashtag template; initializeUpload body; PUT with Bearer only to `*.linkedin.com`, refused otherwise; post body fields and both headers; id from `x-restli-id`; expired token refused in pre-flight; warning under 7 days |
| `test_login.py` | authorization URL parameters and fixed scope; callback server on `127.0.0.1` port 0 (test-only) accepts the right `state`, rejects a wrong one, handles `error`; token exchange form fields; userinfo → person URN; probe 403 → warning; env written with three variables; token value never printed |
| `test_cli.py` | partial failure: Facebook ok, Instagram raises, LinkedIn ok, X ok → four lines, exit 1, four record events; re-run skips published targets and retries the failed one; `unknown` blocks without `--force-target`; a 5xx or cut-off reply on the final publish call records `unknown` (X reservation stays counted), a 4xx stays `failed`; `check-staging` step 3 compares `/published_posts` before and after staging (a new post id or a `post_id` in the upload answer prints `NO`) and prints a 4xx as `unreadable (HTTP n, code c)`; pre-flight failure on one variant → nothing sent, exit 2; dry-run: zero transport sends, no state folder created, output contains each exact text, image facts and X estimate; `delete` refuses ids not in the record; `records` and `status` output; X runs last |

## 14. Unconfirmed facts and live checks

The build publishes nowhere except a test Page in the smoke run (results:
`docs/smoke/2026-11-09-facebook-page.md`). Checks:

| Id | Unconfirmed | Cheapest check | When / who |
|---|---|---|---|
| U1 | Staged photo URL is public, JPEG, absent from the Page's published posts; delete of an unpublished photo works with the Page token | `check-staging --page <test page> <jpeg>` on the test Page: anonymous GET of the CDN URL → 200 and `image/jpeg`; no new post in `/published_posts` after staging and no `post_id` in the upload answer (`/feed` needs `pages_read_engagement`, live 400 code 10 on 2026-11-09); `DELETE` → `success`; read-back answers does-not-exist (404, or code 100 subcode 33 for the bare photo). Publishes nothing. | Smoke stage |
| U1b | Instagram accepts that URL as `image_url` | `check-staging --page kotleta <jpeg> --ig-container ig:kotleta`: container reaches `FINISHED`; `media_publish` is never called; the container expires unpublished within 24 h. This writes an invisible container to the kotleta Instagram account, so it runs **only with the operator's explicit OK**; otherwise the first real Instagram post is the check, and the failure path (staging cleanup, other targets unaffected) contains the damage. | Smoke stage if approved |
| U2 | Price of X media upload | Operator reads the rate card / usage cost for the first X image post in the Developer Console (no API call). Set `X_PRICE_MEDIA_UPLOAD` accordingly. | After the first X image post |
| U3 | Media post billed as "with URL" | Same Console reading; set `X_PRICE_POST_WITH_MEDIA` | Same |
| U4 | What X bills as "with URL" | Conservative classification stays; Console reading after the first post with a link | When it happens |
| U5 | LinkedIn accepts `http://localhost:8765/callback`; Windows browser reaches the WSL2 listener | Operator saves the URL on the Auth tab (the portal accepts or rejects it); `login linkedin` then shows the consent screen and the callback arrives. Publishes nothing. | At LinkedIn setup |
| U6 | `/rest/*` accepts a Share-on-LinkedIn member token | Login step 7 probe (unused upload slot, nothing published) | At LinkedIn setup |
| U7 | `/rest/posts` limit equals 3000 | Conservative 3000 on the escaped text; `FIELD_LENGTH_TOO_LONG` would surface as a target error | Ongoing |
| U8 | LinkedIn post right after an image PUT succeeds without status polling | First LinkedIn image post; on error the re-run retries LinkedIn only | First LinkedIn image post |

Smoke sequence (test Page only, every post deleted; `fb:test` stands for its target):

1. `publish smoke-text.json --targets fb:test --dry-run` → check the shown request.
2. `publish smoke-text.json --targets fb:test` → URL; `delete --target fb:test --post-id …` → read-back confirms.
3. Same with `smoke-photo.json` (JPEG under 1 MB).
4. `check-staging --page test <jpeg>` (U1).
5. U1b only if the operator approved it.
6. `records` shows both posts `deleted`; `status` shows X month $0.000; the ledger file is
   absent or empty; every secret value from the env file is absent from the captured output
   (checked by count, never printed).

## 15. README section (Russian, outline for the build stage)

"Постер": what it does; one-time setup (env file, LinkedIn redirect URL and products,
`login linkedin`); writing a package (example JSON, image library); `publish --dry-run`
then `publish`; reading the summary and exit codes; `delete`, `records`, `status`;
the X cap and how to change prices or the cap; where state lives; the new env names
for `KEYS.md`.

## 16. Open items for the operator (non-blocking)

1. **U1b — Instagram container-only check on the kotleta account during smoke.** Options:
   (a) allow it: proves the Instagram path before the first real post; nothing is published
   and the container expires in 24 h (recommended); (b) skip it: the first real Instagram
   post is the proof.
2. **X image-post price until confirmed.** Options: (a) count image posts at $0.215 until
   the Console shows the real charge, then lower the setting (recommended; ≥ 23 image posts
   per month fit in $5); (b) count at $0.030 now, risking an undercount if X bills media
   posts as "with URL". Also recommended: set the X Console spending limit to $5.
3. **LinkedIn setup actions** (not a decision): add the two products and the redirect URL
   (§10), then the assistant runs `login linkedin` and relays the link.
4. Meta reminder from key collection: the app's data access needs a renewal before
   2027-02-06 (recorded on the task card; the poster does not check it).

## 17. Deferred — not currently justified

| Item | Why deferred | Trigger to build |
|---|---|---|
| Text generation (LLM call) | Addendum: variants are written in chat and approved by the operator | Operator asks; `meta` already records provenance |
| Scheduling, series spread over days (`publish_at`, scheduler) | Undecided by the operator | Decision made; schema 2 adds the field, record state already supports it |
| Delete on X, LinkedIn, Instagram | Requirement asks for Facebook at least; Instagram delete needs `instagram_manage_contents` (I7); X delete costs $0.005 (X5); LinkedIn `DELETE /rest/posts/{urn}` documented (L6) | A mistaken post the operator cannot delete in the app |
| LinkedIn ugcPosts fallback (`/v2/ugcPosts`, `/v2/assets`) | Only if U6 fails | U6 probe returns 403 |
| LinkedIn manual token path (Developer Portal token generator) | Only if U5 fails | Portal rejects the localhost URL |
| Converting PNG etc. to JPEG for Instagram | Needs an image library (not in the standard library) | Operator often supplies non-JPEG photos |
| Alt text (Instagram `alt_text`, LinkedIn `altText`, X media metadata) | Not requested | Operator asks |
| Multi-image, carousels, video, Reels, Stories, X threads, link-preview posts | Not requested | Operator asks |
| Instagram quota pre-check (`content_publishing_limit`) | Volume far below 50 per day | Daily volume grows |
| Animated GIF / chunked X upload | Images only requested | Operator asks |
| LinkedIn mentions | Need member/organization URNs | Operator asks |
| Machine-readable (`--json`) output | Text summary is enough for the assistant | A second consumer appears |
| Automatic retries of publish calls | Not idempotent; re-run covers it | — |
| Bot or web UI | Operator chose chat (decision 2) | — |

## 18. Sources (read 2026-11-08 and 2026-11-09)

Meta: [Pages API — Posts](https://developers.facebook.com/documentation/pages-api/posts) ·
[Page Photos reference v27.0](https://developers.facebook.com/docs/graph-api/reference/page/photos/) ·
[Photo reference](https://developers.facebook.com/docs/graph-api/reference/photo/) ·
[Instagram Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) ·
[IG User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) ·
[IG User media_publish](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish) ·
[IG Container](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container) ·
[IG content_publishing_limit](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit) ·
[IG Media](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media)

X: [Pricing](https://docs.x.com/x-api/getting-started/pricing) ·
[Rate card](https://developer.x.com/#pricing) ·
[Usage and Billing](https://docs.x.com/x-api/fundamentals/post-cap) ·
[Changelog](https://docs.x.com/changelog) ·
[Create Post](https://docs.x.com/x-api/posts/create-post) ·
[Manage Posts](https://docs.x.com/x-api/posts/manage-tweets/introduction) ·
[Delete Post](https://docs.x.com/x-api/posts/delete-post) ·
[Upload Media](https://docs.x.com/x-api/media/upload-media) ·
[Media introduction](https://docs.x.com/x-api/media/introduction) ·
[Media best practices](https://docs.x.com/x-api/media/quickstart/best-practices) ·
[OAuth 1.0a: authorizing a request](https://docs.x.com/fundamentals/authentication/oauth-1-0a/authorizing-a-request) ·
[OAuth 1.0a: creating a signature](https://docs.x.com/fundamentals/authentication/oauth-1-0a/creating-a-signature) ·
[Counting characters](https://docs.x.com/fundamentals/counting-characters) ·
[twitter-text config v3](https://github.com/twitter/twitter-text/blob/master/config/v3.json) ·
[RFC 5849](https://datatracker.ietf.org/doc/html/rfc5849#section-3.4.1.3.1)

LinkedIn: [Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-10) ·
[Images API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2026-10) ·
[Vector Asset API — upload](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/vector-asset-api?view=li-lms-2026-10#upload-the-image) ·
[little Text Format](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format?view=li-lms-2026-10) ·
[Post API schema](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/post-api-schema?view=li-lms-2026-10) ·
[UGC Post API](https://learn.microsoft.com/en-us/linkedin/compliance/integrations/shares/ugc-post-api) ·
[Versioning](https://learn.microsoft.com/en-us/linkedin/marketing/versioning) ·
[Migrations](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/migrations) ·
[Authorization Code Flow](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow) ·
[Share on LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin) ·
[Sign In with LinkedIn using OpenID Connect](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2)
