# Smoke test: a test Facebook Page (2026-11-09)

A live check of the poster against a test Facebook Page: publish a post, read it back,
delete it with the poster, confirm it is gone. The design's open checks U1 and U1b (§14)
were run in the same session; neither publishes anything.

**Result: PASS.** Two posts were published to the test Page, one text-only and one with an
image. Each was read back through the Graph API, deleted with the poster's `delete`
command, and confirmed gone. U1 and U1b are confirmed. One defect turned up in
`check-staging` and is described under "Defect found" below (fixed since).

Nothing was published to X, LinkedIn or Instagram. The X ledger stayed empty.

## Conventions in this document

- `fb:test` stands for the test Page's target and `<page>` for its Page id
  (`FB_PAGE_<NAME>_ID`). Facebook post ids have the form `<page>_<post>`; `<post>`,
  `<photo>` and `<container>` stand for the ids Facebook returned. No real id is recorded.
- Times are UTC: the start of each command as recorded by the runner, and the
  `created_time` values reported by Facebook.

## How it was run

- The poster was exported with `git archive` to a scratch folder and run from there under
  `env -i` with only a scratch `HOME`, `PATH`, `LANG` and `TMPDIR`:
  `python3 -B -m poster --env-file <env file> --state-dir <scratch state> …`
  The env file was passed by path, never copied, and no value was printed.
- Graph API version: `v27.0` (the default; `META_GRAPH_VERSION` not set).
- Test image: a generated solid-colour baseline JPEG, 1080×1080, 13,843 bytes
  (`smoke-test.jpg`).
- Caption on both posts: a short test caption of 28 characters.
- Packages: `smoke-2026-11-09-text` (a `facebook` variant, text only) and
  `smoke-2026-11-09-photo` (a `facebook` variant with text and `smoke-test.jpg`).
- Read-back probes were small standard-library scripts. They read the env file in memory
  and masked the token and the Page id in everything they printed.
- Secret check: every value in the env file whose name contains TOKEN, SECRET or KEY was
  counted in all captured output, both raw and URL-encoded. Every count was **0**. Only
  counts were printed.

## 1. Dry run

| Time | Command | Result |
|---|---|---|
| 07:58:48 | `publish smoke-photo.json --targets fb:test --dry-run` | exit 0, `would publish` |
| 07:58:48 | `publish smoke-text.json --targets fb:test --dry-run` | exit 0, `would publish` |

The plans shown:

```
== fb:test (facebook) ==               (smoke-photo.json)
text:
  | <caption>
  text 28 characters (Meta documents no Page post limit)
  image smoke-test.jpg: jpeg 1080x1080, 13843 bytes
  requests:
    POST https://graph.facebook.com/v27.0/<page>/photos
      header Content-Type: multipart/form-data; boundary=…
      multipart body:
        caption = <caption>
        access_token = [redacted]
        source = <file smoke-test.jpg: jpeg 1080x1080, 13843 bytes>

== fb:test (facebook) ==               (smoke-text.json)
  image: none (text-only)
  requests:
    POST https://graph.facebook.com/v27.0/<page>/feed
      header Content-Type: application/x-www-form-urlencoded
      form body:
        message = <caption>
        access_token = [redacted]
```

After both dry runs, the state folder was still empty.

## 2. Publish (test Page only)

| Time | Command | Post id | Facebook `created_time` | Result |
|---|---|---|---|---|
| 07:58:55 | `publish smoke-text.json --targets fb:test` | `<page>_<post>` | 07:58:55 | exit 0, `published` |
| 07:59:03 | `publish smoke-photo.json --targets fb:test` | `<page>_<post>` (photo `<photo>`) | 07:59:02 | exit 0, `published` |

## 3. Read back, delete, confirm gone

Read back with the Page token, using `GET /{id}?fields=id,created_time,message,is_published,permalink_url`:

| Time | Node | HTTP | Observed |
|---|---|---|---|
| 07:59:18 | text post | 200 | `is_published: true`, message equals the caption |
| 07:59:18 | photo post | 200 | `is_published: true`, message equals the caption |
| 07:59:19 | photo node (`fields=id,created_time,images`) | 200 | a 1080×1080 image exists |

Delete with the poster:

| Time | Command | Result |
|---|---|---|
| 07:59:25 | `delete --target fb:test --post-id <page>_<post>` (text) | exit 0, `deleted (read-back confirms)` |
| 07:59:30 | `delete --target fb:test --post-id <page>_<post>` (photo) | exit 0, `deleted (read-back confirms)` |

Independent confirmation that the posts are gone:

| Time | Request | HTTP | Observed |
|---|---|---|---|
| 07:59:41 | `GET <page>_<post>?fields=id` (text) | 400 | code 10, "Object does not exist, cannot be loaded due to missing permission…". The same token read this post at 07:59:18, so the post is gone. |
| 07:59:42 | `GET <page>_<post>?fields=id` (photo) | 400 | code 10, same message |
| 07:59:42 | `GET <photo>?fields=id` | 400 | code 100, subcode 33, "does not exist" |
| 07:59:53 | `GET <page>/published_posts?limit=25` | 200 | only older posts; neither test post is listed |
| 07:59:54 | `GET <page>/photos?type=uploaded&limit=25` | 200 | only older photos; the test photo is not listed |

`records --last 10` (exit 0) showed both posts `published` and then `deleted`:

```
2026-11-09T07:58:59Z  smoke-2026-11-09-text   fb:test  published  <page>_<post>  https://www.facebook.com/<page>_<post>
2026-11-09T07:59:08Z  smoke-2026-11-09-photo  fb:test  published  <page>_<post>  https://www.facebook.com/<page>_<post>
2026-11-09T07:59:30Z  smoke-2026-11-09-text   fb:test  deleted    <page>_<post>
2026-11-09T07:59:36Z  smoke-2026-11-09-photo  fb:test  deleted    <page>_<post>
```

## 4. Instagram `image_url` path (U1, U1b): publishes nothing

The design marks I8 as unconfirmed; its named check is `check-staging`. The unpublished
staging photo was placed on the test Page, so all Facebook-side writes stayed on that Page.
The container was created on the `ig:kotleta` Instagram account with its Page token.
`media_publish` was never called.

Command, started 08:00:09:
`check-staging --page test smoke-test.jpg --ig-container ig:kotleta` (exit 1, see below)

```
image: smoke-test.jpg jpeg 1080x1080, 13843 bytes
1. staged unpublished photo <photo> on fb:test
2. anonymous GET of the CDN URL (host <Facebook CDN host>): 200, image/jpeg, 14362 bytes -> OK
3. photo absent from the Page feed (last 10): NO or unreadable
4. Instagram container <container> created (media_publish is never called)
   container FINISHED; it expires unpublished after 24 hours
cleanup: staging photo <photo> deleted (read-back confirms)
check-staging FAILED
```

Step 3 failed only because the Page token cannot read `/feed`. The request gets HTTP 400
with code 10: "requires the 'pages_read_engagement' permission or the 'Page Public Content
Access' feature". This happened at 07:59:52 and again at 08:00:52. In the same session
`/posts` and `/published_posts` were readable (200).

To settle the feed question, a follow-up probe used the poster's own `stage_photo` and
`delete_node` on the test Page:

| Time | Step | Result |
|---|---|---|
| 08:01:11 | stage unpublished photo `<photo>` | created |
| 08:01:12 | `GET <page>/posts?limit=10` | 200, staged photo absent |
| 08:01:12 | `GET <page>/published_posts?limit=10` | 200, staged photo absent |
| 08:01:15 | delete and read back | `deleted (read-back confirms)` |

Further read-only checks at 08:00:51–08:00:52:

- `GET <container>?fields=status_code,status` returned 200 with `status_code: FINISHED`
  ("ready to be published"). It is not `PUBLISHED`.
- `GET <ig user>/media?limit=3` returned 200 with only older media, so nothing new was
  published.

| Id | Claim | Label | Evidence |
|---|---|---|---|
| U1 | The staged photo's CDN URL is public and JPEG | CONFIRMED | anonymous GET returned 200 and `image/jpeg` (14,362 bytes; Facebook re-encodes the upload) |
| U1 | The staged photo is absent from the Page's posts | CONFIRMED | not in `/posts` or `/published_posts` while it existed (08:01:12). `/feed` itself is unreadable with this token. |
| U1 | Deleting an unpublished photo works with the Page token | CONFIRMED | `success`, then the read-back fails (08:00:27 and 08:01:15) |
| U1b | Instagram accepts the staged URL as `image_url` | CONFIRMED | the container reached `FINISHED` |

Cleanup: both staging photos were deleted and their read-back confirms it. The Graph API
offers no delete for an unpublished Instagram container. The container stays invisible and
expires unpublished 24 hours after creation.

## 5. Final state

`status` (exit 0):

- X 2026-11: spent $0.000 of $5.00.
- LinkedIn token: none yet.
- The Facebook and Instagram targets configured in the env file were ready; `linkedin` was
  missing its three login variables.

The state folder held only `posts.jsonl` and `posts.lock`, both mode 600. There was no X
ledger file.

## Defect found

`check-staging` step 3 read `GET /{page_id}/feed`. Page tokens with `pages_manage_posts`
but without `pages_read_engagement` cannot read that edge, so `check-staging` reported
`NO or unreadable` and exited 1 even when the image path worked.
`/{page_id}/published_posts` is readable with the same token and answers the same question.
The poster now compares two `/published_posts` listings (design §6).

## Notes

- After a delete, a deleted post answers code 10, which also covers missing permission. The
  poster therefore accepts code 10 as "gone" only after a 200 pre-read of the same post with
  the same token (design §9.1). In this run the same token had read each post 20 seconds
  earlier.
- In `permalink_url`, Facebook returns a different id from the `<page>` prefix of the post
  id. The poster's `https://www.facebook.com/<page>_<post>` URL was not opened in a browser.
