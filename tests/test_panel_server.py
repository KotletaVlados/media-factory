"""Panel server: routes, headers, Host / Origin / CSRF / size / type checks, /img, the snapshot
cache, and the real process lifecycle (design factory.md §11.1, §13.3 item 2; brief §3.1)."""

from __future__ import annotations

import io
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from factory import cli as fcli
from tests import panel_fixture as pf
from tests.base import CANARIES, REPO_ROOT

PAGES = ["/connection", "/files", "/rules", "/calendar", "/reach", "/followers", "/dialogs"]
WRITES = ["/rules/day", "/rules/hour", "/rules/zone", "/rules/start", "/rules/stop",
          "/rules/new", "/files/new-folder"]


class RoutesTest(pf.PanelCase):
    def test_root_redirects_to_connection(self):
        status, headers, _ = self.get("/")
        self.assertEqual(status, 302)
        self.assertEqual(headers["location"], "/connection")

    def test_every_page_answers_html_with_the_security_headers(self):
        for path in PAGES:
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertTrue(headers["content-type"].startswith("text/html"), path)
            self.assertEqual(headers["cache-control"], "no-store", path)
            self.assertEqual(headers["referrer-policy"], "no-referrer", path)
            self.assertEqual(headers["content-security-policy"],
                             "default-src 'self'; img-src 'self'; style-src 'self'; "
                             "script-src 'self'; frame-ancestors 'none'", path)
            self.assertIn('<html lang="ru">', body)
            self.assertNotIn("style=", body, f"{path}: inline style breaks the CSP")
            self.assertNotIn("<script>", body, f"{path}: inline script breaks the CSP")

    def test_static_files_come_from_a_fixed_table(self):
        for name, ctype in (("panel.css", "text/css"), ("panel.js", "text/javascript"),
                            ("probe.js", "text/javascript")):
            status, headers, _ = self.request("GET", f"/static/{name}")
            self.assertEqual(status, 200, name)
            self.assertTrue(headers["content-type"].startswith(ctype), name)
            self.assertIn("content-security-policy", headers)
        for name in ("../server.py", "..%2Fserver.py", "panel.css/../server.py", "other.css", ""):
            status, _, _ = self.request("GET", f"/static/{name}")
            self.assertEqual(status, 404, name)

    def test_unknown_path_is_a_404_page(self):
        status, _, body = self.get("/nope")
        self.assertEqual(status, 404)
        self.assertIn("Страница не найдена", body)

    def test_probe_script_only_with_probe_1(self):
        self.assertNotIn("probe.js", self.get("/rules")[2])
        self.assertIn('<script src="/static/probe.js" defer>', self.get("/rules?probe=1")[2])

    def test_panel_js_stays_small(self):
        path = os.path.join(REPO_ROOT, "factory", "panel", "static", "panel.js")
        with open(path, encoding="utf-8") as fh:
            self.assertLessEqual(len(fh.read().splitlines()), 150)


class HostOriginCsrfTest(pf.PanelCase):
    def test_wrong_host_is_421_on_get_and_post(self):
        port = self.srv.port
        for host in ("evil.example", f"evil.example:{port}", f"127.0.0.1:{port + 1}",
                     f"localhost.evil.example:{port}", ""):
            status, _, _ = self.request("GET", "/rules", host=host)
            self.assertEqual(status, 421, host)
        before = self.file_hash(self.fx.paths.rules)
        status, _, _ = self.post("/rules/start", {"rule": "notes-draft", "rev": self.revision()},
                                 host="evil.example")
        self.assertEqual(status, 421)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)

    def test_missing_host_header_is_421(self):
        status, _, _ = self.request("GET", "/connection", headers={"Host": None})
        self.assertEqual(status, 421)

    def test_localhost_host_is_accepted(self):
        status, _, _ = self.request("GET", "/connection", host=f"localhost:{self.srv.port}")
        self.assertEqual(status, 200)

    def test_post_without_or_with_wrong_csrf_is_403_and_nothing_changes(self):
        before = self.state_hashes()
        fields = {"rule": "notes-draft", "rev": self.revision(), "day": "mon", "hour": "09:00",
                  "zone": "Europe/Paris", "id": "x1", "folder": "notes", "name": "new-one",
                  "lane": "text"}
        for path in WRITES:
            for csrf in (False, "", "0" * 64, self.srv.panel.csrf[:-1]):
                status, _, body = self.post(path, fields, csrf=csrf)
                self.assertEqual(status, 403, (path, csrf))
                self.assertIn("csrf", body)
        self.assertEqual(self.state_hashes(), before)

    def test_foreign_origin_is_403_even_with_the_token(self):
        before = self.state_hashes()
        for origin in ("http://evil.example", f"http://evil.example:{self.srv.port}", "null",
                       f"https://127.0.0.1:{self.srv.port}", f"http://localhost:{self.srv.port}"):
            status, _, _ = self.post("/rules/start", {"rule": "notes-draft",
                                                      "rev": self.revision()}, origin=origin)
            self.assertEqual(status, 403, origin)
        self.assertEqual(self.state_hashes(), before)

    def test_same_origin_post_with_the_token_is_accepted(self):
        status, headers, _ = self.post("/rules/day", {"rule": "notes-draft", "rev": self.revision(),
                                                      "day": "mon"},
                                       origin=f"http://{self.host}")
        self.assertEqual(status, 303)
        self.assertEqual(headers["location"], "/rules#rule-notes-draft")

    def test_wrong_media_type_is_415_and_large_body_is_413(self):
        before = self.state_hashes()
        fields = {"rule": "notes-draft", "rev": self.revision(), "day": "mon"}
        for ctype in ("text/plain", "multipart/form-data; boundary=x", "application/json", ""):
            status, _, _ = self.post("/rules/day", fields, ctype=ctype)
            self.assertEqual(status, 415, ctype)
        big = [("rule", "notes-draft"), ("rev", self.revision()), ("day", "mon"),
               ("pad", "x" * (16 * 1024))]
        status, _, _ = self.post("/rules/day", big)
        self.assertEqual(status, 413)
        status, _, _ = self.request("POST", "/rules/day", body=b"", headers={
            "Content-Type": "application/x-www-form-urlencoded", "Content-Length": "abc"})
        self.assertEqual(status, 400)
        self.assertEqual(self.state_hashes(), before)

    def test_post_without_content_length_is_411(self):
        status, _, _ = self.request("POST", "/rules/day", body=None, headers={
            "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 411)

    def test_unknown_post_path_is_404(self):
        status, _, _ = self.post("/rules/delete", {"rule": "city-main"})
        self.assertEqual(status, 404)


class ImageTest(pf.PanelCase):
    def img(self, folder, file, ref):
        import urllib.parse
        q = urllib.parse.urlencode({"folder": folder, "file": file, "ref": ref})
        return self.request("GET", f"/img?{q}")

    def test_a_package_image_is_served(self):
        status, headers, data = self.img("city", "001-city-01.json", "city-01.jpg")
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "image/jpeg")
        with open(os.path.join(self.fx.paths.library, "city-01.jpg"), "rb") as fh:
            self.assertEqual(data, fh.read())

    def test_refs_that_the_package_does_not_name_are_404(self):
        for ref in ("../../fake.env", "../fake.env", self.fx.paths.env_file, "/etc/passwd",
                    "city-02.jpg", "", "%2e%2e/fake.env"):
            status, _, data = self.img("city", "001-city-01.json", ref)
            self.assertEqual(status, 404, ref)
            self.assertNotIn(b"cnry", data)
        for folder, file in (("nope", "001-city-01.json"), ("city", "999.json"), ("", ""),
                             ("../content", "001-city-01.json")):
            self.assertEqual(self.img(folder, file, "city-01.jpg")[0], 404)

    def _evil_package(self, ref: str, name: str) -> None:
        folder = os.path.join(self.fx.paths.stock, "evil")
        pf._write_json(os.path.join(folder, "folder.json"),
                       {"schema": 1, "title": "evil", "lane": "photo"})
        pf._write_json(os.path.join(folder, f"{name}.json"), {
            "schema": 1, "id": name, "theme": "t",
            "variants": {"facebook": {"text": "t", "image": ref}}})

    def test_named_refs_outside_the_roots_or_not_images_are_404(self):
        outside = os.path.join(self.root, "outside")
        os.makedirs(outside)
        with open(os.path.join(outside, "real.jpg"), "wb") as fh:
            fh.write(pf.make_photo(16, 16, 1))
        os.symlink(os.path.join(outside, "real.jpg"), os.path.join(self.fx.paths.library, "link.jpg"))
        with open(os.path.join(self.fx.paths.library, "notes.jpg"), "w", encoding="utf-8") as fh:
            fh.write("not an image " + CANARIES["X_API_KEY"])
        cases = {
            "dotdot": "../../../fake.env",                       # .. out of the stock folder
            "absolute": os.path.join(outside, "real.jpg"),       # an absolute path elsewhere
            "symlink": "link.jpg",                              # a library symlink out of it
            "notimage": "notes.jpg",                            # a file that does not sniff
        }
        for name, ref in cases.items():
            self._evil_package(ref, name)
        self.assertEqual(self.get("/files")[0], 200)   # the snapshot sees the new folder
        for name, ref in cases.items():
            status, _, data = self.img("evil", f"{name}.json", ref)
            self.assertEqual(status, 404, name)
            self.assertNotIn(b"cnry", data, name)


class CanaryTest(pf.PanelCase):
    def test_no_canary_secret_in_any_page(self):
        paths = PAGES + ["/connection?net=" + n for n in
                         ("facebook", "instagram", "x", "linkedin", "telegram")] + [
            "/connection?attention=1", "/files?folder=city", "/files?folder=quotes",
            "/calendar?day=2026-11-10", "/calendar?day=2026-11-06", "/calendar?more=2",
            "/reach?sort=weak", "/reach?net=facebook", "/followers?period=all", "/nope"]
        for path in paths:
            status, _, body = self.get(path)
            self.assertIn(status, (200, 404), path)
            self.assert_no_canary(body)
        # the record row with the planted token was rendered, redacted
        body = self.get("/calendar?day=2026-11-10")[2]
        self.assertIn("ошибка: Graph code 190: Error validating access token [redacted:", body)

    def test_an_unexpected_error_is_500_and_redacted(self):
        from factory.panel import server, views
        original = views.reach

        def boom(ctx):
            raise RuntimeError("broken with " + CANARIES["FB_PAGE_DEMO_TOKEN"])
        server.PAGES["/reach"] = ("reach", boom)
        self.addCleanup(server.PAGES.__setitem__, "/reach", ("reach", original))
        status, _, body = self.get("/reach")
        self.assertEqual(status, 500)
        self.assertIn("Ошибка панели", body)
        self.assertIn("RuntimeError: broken with [redacted:FB_PAGE_DEMO_TOKEN]", body)
        self.assertIs(server.PAGES["/reach"][1], boom)


class SnapshotTest(pf.PanelCase):
    def test_one_build_per_change(self):
        holder = self.srv.panel.holder
        self.get("/rules")
        self.get("/calendar")
        self.get("/files")
        self.assertEqual(holder.builds, 1)
        self.assertRegex(self.log.getvalue(), r"panel: snapshot_ms=\d+")
        # a rules write changes the key
        self.post("/rules/day", {"rule": "notes-draft", "rev": self.revision(), "day": "mon"})
        self.get("/rules")
        self.assertEqual(holder.builds, 2)
        # a new record row changes the key
        from poster import state as poster_state
        poster_state.append_jsonl(os.path.join(self.fx.paths.poster_state, "posts.jsonl"),
                                  [{"ts": "2026-11-11T09:39:00Z", "package": "p", "target": "x",
                                    "network": "x", "status": "failed", "error": "e"}])
        self.get("/rules")
        self.assertEqual(holder.builds, 3)
        # the next minute rebuilds once
        self.panel_clock.now = pf.NOW.replace(minute=41)
        self.get("/rules")
        self.get("/reach")
        self.assertEqual(holder.builds, 4)

    def test_concurrent_first_requests_share_one_build(self):
        results = []

        def fetch():
            results.append(self.get("/calendar")[0])
        threads = [threading.Thread(target=fetch) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(results, [200] * 6)
        self.assertEqual(self.srv.panel.holder.builds, 1)


class WriteErrorTest(pf.PanelCase):
    """An unexpected error inside a POST is answered like one inside a page (brief §3.2):
    HTTP 500, the shell with `type: message` redacted, one redacted log line, nothing written."""

    def assert_last_resort(self, status, body):
        self.assertEqual(status, 500)
        self.assertIn("Ошибка панели", body)
        self.assertNotIn(CANARIES["FB_PAGE_DEMO_TOKEN"], body)
        self.assertNotIn(CANARIES["FB_PAGE_DEMO_TOKEN"], self.log.getvalue())
        self.assertIn("panel: ", self.log.getvalue())

    def test_a_failing_rules_write_is_a_500_page_and_the_file_stays(self):
        from factory import ruleset as fruleset
        before = self.file_hash(self.fx.paths.rules)
        err = OSError("disk said no with " + CANARIES["FB_PAGE_DEMO_TOKEN"])
        with mock.patch.object(fruleset, "write", side_effect=err):
            status, headers, body = self.post("/rules/day", {
                "rule": "notes-draft", "rev": self.revision(), "day": "mon"})
        self.assert_last_resort(status, body)
        self.assertIn("OSError: disk said no with [redacted:FB_PAGE_DEMO_TOKEN]", body)
        self.assertEqual(headers["cache-control"], "no-store")
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)
        # the panel still answers, and the write lock was released
        self.assertEqual(self.get("/rules")[0], 200)
        self.assertEqual(self.post("/rules/day", {"rule": "notes-draft", "rev": self.revision(),
                                                  "day": "mon"})[0], 303)

    def test_read_only_folders_give_a_500_page_not_a_dropped_connection(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores directory modes")
        content = os.path.dirname(self.fx.paths.rules)
        stock = self.fx.paths.stock
        for path in (content, stock):
            old = stat.S_IMODE(os.stat(path).st_mode)
            os.chmod(path, 0o500)
            self.addCleanup(os.chmod, path, old)
        before = self.file_hash(self.fx.paths.rules)
        status, _, body = self.post("/rules/day", {"rule": "notes-draft", "rev": self.revision(),
                                                   "day": "mon"})
        self.assertEqual(status, 500)
        self.assertIn("Ошибка панели", body)
        status, _, body = self.post("/files/new-folder", {"name": "fresh", "lane": "photo"})
        self.assertEqual(status, 500)
        self.assertIn("Ошибка панели", body)
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)
        self.assertFalse(os.path.exists(os.path.join(stock, "fresh")))

    def test_a_failing_folder_write_is_a_500_page(self):
        from factory.panel import actions
        err = RuntimeError("no room " + CANARIES["FB_PAGE_DEMO_TOKEN"])
        with mock.patch.object(actions, "new_folder", side_effect=err):
            status, _, body = self.post("/files/new-folder", {"name": "fresh", "lane": "photo"})
        self.assert_last_resort(status, body)
        self.assertIn("RuntimeError: no room [redacted:FB_PAGE_DEMO_TOKEN]", body)


class BindTest(pf.PanelCase):
    """"Local only": the listening socket is on the loopback address, and the port is free
    again at once after a stop (design factory.md §11.1)."""

    def test_make_server_binds_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")
        self.assertEqual(self.srv.socket.getsockname()[0], "127.0.0.1")

    def test_the_port_can_be_bound_again_right_after_a_stop(self):
        from factory.panel import server
        srv = server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz, 0,
                                 log=io.StringIO())
        port = srv.port
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        for path in ("/connection", "/rules", "/calendar"):
            self.assertTrue(fetch_to_eof(port, path).startswith(b"HTTP/1.0 200"))
        srv.shutdown()
        srv.server_close()
        thread.join(5)
        again = server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz, port,
                                   log=io.StringIO())
        self.addCleanup(again.server_close)
        self.assertEqual(again.port, port)

    def test_a_second_live_listener_on_the_port_is_still_refused(self):
        from factory.panel import server
        with self.assertRaises(OSError) as ctx:
            server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz,
                               self.srv.port, log=io.StringIO())
        import errno
        self.assertEqual(ctx.exception.errno, errno.EADDRINUSE)


def fetch_to_eof(port: int, path: str) -> bytes:
    """GET `path` and read until the server closes the stream. The server closes first, so
    its side of the connection is the one left in TIME_WAIT (what blocks a rebind of the port
    when the listener lacks SO_REUSEADDR)."""
    with socket.create_connection(("127.0.0.1", port), timeout=30) as conn:
        conn.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                     "Connection: close\r\n\r\n".encode())
        data = b""
        while chunk := conn.recv(65536):
            data += chunk
    return data


def listening_addresses(port: int) -> set:
    """Local addresses (hex, as /proc prints them) of every TCP socket listening on `port`."""
    found = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="ascii") as fh:
                rows = fh.read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            cols = row.split()
            addr, _, p = cols[1].rpartition(":")
            if cols[3] == "0A" and int(p, 16) == port:
                found.add(addr)
    return found


class ProcessTest(pf.PanelCase):
    """`python3 -m factory panel` as a real process: the port it prints, Ctrl+C, and the CSRF
    token that lives only in that process's memory."""

    def _start(self):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        env.update(self.fx.environ)
        code = (f"import sys; sys.path.insert(0, {REPO_ROOT!r}); from factory.cli import main; "
                "sys.exit(main(['panel', '--port', '0']))")
        proc = subprocess.Popen([sys.executable, "-I", "-B", "-u", "-c", code], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self._reap, proc)
        line = proc.stdout.readline()
        m = re.search(r"http://localhost:(\d+)/", line)
        self.assertIsNotNone(m, line + proc.stderr.read() if proc.poll() is not None else line)
        return proc, int(m.group(1))

    @staticmethod
    def _reap(proc):
        if proc.poll() is None:
            proc.kill()
        proc.wait(10)
        proc.stdout.close()
        proc.stderr.close()

    def _token(self, port):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("GET", "/rules", headers={"Host": f"127.0.0.1:{port}"})
        body = conn.getresponse().read().decode()
        conn.close()
        self.outputs.append(body)
        return re.search(r'name="csrf" value="([0-9a-f]{64})"', body).group(1)

    @unittest.skipUnless(os.path.exists("/proc/net/tcp"), "needs /proc/net/tcp")
    def test_the_process_listens_on_loopback_only(self):
        proc, port = self._start()
        self.assertEqual(listening_addresses(port), {"0100007F"})   # 127.0.0.1, nothing else
        proc.send_signal(signal.SIGINT)
        self.assertEqual(proc.wait(20), 0)

    def test_a_restart_on_the_same_port_works_at_once(self):
        proc, port = self._start()
        for path in ("/connection", "/rules", "/calendar"):
            self.assertTrue(fetch_to_eof(port, path).startswith(b"HTTP/1.0 200"))
        proc.send_signal(signal.SIGINT)
        self.assertEqual(proc.wait(20), 0)
        from factory.panel import server
        srv = server.make_server(self.fx.paths, self.panel_clock, self.fx.machine_tz, port,
                                 log=io.StringIO())
        srv.server_close()
        self.assertEqual(srv.port, port)

    def test_ctrl_c_stops_and_a_restart_makes_a_new_token(self):
        proc, port = self._start()
        old = self._token(port)
        proc.send_signal(signal.SIGINT)
        self.assertEqual(proc.wait(20), 0)
        proc2, port2 = self._start()
        new = self._token(port2)
        self.assertNotEqual(old, new)
        import http.client
        import urllib.parse
        before = self.file_hash(self.fx.paths.rules)
        body = urllib.parse.urlencode({"csrf": old, "rule": "notes-draft",
                                       "rev": self.revision(), "day": "mon"})
        conn = http.client.HTTPConnection("127.0.0.1", port2, timeout=30)
        conn.request("POST", "/rules/day", body=body, headers={
            "Host": f"127.0.0.1:{port2}", "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(conn.getresponse().status, 403)
        conn.close()
        self.assertEqual(self.file_hash(self.fx.paths.rules), before)
        proc2.send_signal(signal.SIGINT)
        self.assertEqual(proc2.wait(20), 0)

    def test_port_in_use_stops_with_a_message(self):
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        busy.listen(1)
        self.addCleanup(busy.close)
        out, err = io.StringIO(), io.StringIO()
        code = fcli.main(["panel", "--port", str(busy.getsockname()[1])],
                         environ=self.fx.environ, clock=self.fx.clock, stdout=out, stderr=err)
        self.assertEqual(code, 2)
        self.assertIn("port in use, pass --port", err.getvalue())

    def test_bad_port_is_a_usage_error(self):
        out, err = io.StringIO(), io.StringIO()
        self.assertEqual(fcli.main(["panel", "--port", "70000"], environ=self.fx.environ,
                                   stdout=out, stderr=err), 2)


if __name__ == "__main__":
    unittest.main()
