"""Photo upload into photo-lane stock folders: POST /files/photos, GET /photo, the Files tab
(design authoring.md §6, §13, §14.1; acceptance of slice A, §15.1)."""

from __future__ import annotations

import glob
import hashlib
import io
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import unittest
import urllib.parse
from unittest import mock

from factory.authoring import photos
from factory.panel import server
from factory.panel import strings as S
from tests import panel_fixture as pf
from tests.base import CANARIES, REPO_ROOT


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def eighteen() -> list:
    """(name, original, type): 6 EXIF-6 JPEGs, 6 PNGs, 6 WebPs, all distinct."""
    out = []
    for k in range(6):
        out.append((f"IMG_{k:04d}.jpg", pf.make_exif6(64 + 8 * k, 48, k), "image/jpeg"))
        out.append((f"scan-{k}.png", pf.make_png(24 + k, 16, k), "image/png"))
        out.append((f"web-{k}.webp", pf.make_webp(k), "image/webp"))
    return out


class PhotoCase(pf.PanelCase):
    THUMB = pf.make_photo(48, 64, 7)
    VIEW = pf.make_photo(96, 128, 8)

    def upload(self, params: dict, body: bytes | None, *, ctype: str = "image/jpeg",
               csrf: str | None = "ok", origin: str | None = "ok", host: str | None = None,
               length: str | bytes | None = None):
        headers = {"Content-Type": ctype}
        if csrf is not None:
            headers["X-CSRF-Token"] = self.srv.panel.csrf if csrf == "ok" else csrf
        if origin is not None:
            headers["Origin"] = f"http://{self.host}" if origin == "ok" else origin
        if length is not None:
            headers["Content-Length"] = length
        status, headers, data = self.request("POST", "/files/photos?" + urllib.parse.urlencode(
            params), body=body, headers=headers, host=host)
        if headers.get("content-type", "").startswith("application/json"):
            self.outputs.append(data.decode("utf-8"))
            return status, headers, json.loads(data.decode("utf-8"))
        return status, headers, data

    def full_upload(self, folder: str, orig: bytes, ctype: str, name: str) -> str:
        status, _, answer = self.upload({"folder": folder, "kind": "orig"}, orig, ctype=ctype)
        self.assertEqual(status, 200, answer)
        pid = answer["id"]
        if answer["dup"]:
            return pid
        status, _, answer = self.upload({"folder": folder, "kind": "thumb", "id": pid}, self.THUMB)
        self.assertEqual((status, answer), (200, {"id": pid, "ok": True}))
        status, _, answer = self.upload({"folder": folder, "kind": "view", "id": pid, "w": 96,
                                         "h": 128, "name": name}, self.VIEW)
        self.assertEqual((status, answer), (200, {"id": pid, "ok": True}))
        return pid

    def photos_dir(self, folder: str = "city") -> str:
        return os.path.join(self.fx.paths.stock, folder, "photos")

    def tree(self) -> dict:
        """Every file under the fixture root and the scratch root, with its hash."""
        out = {}
        for top in (self.fx.root, self.root):
            for dirpath, _, files in os.walk(top):
                for f in files:
                    path = os.path.join(dirpath, f)
                    if not os.path.islink(path):
                        out[path] = self.file_hash(path)
        return out

    def temps(self) -> list:
        return glob.glob(os.path.join(self.fx.paths.stock, "*", "photos", photos.TMP_PREFIX + "*"))


class UploadTest(PhotoCase):
    def test_eighteen_images_are_stored_byte_identical_then_answer_dup(self):
        images = eighteen()
        ids = {}
        for name, data, ctype in images:
            ids[name] = self.full_upload("city", data, ctype, name)
        self.assertEqual(len(set(ids.values())), 18)
        rows = photos.read_index(self.photos_dir())
        self.assertEqual(len(rows), 18)
        self.assertEqual([r["name"] for r in rows], [n for n, _, _ in images])
        for name, data, ctype in images:
            pid = ids[name]
            self.assertEqual(pid, "p-" + sha(data)[:16])
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[ctype]
            orig = os.path.join(self.photos_dir(), f"{pid}.{ext}")
            self.assertEqual(self.file_hash(orig), sha(data), name)
            self.assertEqual(self.file_hash(os.path.join(self.photos_dir(), "thumb", f"{pid}.jpg")),
                             sha(self.THUMB))
            self.assertEqual(self.file_hash(os.path.join(self.photos_dir(), "view", f"{pid}.jpg")),
                             sha(self.VIEW))
            row = next(r for r in rows if r["id"] == pid)
            self.assertEqual((row["ext"], row["bytes"], row["w"], row["h"], row["ts"]),
                             (ext, len(data), 96, 128, "2026-11-11T09:40:00Z"))
            self.assertEqual(os.stat(orig).st_mode & 0o777, 0o600)
        for sub in ("", "thumb", "view"):
            self.assertEqual(os.stat(os.path.join(self.photos_dir(), sub)).st_mode & 0o777, 0o700)
        before = self.tree()
        for name, data, ctype in images:
            status, _, answer = self.upload({"folder": "city", "kind": "orig"}, data, ctype=ctype)
            self.assertEqual((status, answer), (200, {"id": ids[name], "dup": True}))
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.temps(), [])

    def test_heic_and_text_bodies_are_415_and_leave_nothing(self):
        self.full_upload("city", pf.make_photo(32, 32, 1), "image/jpeg", "a.jpg")
        before = self.tree()
        for body in (pf.HEIC_HEAD, b"hello, not an image",
                     b"<html><body>" + CANARIES["X_API_KEY"].encode() + b"</body></html>"):
            status, _, answer = self.upload({"folder": "city", "kind": "orig"}, body)
            self.assertEqual(status, 415, body[:20])
            self.assertIn("HEIC", answer["error"])
        for kind in ("thumb", "view"):
            pid = photos.read_index(self.photos_dir())[0]["id"]
            for body in (pf.make_png(8, 8, 1), b"text"):
                status, _, answer = self.upload({"folder": "city", "kind": kind, "id": pid}, body)
                self.assertEqual(status, 415, (kind, body[:8]))
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.temps(), [])

    def test_an_upload_cut_after_orig_leaves_no_row_and_a_repeat_completes_it(self):
        data = pf.make_exif6(80, 60, 3)
        status, _, answer = self.upload({"folder": "city", "kind": "orig"}, data)
        self.assertEqual((status, answer["dup"]), (200, False))
        pid = answer["id"]
        self.assertEqual(photos.read_index(self.photos_dir()), [])
        self.assertNotIn(pid, self.get("/files?folder=city")[2])
        # the repeat: the stored but unlisted original is not a duplicate
        self.assertEqual(self.full_upload("city", data, "image/jpeg", "again.jpg"), pid)
        self.assertEqual([r["id"] for r in photos.read_index(self.photos_dir())], [pid])
        self.assertIn(pid, self.get("/files?folder=city")[2])

    def test_a_view_before_its_thumb_and_a_thumb_without_orig_are_refused(self):
        status, _, answer = self.upload({"folder": "city", "kind": "orig"}, pf.make_photo(16, 16, 2))
        pid = answer["id"]
        status, _, answer = self.upload({"folder": "city", "kind": "view", "id": pid}, self.VIEW)
        self.assertEqual(status, 409)
        status, _, _ = self.upload({"folder": "city", "kind": "thumb", "id": "p-" + "0" * 16},
                                   self.THUMB)
        self.assertEqual(status, 404)
        self.assertEqual(photos.read_index(self.photos_dir()), [])

    def test_a_body_cut_mid_stream_is_400_and_leaves_no_temp_file(self):
        path = "/files/photos?folder=city&kind=orig"
        with socket.create_connection(("127.0.0.1", self.srv.port), timeout=30) as conn:
            conn.sendall((f"POST {path} HTTP/1.1\r\nHost: {self.host}\r\n"
                          f"Origin: http://{self.host}\r\nContent-Type: image/jpeg\r\n"
                          f"X-CSRF-Token: {self.srv.panel.csrf}\r\nContent-Length: 100000\r\n\r\n"
                          ).encode() + pf.make_photo(16, 16, 1))
            conn.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := conn.recv(65536):
                data += chunk
        self.assertTrue(data.startswith(b"HTTP/1.0 400"), data[:40])
        self.assertIn("загрузка оборвалась", data.decode("utf-8"))
        self.assertEqual(self.temps(), [])
        self.assertEqual(sorted(os.listdir(self.photos_dir())), ["thumb", "view"])
        self.assertEqual(self.get("/files")[0], 200)   # the panel still answers

    def test_names_are_data_never_paths(self):
        data = pf.make_photo(24, 24, 9)
        outside = os.path.join(self.fx.paths.content, "draft.json")
        pid = self.full_upload("city", data, "image/jpeg", "../../draft.json")
        self.assertFalse(os.path.exists(outside))
        row = photos.read_index(self.photos_dir())[0]
        self.assertEqual(row["name"], "draft.json")
        self.assertEqual(photos.clean_name("x\x00\x1b[31m‮evil.jpg", "f"), "x[31mevil.jpg")
        self.assertEqual(len(photos.clean_name("n" * 400, "f")), 120)
        self.assertEqual(photos.clean_name("a/b\\c.jpg", "f"), "c.jpg")
        self.assertEqual(photos.clean_name("  /  ", "fallback.jpg"), "fallback.jpg")
        self.assertEqual(row["id"], pid)

    def test_concurrent_views_of_one_photo_write_one_index_row(self):
        status, _, answer = self.upload({"folder": "city", "kind": "orig"}, pf.make_photo(40, 30, 4))
        pid = answer["id"]
        self.upload({"folder": "city", "kind": "thumb", "id": pid}, self.THUMB)
        results = []

        def view():
            results.append(self.upload({"folder": "city", "kind": "view", "id": pid,
                                        "name": "same.jpg"}, self.VIEW)[0])
        threads = [threading.Thread(target=view) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(results, [200] * 6)
        self.assertEqual(len(photos.read_index(self.photos_dir())), 1)
        with open(os.path.join(self.photos_dir(), "index.jsonl"), encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 1)

    def test_more_than_two_thousand_photos_are_refused(self):
        os.makedirs(os.path.join(self.photos_dir(), "thumb"), 0o700)
        os.makedirs(os.path.join(self.photos_dir(), "view"), 0o700)
        rows = [{"id": f"p-{k:016x}", "name": f"{k}.jpg", "ext": "jpg", "bytes": 10, "w": 4,
                 "h": 3, "ts": "2026-11-11T00:00:00Z"} for k in range(photos.MAX_PHOTOS)]
        pf.poster_state.append_jsonl(os.path.join(self.photos_dir(), "index.jsonl"), rows)
        before = self.tree()
        status, _, answer = self.upload({"folder": "city", "kind": "orig"}, pf.make_photo(8, 8, 1))
        self.assertEqual(status, 409)
        self.assertIn("2 000", answer["error"])
        self.assertEqual(self.tree(), before)

    def test_low_disk_space_is_507_before_any_byte_is_stored(self):
        real = os.statvfs

        class Small:
            f_bavail, f_frsize = 1000, 4096
        with mock.patch.object(photos.os, "statvfs", side_effect=lambda p: Small()):
            status, _, answer = self.upload({"folder": "city", "kind": "orig"}, pf.make_photo(8, 8, 1))
        self.assertIs(os.statvfs, real)
        self.assertEqual(status, 507)
        self.assertIn("1 ГБ", answer["error"])
        self.assertEqual(sorted(os.listdir(self.photos_dir())), ["thumb", "view"])

    def test_an_unexpected_error_is_a_redacted_500_and_the_temp_file_goes(self):
        err = RuntimeError("sniff broke with " + CANARIES["FB_PAGE_DEMO_TOKEN"])
        with mock.patch.object(photos.poster_rules, "sniff", side_effect=err):
            status, headers, answer = self.upload({"folder": "city", "kind": "orig"},
                                                  pf.make_photo(8, 8, 1))
        self.assertEqual(status, 500)
        self.assertEqual(answer, {"error": "ошибка панели при загрузке"})
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertIn("panel: upload: RuntimeError: sniff broke with [redacted:FB_PAGE_DEMO_TOKEN]",
                      self.log.getvalue())
        self.assertNotIn(CANARIES["FB_PAGE_DEMO_TOKEN"], self.log.getvalue())
        self.assertEqual(self.temps(), [])
        self.assertEqual(self.get("/files")[0], 200)
        self.assertEqual(self.upload({"folder": "city", "kind": "orig"},
                                     pf.make_photo(8, 8, 1))[0], 200)


class UploadGuardTest(PhotoCase):
    """§13 rows for uploads: CSRF, Origin, Host, sizes, types, traversal, symlinks."""

    BODY = pf.make_photo(16, 16, 5)

    def assert_refused(self, status, expected, before):
        self.assertEqual(status, expected)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.temps(), [])

    def test_csrf_header_and_origin_are_required(self):
        before = self.tree()
        params = {"folder": "city", "kind": "orig"}
        for csrf in (None, "", "0" * 64, self.srv.panel.csrf[:-1]):
            status, headers, answer = self.upload(params, self.BODY, csrf=csrf)
            self.assert_refused(status, 403, before)
            self.assertEqual(answer["error"], "запрос отклонён: обновите страницу панели")
            self.assertTrue(headers["content-type"].startswith("application/json"))
        for origin in (None, "http://evil.example", f"http://evil.example:{self.srv.port}",
                       "null", f"https://{self.host}", f"http://localhost:{self.srv.port}"):
            status, _, _ = self.upload(params, self.BODY, origin=origin)
            self.assert_refused(status, 403, before)
        # the form token in a form field does not count for a raw body
        status, _, _ = self.upload(params, b"csrf=" + self.srv.panel.csrf.encode(), csrf=None,
                                   ctype="application/x-www-form-urlencoded")
        self.assertIn(status, (403, 415))
        self.assertEqual(self.tree(), before)

    def test_wrong_host_is_421_on_upload_and_photo(self):
        pid = self.full_upload("city", self.BODY, "image/jpeg", "a.jpg")
        before = self.tree()
        for host in ("evil.example", f"evil.example:{self.srv.port}", ""):
            status, _, _ = self.upload({"folder": "city", "kind": "orig"},
                                       pf.make_photo(8, 8, 2), host=host)
            self.assert_refused(status, 421, before)
            status, _, data = self.request("GET", f"/photo?folder=city&id={pid}&v=orig", host=host)
            self.assertEqual(status, 421)
            self.assertNotEqual(data, self.BODY)

    def test_sizes_and_lengths(self):
        before = self.tree()
        cases = [({"kind": "orig"}, str(25 * 1024 * 1024 + 1), 413),
                 ({"kind": "orig"}, str(26 * 1024 * 1024), 413),
                 ({"kind": "thumb", "id": "p-" + "0" * 16}, str(2 * 1024 * 1024 + 1), 413),
                 ({"kind": "view", "id": "p-" + "0" * 16}, str(3 * 1024 * 1024), 413),
                 ({"kind": "nope"}, str(3 * 1024 * 1024), 413),
                 ({"kind": "orig"}, "abc", 400), ({"kind": "orig"}, "-5", 400),
                 ({"kind": "orig"}, "5_000", 400), ({"kind": "orig"}, "+5", 400),
                 ({"kind": "orig"}, "٥".encode("utf-8"), 400), ({"kind": "orig"}, "1e3", 400),
                 ({"kind": "orig"}, "9" * 19, 400), ({"kind": "orig"}, "9" * 18, 413)]
        for params, length, expected in cases:
            # headers only: the refusal comes before any body byte is read
            status, headers, _ = self.upload(dict(params, folder="city"), None, length=length)
            self.assert_refused(status, expected, before)
            self.assertEqual(headers.get("connection"), "close")
        status, _, _ = self.upload({"folder": "city", "kind": "orig"}, None)
        self.assert_refused(status, 411, before)
        # int() alone would take these; the panel takes ASCII digits only
        for raw in ("٥", "5_000", " 5", "5 ", "+5", "", None):
            self.assertIsNone(server.declared_length(raw), raw)
        self.assertEqual(server.declared_length("0"), 0)
        # exactly at the thumb limit is accepted by the length check (then sniffed)
        status, _, _ = self.upload({"folder": "city", "kind": "orig"}, b"x" * (2 * 1024 * 1024))
        self.assertEqual(status, 415)

    def test_media_types(self):
        before = self.tree()
        for kind, ctype in (("orig", "text/html"), ("orig", "image/heic"), ("orig", "image/gif"),
                            ("orig", "application/octet-stream"), ("orig", ""),
                            ("thumb", "image/png"), ("view", "image/webp")):
            params = {"folder": "city", "kind": kind, "id": "p-" + "0" * 16}
            status, _, answer = self.upload(params, self.BODY, ctype=ctype)
            self.assert_refused(status, 415, before)
            self.assertIn("JPEG", answer["error"])
        # parameters after the type are ignored
        status, _, _ = self.upload({"folder": "city", "kind": "orig"}, self.BODY,
                                   ctype="image/jpeg; charset=binary")
        self.assertEqual(status, 200)

    def test_folders_ids_and_kinds_are_checked(self):
        pid = self.full_upload("city", self.BODY, "image/jpeg", "a.jpg")
        before = self.tree()
        cases = [({"folder": "../city", "kind": "orig"}, 404),
                 ({"folder": "city/..", "kind": "orig"}, 404),
                 ({"folder": "nope", "kind": "orig"}, 404),
                 ({"folder": "", "kind": "orig"}, 404),
                 ({"folder": "quotes", "kind": "orig"}, 409),       # a text-lane folder
                 ({"folder": "city", "kind": "other"}, 400),
                 ({"folder": "city", "kind": "thumb", "id": "../../.env"}, 404),
                 ({"folder": "city", "kind": "thumb", "id": pid + "x"}, 404),
                 ({"folder": "city", "kind": "view", "id": "p-" + "f" * 16}, 404)]
        for params, expected in cases:
            status, _, answer = self.upload(params, pf.make_photo(8, 8, 3))
            self.assert_refused(status, expected, before)
            self.assertIn("error", answer)
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.stock, "quotes", "photos")))

    def test_a_folder_symlinked_out_of_the_stock_is_404(self):
        outside = os.path.join(self.root, "elsewhere")
        os.makedirs(outside)
        pf._write_json(os.path.join(outside, "folder.json"), {"schema": 1, "title": "x",
                                                              "lane": "photo"})
        os.symlink(outside, os.path.join(self.fx.paths.stock, "linked"))
        before = self.tree()
        status, _, _ = self.upload({"folder": "linked", "kind": "orig"}, self.BODY)
        self.assert_refused(status, 404, before)
        self.assertEqual(os.listdir(outside), ["folder.json"])

    def test_a_photos_symlink_is_409_and_nothing_is_written_outside(self):
        outside = os.path.join(self.root, "tmp-like")
        os.makedirs(outside)
        os.symlink(outside, self.photos_dir())
        before = self.tree()
        status, _, answer = self.upload({"folder": "city", "kind": "orig"}, self.BODY)
        self.assert_refused(status, 409, before)
        self.assertIn("не каталог", answer["error"])
        self.assertEqual(os.listdir(outside), [])
        # a thumb/ symlink inside a real photos/ is refused the same way
        os.unlink(self.photos_dir())
        os.makedirs(self.photos_dir(), 0o700)
        os.symlink(outside, os.path.join(self.photos_dir(), "thumb"))
        status, _, _ = self.upload({"folder": "city", "kind": "orig"}, self.BODY)
        self.assertEqual(status, 409)
        self.assertEqual(os.listdir(outside), [])

    def test_photos_never_enter_git(self):
        for rel in ("content/stock/f/photos/p.jpg", "content/stock/f/photos/thumb/p.jpg",
                    "content/stock/f/photos/index.jsonl", "content/drafts/d/voice-1.webm"):
            r = subprocess.run(["git", "-C", REPO_ROOT, "check-ignore", "-q", rel])
            self.assertEqual(r.returncode, 0, rel)

    def test_form_routes_still_take_forms_only(self):
        status, _, _ = self.post("/files/new-folder", {"name": "fresh", "lane": "photo"},
                                 ctype="image/jpeg")
        self.assertEqual(status, 415)
        status, _, _ = self.request("POST", "/files/new-folder", body=b"name=x&lane=photo",
                                    headers={"Content-Type": "application/x-www-form-urlencoded",
                                             "X-CSRF-Token": self.srv.panel.csrf})
        self.assertEqual(status, 403)   # a header token does not replace the form field
        self.assertFalse(os.path.exists(os.path.join(self.fx.paths.stock, "x")))


class PhotoServeTest(PhotoCase):
    def test_each_version_is_served_with_its_type_and_cache_header(self):
        png = pf.make_png(20, 10, 1)
        pid = self.full_upload("city", png, "image/png", "a.png")
        for version, data, ctype in (("orig", png, "image/png"), ("thumb", self.THUMB, "image/jpeg"),
                                     ("view", self.VIEW, "image/jpeg")):
            status, headers, body = self.request("GET", f"/photo?folder=city&id={pid}&v={version}")
            self.assertEqual(status, 200, version)
            self.assertEqual(body, data, version)
            self.assertEqual(headers["content-type"], ctype)
            self.assertEqual(headers["cache-control"], "private, max-age=300")
            self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_hostile_queries_are_404(self):
        pid = self.full_upload("city", pf.make_photo(16, 16, 1), "image/jpeg", "a.jpg")
        bad = [{"folder": "../city", "id": pid, "v": "orig"},
               {"folder": "city", "id": "../../.env", "v": "orig"},
               {"folder": "city", "id": "../../../fake.env", "v": "thumb"},
               {"folder": "city", "id": pid, "v": "../index.jsonl"},
               {"folder": "city", "id": pid, "v": ""},
               {"folder": "nature", "id": pid, "v": "orig"},
               {"folder": "nope", "id": pid, "v": "orig"},
               {"folder": "city", "id": "p-" + "0" * 16, "v": "orig"}]
        for q in bad:
            status, _, data = self.request("GET", "/photo?" + urllib.parse.urlencode(q))
            self.assertEqual(status, 404, q)
            self.assertNotIn(b"cnry", data)

    def test_a_symlinked_or_non_image_file_is_404(self):
        pid = self.full_upload("city", pf.make_photo(16, 16, 1), "image/jpeg", "a.jpg")
        thumb = os.path.join(self.photos_dir(), "thumb", f"{pid}.jpg")
        os.unlink(thumb)
        os.symlink(self.fx.paths.env_file, thumb)
        view = os.path.join(self.photos_dir(), "view", f"{pid}.jpg")
        with open(view, "w", encoding="utf-8") as fh:
            fh.write("not an image " + CANARIES["X_API_KEY"])
        for version in ("thumb", "view"):
            status, _, data = self.request("GET", f"/photo?folder=city&id={pid}&v={version}")
            self.assertEqual(status, 404, version)
            self.assertNotIn(b"cnry", data)


class FilesTabTest(PhotoCase):
    def test_cards_show_photo_thumbs_and_counts(self):
        ids = [self.full_upload("city", pf.make_photo(24 + k, 24, k), "image/jpeg", f"{k}.jpg")
               for k in range(5)]
        body = self.get("/files")[2]
        city = body[body.index('<a href="/files?folder=city" title='):]
        city = city[:city.index("</article>")]
        for pid in ids[:3]:
            self.assertIn(f'src="/photo?folder=city&amp;id={pid}&amp;v=thumb"', city)
        self.assertNotIn(ids[3], city)
        self.assertIn('<span class="tile tile-more mono">+2</span>', city)
        self.assertIn('<span class="pair"><span class="mono num">39</span> '
                      '<span class="muted">пакетов ·</span></span> <span class="pair">'
                      '<span class="mono num">5</span> <span class="muted">фото</span></span>', city)
        nature = body[body.index('<a href="/files?folder=nature" title='):]
        nature = nature[:nature.index("</article>")]
        self.assertNotIn("фото</span>", nature)          # without photos it stays as before
        self.assertNotIn("/photo?", nature)

    def test_an_upload_rebuilds_the_snapshot_once(self):
        holder = self.srv.panel.holder
        self.get("/files")
        self.assertEqual(holder.builds, 1)
        self.full_upload("city", pf.make_photo(16, 16, 1), "image/jpeg", "a.jpg")
        self.assertIn('<span class="mono num">1</span> <span class="muted">фото</span>',
                      self.get("/files")[2])
        self.get("/files?folder=city")
        self.assertEqual(holder.builds, 2)
        # a cut upload (orig only) does not change what is listed
        self.upload({"folder": "city", "kind": "orig"}, pf.make_photo(16, 16, 2))
        self.assertIn('<span class="mono num">1</span> <span class="muted">фото</span>',
                      self.get("/files")[2])

    def test_folder_view_has_the_photo_section_grid_and_chips(self):
        body = self.get("/files?folder=city")[2]
        self.assertIn('<h2 id="photos-h">Фото · <span class="mono">0</span></h2>', body)
        self.assertIn("Фото пока нет", body)
        self.assertIn('<script src="/static/author.js" defer></script>', body)
        self.assertIn('data-pick="dir" disabled>Загрузить папку</button>', body)
        self.assertIn('data-pick="files" disabled>Добавить фото</button>', body)
        self.assertIn('webkitdirectory multiple hidden', body)
        self.assertIn('accept="image/jpeg,image/png,image/webp"', body)
        self.assertIn(f'data-csrf="{self.srv.panel.csrf}"', body)
        self.assertIn("<noscript>", body)
        self.assertLess(body.index('class="photos"'), body.index('class="pkgs"'))
        for folder in ("quotes", "notes"):
            other = self.get(f"/files?folder={folder}")[2]
            self.assertNotIn('class="photos"', other)
            self.assertNotIn("author.js", other)
        self.assertNotIn("author.js", self.get("/files")[2])

    def test_chips_name_how_a_photo_is_used(self):
        fx = pf.build_photos(os.path.join(self.root, "photos-fx"), n=4)
        from factory.panel import server
        srv = server.make_server(fx.paths, fx.clock, fx.machine_tz, 0, log=io.StringIO())
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), thread.join(5)))
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
        conn.request("GET", "/files?folder=city", headers={"Host": f"127.0.0.1:{srv.port}"})
        body = conn.getresponse().read().decode()
        conn.close()
        self.outputs.append(body)
        rows = photos.read_index(os.path.join(fx.paths.stock, "city", "photos"))
        tiles = re.findall(r'<li class="ptile" id="photo-(\d+)" data-id="(p-[0-9a-f]{16})">(.*?)</li>',
                           body)
        # newest upload first
        self.assertEqual([t[1] for t in tiles], [r["id"] for r in reversed(rows)])
        self.assertEqual([t[0] for t in tiles], ["1", "2", "3", "4"])
        chips = {t[1]: re.sub(r"<[^>]+>", "", t[2]) for t in tiles}
        self.assertEqual(chips[rows[0]["id"]], "")
        self.assertEqual(chips[rows[1]["id"]], "опубликовано")
        self.assertEqual(chips[rows[2]["id"]], "в очереди")
        self.assertIn('alt="walk-0001-portrait.jpg" title="walk-0001-portrait.jpg"', body)
        self.assertIn('<h2 id="photos-h">Фото · <span class="mono">4</span></h2>', body)

    def test_a_new_upload_is_the_first_tile_even_in_a_big_folder(self):
        os.makedirs(os.path.join(self.photos_dir(), "thumb"), 0o700)
        os.makedirs(os.path.join(self.photos_dir(), "view"), 0o700)
        rows = [{"id": f"p-{k:016x}", "name": f"{k}.jpg", "ext": "jpg", "bytes": 10, "w": 4,
                 "h": 3, "ts": "2026-11-11T00:00:00Z"} for k in range(70)]
        pf.poster_state.append_jsonl(os.path.join(self.photos_dir(), "index.jsonl"), rows)
        before = self.get("/files?folder=city")[2]
        self.assertEqual(re.findall(r'id="photo-1" data-id="(p-[0-9a-f]{16})"', before),
                         [rows[-1]["id"]])
        self.full_upload("city", pf.make_photo(16, 16, 77), "image/jpeg", "fresh.jpg")
        after = self.get("/files?folder=city")[2]
        first = re.search(r'id="photo-1" data-id="(p-[0-9a-f]{16})".*?alt="([^"]*)"', after, re.S)
        self.assertEqual(first.group(2), "fresh.jpg")
        self.assertNotIn(first.group(1), [r["id"] for r in rows])
        self.assertEqual(after.count('class="ptile"'), 60)   # the 61st step is still behind more
        self.assertIn("60 из 71", after)
        self.assertIn(rows[0]["id"], self.get("/files?folder=city&photos=71")[2])   # oldest last

    def test_busy_buttons_look_disabled_and_the_run_has_distinct_button_words(self):
        with open(os.path.join(REPO_ROOT, "factory", "panel", "static", "panel.css"),
                  encoding="utf-8") as fh:
            css = fh.read()
        rule = re.search(r"\.btn:disabled\s*\{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        self.assertRegex(rule.group(1), r"opacity:\s*\.\d+")
        self.assertIn("cursor: default", rule.group(1))
        words = S.UPLOAD_JS
        self.assertNotEqual(words["reload"], words["reload_new"])
        # the status line counts; no reason text is a part of its strings
        for key in ("progress", "dup", "skipped", "done", "running"):
            for reason in (words["heic"], words["type"], words["decode"], S.UP_BAD_TYPE):
                self.assertNotIn(reason, words[key])

    def test_sixty_per_step_with_show_more(self):
        os.makedirs(os.path.join(self.photos_dir(), "thumb"), 0o700)
        os.makedirs(os.path.join(self.photos_dir(), "view"), 0o700)
        rows = [{"id": f"p-{k:016x}", "name": f"{k}.jpg", "ext": "jpg", "bytes": 10, "w": 4,
                 "h": 3, "ts": "2026-11-11T00:00:00Z"} for k in range(130)]
        pf.poster_state.append_jsonl(os.path.join(self.photos_dir(), "index.jsonl"), rows)
        body = self.get("/files?folder=city")[2]
        self.assertEqual(body.count('class="ptile"'), 60)
        self.assertIn('href="/files?folder=city&amp;photos=120#photo-61">показать ещё</a>', body)
        self.assertIn("60 из 130", body)
        body = self.get("/files?folder=city&photos=120")[2]
        self.assertEqual(body.count('class="ptile"'), 120)
        self.assertIn('id="photo-61"', body)
        self.assertIn("photos=130#photo-121", body)
        body = self.get("/files?folder=city&photos=130")[2]
        self.assertEqual(body.count('class="ptile"'), 130)
        self.assertNotIn("показать ещё", body)
        for bad in ("abc", "-5", "0", "99999999999999999999", "nan"):
            status, _, body = self.get(f"/files?folder=city&photos={bad}")
            self.assertEqual(status, 200, bad)
            self.assertIn(body.count('class="ptile"'), (60, 130), bad)

    def test_a_malformed_index_row_is_skipped_not_fatal(self):
        os.makedirs(os.path.join(self.photos_dir(), "thumb"), 0o700)
        os.makedirs(os.path.join(self.photos_dir(), "view"), 0o700)
        good = {"id": "p-" + "a" * 16, "name": "ok.jpg", "ext": "jpg", "bytes": 1, "w": 1, "h": 1,
                "ts": "2026-11-11T00:00:00Z"}
        with open(os.path.join(self.photos_dir(), "index.jsonl"), "w", encoding="utf-8") as fh:
            for row in (dict(good, id="../x"), dict(good, ext="exe"), dict(good, w=True),
                        dict(good, name=5), good, dict(good, name="second"), [1]):
                fh.write(json.dumps(row) + "\n")
            fh.write('{"torn": ')
        self.assertEqual(photos.read_index(self.photos_dir()), [good])
        self.assertEqual(self.get("/files?folder=city")[2].count('class="ptile"'), 1)


class ProcessTokenTest(PhotoCase):
    """The upload token lives in the panel process's memory: after a restart the old page's
    token is refused and nothing is stored."""

    def test_a_restart_refuses_the_old_upload_token(self):
        def start():
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            env.update(self.fx.environ)
            code = (f"import sys; sys.path.insert(0, {REPO_ROOT!r}); from factory.cli import main; "
                    "sys.exit(main(['panel', '--port', '0']))")
            proc = subprocess.Popen([sys.executable, "-I", "-B", "-u", "-c", code], env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(10),
                                     proc.stdout.close(), proc.stderr.close()))
            port = int(re.search(r"http://localhost:(\d+)/", proc.stdout.readline()).group(1))
            return proc, port

        def call(port, method, path, body=None, headers=None):
            import http.client
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            conn.request(method, path, body=body, headers=dict({"Host": f"127.0.0.1:{port}"},
                                                               **(headers or {})))
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            return resp.status, data
        proc, port = start()
        page = call(port, "GET", "/files?folder=city")[1].decode()
        self.outputs.append(page)
        token = re.search(r'data-csrf="([0-9a-f]{64})"', page).group(1)
        body = pf.make_photo(16, 16, 1)
        headers = {"Content-Type": "image/jpeg", "X-CSRF-Token": token,
                   "Origin": f"http://127.0.0.1:{port}"}
        status, data = call(port, "POST", "/files/photos?folder=city&kind=orig", body, headers)
        self.assertEqual(status, 200, data)
        proc.send_signal(signal.SIGINT)
        self.assertEqual(proc.wait(20), 0)
        proc2, port2 = start()
        before = self.tree()
        headers["Origin"] = f"http://127.0.0.1:{port2}"
        status, data = call(port2, "POST", "/files/photos?folder=city&kind=orig",
                            pf.make_photo(16, 16, 2), headers)
        self.assertEqual(status, 403)
        self.assertIn("обновите страницу", data.decode())
        self.assertEqual(self.tree(), before)
        proc2.send_signal(signal.SIGINT)
        self.assertEqual(proc2.wait(20), 0)


class FixtureImageTest(unittest.TestCase):
    """The generated WebP originals are well-formed RIFF files, not only RIFF/WEBP magic."""

    @staticmethod
    def walk(data: bytes) -> list:
        """(fourcc, size) of each chunk after the 12-byte RIFF header; fails on a chunk that
        runs past the file or is not word-aligned padded."""
        out, pos = [], 12
        while pos < len(data):
            kind, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
            out.append((kind, size))
            pos += 8 + size + (size & 1)
        return out, pos

    def test_webp_fixture_chunks_end_exactly_at_the_file(self):
        for seed in (0, 3, 99):
            data = pf.make_webp(seed)
            chunks, end = self.walk(data)
            self.assertEqual(end, len(data), seed)
            self.assertEqual(chunks, [(b"VP8L", 13), (b"MFIX", 4)], seed)
            self.assertEqual(int.from_bytes(data[4:8], "little"), len(data) - 8)
            self.assertEqual(data[:4] + data[8:12], b"RIFFWEBP")
            self.assertEqual(data[20], 0x2F)   # the VP8L signature byte


if __name__ == "__main__":
    unittest.main()
