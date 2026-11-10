"""X API v2 with OAuth 1.0a user context: media upload and create post (design §9.3).

Every X request is reserved in the monthly ledger before it is sent (§11.2).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import urllib.parse
from decimal import Decimal

from poster.context import Ctx, Result
from poster.http import ApiError, TransportError, check, json_request, UPLOAD_TIMEOUT
from poster.rules import sniff, x_has_url
from poster.state import BudgetExceeded

UPLOAD_URL = "https://api.x.com/2/media/upload"
TWEETS_URL = "https://api.x.com/2/tweets"


def pct(value: str) -> str:
    """RFC 3986 percent-encoding as X's "Percent encoding parameters" page requires."""
    return urllib.parse.quote(str(value), safe="-._~")


def make_nonce() -> str:
    return re.sub(r"\W", "", base64.b64encode(secrets.token_bytes(32)).decode())


def oauth1_header(method: str, url: str, consumer_key: str, consumer_secret: str,
                  token: str, token_secret: str, *, form: dict | None = None,
                  nonce: str | None = None, timestamp: str | None = None) -> str:
    """HMAC-SHA1 OAuth 1.0a header (X4). Only query and form-encoded body parameters are
    signed; JSON and multipart bodies are not (RFC 5849 §3.4.1.3.1)."""
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or make_nonce(),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    parts = urllib.parse.urlsplit(url)
    base_url = urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                                        "", ""))
    params = list(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
    params += list((form or {}).items())
    params += list(oauth.items())
    encoded = sorted((pct(k), pct(v)) for k, v in params)
    param_string = "&".join(f"{k}={v}" for k, v in encoded)
    base = "&".join([method.upper(), pct(base_url), pct(param_string)])
    key = f"{pct(consumer_secret)}&{pct(token_secret)}"
    signature = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest())
    oauth["oauth_signature"] = signature.decode()
    return "OAuth " + ", ".join(f'{pct(k)}="{pct(v)}"' for k, v in sorted(oauth.items()))


def price_items(text: str, has_image: bool, settings) -> list[tuple[str, Decimal]]:
    """Per-request prices for one X post (§11.2): upload (if image) + one post price."""
    items: list[tuple[str, Decimal]] = []
    if has_image:
        items.append(("media_upload", settings.price_media_upload))
    if x_has_url(text):
        items.append(("post_with_url", settings.price_post_with_url))
    elif has_image:
        items.append(("post_with_media", settings.price_post_with_media))
    else:
        items.append(("post", settings.price_post))
    return items


def estimate(text: str, has_image: bool, settings) -> Decimal:
    return sum((p for _, p in price_items(text, has_image, settings)), Decimal("0"))


def _auth(ctx: Ctx, method: str, url: str) -> dict:
    env = ctx.env
    return {"Authorization": oauth1_header(method, url, env["X_API_KEY"], env["X_API_SECRET"],
                                           env["X_ACCESS_TOKEN"], env["X_ACCESS_SECRET"])}


def publish(variant, target, ctx: Ctx) -> Result:
    result = Result(target.id, "x", "failed")
    has_image = bool(variant.image_path)
    items = price_items(variant.text, has_image, ctx.settings)
    try:
        rids = ctx.ledger.reserve(items, ctx.package_id, ctx.settings.cap)
    except BudgetExceeded as exc:
        result.error = str(exc)
        return result
    cost = sum((p for _, p in items), Decimal("0"))
    result.extra["estimate_usd"] = f"{cost:.3f}"
    post_rid = rids[-1]
    media_id = None

    if has_image:
        upload_rid = rids[0]
        with open(variant.image_path, "rb") as fh:
            raw = fh.read()
        info = sniff(variant.image_path)
        body = {"media": base64.b64encode(raw).decode(), "media_category": "tweet_image"}
        shown = {"media": f"<base64 of {len(raw)} bytes from {os.path.basename(variant.image_path)}"
                          f" ({info.describe()})>", "media_category": "tweet_image"}
        req = json_request("POST", UPLOAD_URL, body, display=shown,
                           headers=_auth(ctx, "POST", UPLOAD_URL), timeout=UPLOAD_TIMEOUT)
        try:
            data = check(ctx.send(req), "X media upload").get("data") or {}
        except TransportError as exc:
            # may have been billed: the upload reservation stays counted
            ctx.ledger.settle(post_rid, "failed", note="not sent")
            result.error = f"X media upload: {exc}; nothing was posted"
            return result
        except ApiError as exc:
            ctx.ledger.settle(upload_rid, "failed")
            ctx.ledger.settle(post_rid, "failed", note="not sent")
            result.error = str(exc)
            return result
        media_id = data.get("id")
        state = (data.get("processing_info") or {}).get("state")
        if not media_id or (state and state != "succeeded"):
            ctx.ledger.settle(upload_rid, "ok", x_id=media_id)
            ctx.ledger.settle(post_rid, "failed", note="not sent")
            result.error = ("X media upload returned no media id" if not media_id else
                            f"X media upload is still processing (state {state}); nothing was posted")
            return result
        ctx.ledger.settle(upload_rid, "ok", x_id=str(media_id))

    body = {"text": variant.text}
    if media_id:
        body["media"] = {"media_ids": [str(media_id)]}
    req = json_request("POST", TWEETS_URL, body, headers=_auth(ctx, "POST", TWEETS_URL))
    try:
        data = check(ctx.send(req), "X create post").get("data") or {}
    except TransportError as exc:
        result.status = "unknown"
        result.error = (f"{exc}; the post may exist — look at the X account before re-running "
                        f"with --force-target {target.id}")
        return result   # reservation stays counted
    except ApiError as exc:
        result.error = str(exc)
        if exc.uncertain:   # 5xx: X may have posted (and billed) before failing
            result.status = "unknown"
            result.error += (f"; the post may exist — look at the X account before re-running "
                             f"with --force-target {target.id}")
            return result   # reservation stays counted
        ctx.ledger.settle(post_rid, "failed")
        return result
    post_id = data.get("id")
    ctx.ledger.settle(post_rid, "ok", x_id=str(post_id) if post_id else None)
    if not post_id:
        result.status = "unknown"
        result.error = "X returned no post id; look at the account"
        return result
    result.status = "published"
    result.post_id = str(post_id)
    result.url = f"https://x.com/i/web/status/{post_id}"   # X12
    return result
