"""Instagram business account: staging -> container -> status -> publish -> permalink ->
cleanup (design §9.2). The image reaches Instagram as an unpublished photo on the linked
Page whose CDN URL becomes `image_url` (decision (a), §3.5)."""

from __future__ import annotations

from poster import facebook
from poster.context import Ctx, Result
from poster.http import ApiError, Request, TransportError, check, form_request

POLL_INTERVAL = 60   # I5: "once per minute"
POLL_MAX = 5         # I5: "for no more than 5 minutes"


def ig_user_id(env: dict, name: str) -> str:
    return env[f"IG_{name.upper()}_USER_ID"]


def create_container(ctx: Ctx, ig_id: str, token: str, image_url: str, caption: str | None) -> str:
    fields = {"image_url": image_url, "access_token": token}
    if caption is not None:
        fields["caption"] = caption
    data = check(ctx.send(form_request("POST", facebook.graph_url(ctx, ig_id, "media"), fields)),
                 "Instagram container")
    if not data.get("id"):
        raise ApiError(0, "Instagram container: no id returned")
    return str(data["id"])


def wait_finished(ctx: Ctx, container_id: str, token: str) -> None:
    """Check status now, then once per minute for at most 5 minutes (I5)."""
    for attempt in range(POLL_MAX + 1):
        if attempt:
            ctx.sleep(POLL_INTERVAL)
        req = Request("GET", facebook.graph_url(ctx, container_id, fields="status_code,status",
                                                access_token=token),
                      secret_fields=("access_token",))
        data = check(ctx.send(req), "Instagram container status")
        code = data.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            detail = data.get("status")
            raise ApiError(0, f"Instagram container {code}" + (f": {detail}" if detail else ""))
    raise ApiError(0, f"Instagram container not FINISHED after {POLL_MAX} minutes")


def publish(variant, target, ctx: Ctx) -> Result:
    result = Result(target.id, "instagram", "failed")
    if not variant.image_path:   # pre-flight refuses this already; defence in depth
        result.error = "Instagram needs an image; this variant has none"
        return result
    page_id, token = facebook.page_creds(ctx.env, target.name)
    ig_id = ig_user_id(ctx.env, target.name)
    photo_id = None
    try:
        photo_id = facebook.stage_photo(ctx, page_id, token, variant.image_path)
        result.extra["staging_photo_id"] = photo_id
        image_url = facebook.staged_image_url(ctx, photo_id, token)
        container_id = create_container(ctx, ig_id, token, image_url, variant.text)
        wait_finished(ctx, container_id, token)
        req = form_request("POST", facebook.graph_url(ctx, ig_id, "media_publish"),
                           {"creation_id": container_id, "access_token": token})
        try:
            data = check(ctx.send(req), "Instagram publish")
        except (TransportError, ApiError) as exc:
            if isinstance(exc, ApiError) and not exc.uncertain:
                raise   # 4xx: a definite refusal, recorded as failed below
            result.status = "unknown"
            result.error = (f"{exc}; the post may exist — look at the Instagram account before "
                            f"re-running with --force-target {target.id}")
            return result
        media_id = data.get("id")
        if not media_id:
            result.status = "unknown"
            result.error = "Instagram publish returned no media id; look at the account"
            return result
        result.status = "published"
        result.post_id = str(media_id)
        issue = data.get("config_issue")
        if issue:
            result.warnings.append(f"Instagram config_issue: {issue}")
        try:
            link = check(ctx.send(Request(
                "GET", facebook.graph_url(ctx, media_id, fields="permalink", access_token=token),
                secret_fields=("access_token",))), "Instagram permalink")
            result.url = link.get("permalink")
        except (ApiError, TransportError) as exc:
            result.warnings.append(f"published, but the permalink could not be read: {exc}")
        return result
    except (ApiError, TransportError) as exc:
        result.status = "failed"
        result.error = str(exc)
        return result
    finally:
        if photo_id:
            gone, message = facebook.delete_node(ctx, photo_id, token, "staging photo")
            result.extra["cleanup"] = "deleted" if gone else "failed"
            if gone:
                result.note = "staging photo removed"
            else:
                result.warnings.append(
                    f"staging photo {photo_id} was not removed ({message}); Meta deletes "
                    "unpublished photos after about 24 hours")
