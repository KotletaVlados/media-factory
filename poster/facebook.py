"""Facebook Page: text post, photo post, delete, and unpublished staging photos (design §9.1, §3.5)."""

from __future__ import annotations

import os
import urllib.parse

from poster.context import Ctx, Result
from poster.http import (ApiError, FilePart, Request, TransportError, check, describe_status,
                         form_request, graph_error_codes, multipart_request)
from poster.rules import sniff

GRAPH = "https://graph.facebook.com"


def page_creds(env: dict, name: str) -> tuple[str, str]:
    up = name.upper()
    return env[f"FB_PAGE_{up}_ID"], env[f"FB_PAGE_{up}_TOKEN"]


def graph_url(ctx: Ctx, *parts: str, **query) -> str:
    path = "/".join(urllib.parse.quote(str(p), safe="") for p in parts)
    url = f"{GRAPH}/{ctx.settings.graph_version}/{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def image_part(path: str, field: str = "source") -> FilePart:
    info = sniff(path)
    with open(path, "rb") as fh:
        data = fh.read()
    return FilePart(field, os.path.basename(path), info.mime, data, info.describe())


def post_url(page_post_id: str) -> str:
    return f"https://www.facebook.com/{page_post_id}"   # F8


def publish(variant, target, ctx: Ctx) -> Result:
    page_id, token = page_creds(ctx.env, target.name)
    result = Result(target.id, "facebook", "failed")
    if variant.image_path:
        req = multipart_request("POST", graph_url(ctx, page_id, "photos"),
                                {"caption": variant.text, "access_token": token},
                                [image_part(variant.image_path)])
        what = "Facebook photo post"
    else:
        req = form_request("POST", graph_url(ctx, page_id, "feed"),
                           {"message": variant.text, "access_token": token})
        what = "Facebook post"
    try:
        data = check(ctx.send(req), what)
    except TransportError as exc:
        result.status = "unknown"
        result.error = (f"{exc}; the post may exist — look at the Page before re-running "
                        f"with --force-target {target.id}")
        return result
    except ApiError as exc:
        result.error = str(exc)
        if exc.uncertain:   # 5xx: Facebook may have created the post before failing
            result.status = "unknown"
            result.error += (f"; the post may exist — look at the Page before re-running "
                             f"with --force-target {target.id}")
        return result
    if variant.image_path:
        post_id = data.get("post_id")
        result.extra["photo_id"] = data.get("id")
        if not post_id:
            result.status = "unknown"
            result.error = "Facebook returned no post_id for the photo; look at the Page"
            return result
    else:
        post_id = data.get("id")
        if not post_id:
            result.status = "unknown"
            result.error = "Facebook returned no post id; look at the Page"
            return result
    result.status = "published"
    result.post_id = str(post_id)
    result.url = post_url(result.post_id)
    return result


def _get_id(ctx: Ctx, node_id: str, token: str):
    """GET the node with fields=id. Returns (response, None) or (None, transport error text)."""
    try:
        return ctx.send(Request("GET", graph_url(ctx, node_id, fields="id", access_token=token),
                                secret_fields=("access_token",))), None
    except TransportError as exc:
        return None, str(exc)


def _read_back(ctx: Ctx, node_id: str, token: str, readable_before: bool) -> tuple[bool, str]:
    """Read a deleted node back. Gone is: HTTP 404, or code 100 with error_subcode 33 (a bare
    node answers this way, smoke 2026-11-09); for a Page post whose pre-read answered 200 with
    the same token, also code 10 (the smoke run saw deleted Page posts answer HTTP 400, code 10
    "Object does not exist, cannot be loaded due to missing permission"). Any other error
    (190, a rate limit, a 5xx, a cut-off) proves nothing. Returns (gone, reason)."""
    resp, failure = _get_id(ctx, node_id, token)
    if resp is None:
        return False, f"deletion not confirmed: read-back failed ({failure})"
    if resp.ok:
        return False, "read-back still finds it"
    code, subcode = graph_error_codes(resp)
    if resp.status == 404 or (code == 100 and subcode == 33) or (readable_before and code == 10):
        return True, ""
    return False, f"deletion not confirmed: read-back answered {describe_status(resp)}"


def delete_node(ctx: Ctx, node_id: str, token: str, what: str,
                pre_read: bool = False) -> tuple[bool, str]:
    """DELETE a post or photo, then read it back. Returns (gone, message). With pre_read, the
    node is first read with the same token and must answer 200: only then can a code-10
    read-back after the DELETE mean "gone" instead of "no permission"."""
    if pre_read:
        resp, failure = _get_id(ctx, node_id, token)
        if resp is None:
            return False, f"delete {what}: not deleted, pre-read failed ({failure})"
        if not resp.ok:
            return False, (f"delete {what}: not deleted, the {what} cannot be read with this "
                           f"token first ({describe_status(resp)})")
    req = Request("DELETE", graph_url(ctx, node_id, access_token=token),
                  secret_fields=("access_token",))
    try:
        data = check(ctx.send(req), f"delete {what}")
    except (ApiError, TransportError) as exc:
        return False, str(exc)
    if data.get("success") is not True:
        return False, f"delete {what}: Facebook did not answer success"
    gone, reason = _read_back(ctx, node_id, token, pre_read)
    if not gone:
        return False, f"delete {what}: {reason}"
    return True, "deleted (read-back confirms)"


def stage_photo(ctx: Ctx, page_id: str, token: str, path: str) -> str:
    """Upload an unpublished photo (published=false, F5); returns its photo id."""
    return stage_photo_answer(ctx, page_id, token, path)["id"]


def stage_photo_answer(ctx: Ctx, page_id: str, token: str, path: str) -> dict:
    """Same upload; returns the answer ({"id": photo id, ...}). A published photo answers with
    a post_id too (F2), an unpublished one must not."""
    req = multipart_request("POST", graph_url(ctx, page_id, "photos"),
                            {"published": "false", "access_token": token}, [image_part(path)])
    data = check(ctx.send(req), "stage unpublished photo")
    if not data.get("id"):
        raise ApiError(0, "stage unpublished photo: no photo id returned")
    return {**data, "id": str(data["id"])}


def staged_image_url(ctx: Ctx, photo_id: str, token: str) -> str:
    """The largest `images[].source` of a photo (F6)."""
    req = Request("GET", graph_url(ctx, photo_id, fields="images", access_token=token),
                  secret_fields=("access_token",))
    data = check(ctx.send(req), "read staged photo")
    images = [i for i in data.get("images") or [] if isinstance(i, dict) and i.get("source")]
    if not images:
        raise ApiError(0, "read staged photo: no images[].source returned")
    best = max(images, key=lambda i: int(i.get("width") or 0))
    url = str(best["source"])
    ctx.redactor.add("STAGING_URL", url)
    return url
