"""Each tab's states (design factory.md §11.3–§11.10, §14; brief §3.2 and §4): the data and
empty fixtures, every page-level error state, and the strings and helpers behind them."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import unittest

from factory.panel import model as M, strings as S
from tests import panel_fixture as pf

TABS = ["/connection", "/files", "/rules", "/calendar", "/reach", "/followers"]


def main_of(body: str) -> str:
    """The page's <main> only (the top bar is shared by every tab)."""
    return html.unescape(body.split("<main", 1)[1].split("</main>", 1)[0])


def text_of(fragment: str) -> str:
    """Visible text of an HTML fragment, tags dropped."""
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


class ShellTest(pf.PanelCase):
    def test_tab_bar_and_top_right(self):
        body = self.get("/connection")[2]
        for label in ("Подключение", "Файлы", "Правила", "Календарь", "Охваты", "Подписчики"):
            self.assertIn(f">{label}</a>", body)
        self.assertIn('<span class="tab off" aria-disabled="true">Диалоги · выкл</span>', body)
        self.assertNotIn('href="/dialogs"', body)
        self.assertIn('aria-current="page">Подключение</a>', body)
        top = html.unescape(body.split("</header>")[0])
        self.assertIn("X ноябрь $1.12 из $5.00 · план +$", top)
        self.assertIn("LinkedIn: 54 дн.", top)
        self.assertIn("таймер: 2 мин назад", top)
        self.assertRegex(top, r'<span class="badge mono">5</span>')

    def test_attention_strip_opens_without_js_and_links_to_rows(self):
        closed = self.get("/connection")[2]
        self.assertIn('class="attn" hidden', closed)
        body = html.unescape(self.get("/connection?attention=1")[2])
        strip = body.split('id="attention"')[1].split("</section>")[0]
        self.assertNotIn(" hidden", strip.split(">")[0])
        self.assertIn("Внимание · <span class=\"mono\">5</span>", strip)
        self.assertIn('href="/calendar?day=2026-11-06"', strip)       # linkedin failed, x unknown
        self.assertIn('href="/calendar?day=2026-11-10"', strip)       # fb:demo failed
        self.assertIn('href="/files?folder=nature"', strip)          # not approved
        self.assertIn('href="/files?folder=quotes"', strip)          # needs fixing
        self.assertIn("ended unknown; check the account", strip)

    def test_timer_silent_is_red_text(self):
        self.panel_clock.now = pf.NOW + dt.timedelta(minutes=40)
        top = self.get("/rules")[2].split("</header>")[0]
        self.assertIn('<span class="mono red">таймер молчит 42 мин</span>', top)


class ConnectionTest(pf.PanelCase):
    def test_data(self):
        body = main_of(self.get("/connection")[2])
        p = pf.profile()
        self.assertIn("6 целей в файле ключей", self.get("/connection")[2])
        self.assertIn("Аккаунты", body)
        self.assertIn("основной профиль", body)
        self.assertIn(f'<span class="mono">{p["facebook"]}</span><span class="st k-ok">подключено',
                      body)
        self.assertIn('<span class="mono">fb:demo</span><span class="st k-bad">ошибка токена', body)
        self.assertRegex(body, r'class="ring-n"[^>]*>4<tspan class="ring-of"> из 4</tspan>')
        self.assertIn("сети постера", body)
        self.assertEqual(body.count('class="node-state k-muted"'), 5)
        self.assertEqual(text_of(body).count("не построено"), 5)
        self.assertIn("Выберите сеть на кольце", body)
        self.assertNotIn("Подключить", body)       # no one-click aggregator (§18)
        self.assertNotIn("<form", body)            # no write action

    def test_selected_node_card(self):
        body = main_of(self.get("/connection?net=linkedin")[2])
        self.assertIn("Токен действует до 5 января 2027 (54 дн.)", body)
        self.assertIn("python3 -m poster login linkedin", body)
        self.assertIn('<span class="mono">LINKEDIN_ACCESS_TOKEN</span> <span class="st k-ok">есть',
                      body)
        self.assertIn("Последняя публикация", body)
        self.assertIn('href="https://example.com/li/', body)
        body = main_of(self.get("/connection?net=facebook")[2])
        self.assertIn("fb:demo", body)
        self.assertIn("token rejected", body)          # the last stats read, as written
        body = main_of(self.get("/connection?net=tiktok")[2])
        self.assertIn("Постер не публикует в эту сеть", body)

    def test_expired_linkedin_token_needs_login(self):
        self.panel_clock.now = dt.datetime(2027, 1, 6, tzinfo=dt.timezone.utc)
        body = main_of(self.get("/connection")[2])
        self.assertIn('<span class="mono">linkedin</span><span class="st k-warn">нужен вход', body)
        self.assertIn("LinkedIn: нужен вход", self.get("/connection")[2])


class FilesTest(pf.PanelCase):
    def test_data(self):
        page = self.get("/files")[2]
        self.assertIn('<p class="sub-left">5 папок</p>', page)
        body = main_of(page)
        self.assertIn("Фото-посты", body)
        self.assertIn("· 2 папки · 46 пакетов", body)
        self.assertIn("Текстовые посты", body)
        self.assertIn("не одобрено: 1", body)
        self.assertIn("нужно исправить: 1", body)
        self.assertIn("никто не берёт · расход 0", body)
        self.assertRegex(body, r"\d+ из 90 дней")
        self.assertEqual(body.count("новая папка в этой полосе"), 2)
        self.assertIn('src="/img?folder=city&file=001-city-01.json&ref=city-01.jpg"', body)
        self.assertIn('+37</span>', body)

    def test_folder_view(self):
        body = main_of(self.get("/files?folder=city")[2])
        self.assertIn("001-city-01.json", body)
        self.assertIn("опубликован · 14 сент.", body)
        self.assertIn("запланирован · ", body)
        self.assertIn("ждёт", body)
        self.assertIn("неизвестно — проверьте аккаунт", main_of(self.get("/files?folder=city")[2]))
        self.assertIn("Папки «nope» нет", main_of(self.get("/files?folder=nope")[2]))
        nature = main_of(self.get("/files?folder=nature")[2])
        self.assertIn("ни одно правило не берёт эту папку", nature)
        self.assertIn("не одобрено", nature)


LONG_TITLE = "Фотографии с городских прогулок"
PANEL_CSS = os.path.join(os.path.dirname(pf.__file__), "..", "factory", "panel", "static", "panel.css")


def css_rule(css: str, selector: str) -> str:
    """The declarations of the one rule whose selector list is exactly `selector`."""
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


class LongTitleTest(pf.PanelCase):
    """A folder title of 31+ characters, read by a rule, is clamped with an ellipsis on the
    Files card and the Rules source card, and the count beside it stays on one line."""

    def test_fixture_folder_is_long_and_read_by_a_rule(self):
        self.assertGreaterEqual(len(LONG_TITLE), 31)
        with open(os.path.join(self.fx.paths.stock, "city", "folder.json"), encoding="utf-8") as fh:
            folder = json.load(fh)
        self.assertEqual(folder["title"], LONG_TITLE)
        self.assertTrue(any(r["folder"] == "city" for r in self.rules_doc()["rules"]))

    def test_both_cards_carry_the_whole_title(self):
        files = main_of(self.get("/files")[2])
        self.assertIn(f'title="{LONG_TITLE}">{LONG_TITLE}</a>', files)
        rules = main_of(self.get("/rules")[2])
        self.assertIn(f'title="{LONG_TITLE}">{LONG_TITLE}</a>', rules)
        self.assertIn('<span class="mono num-s">39</span>', rules)

    def test_clamped_boxes_are_block_level_and_numbers_do_not_wrap(self):
        with open(PANEL_CSS, encoding="utf-8") as fh:
            css = fh.read()
        for selector in (".mini-title", ".fcard-title a"):
            rule = css_rule(css, selector)
            self.assertIn("text-overflow: ellipsis", rule, selector)
            self.assertIn("overflow: hidden", rule, selector)
            self.assertRegex(rule, r"display:\s*block\b", selector)   # flex ignores ellipsis
        self.assertRegex(css_rule(css, ".num-s"), r"flex:\s*none")
        numbers = css_rule(css, ".num, .num-s, .n, .big, .fnum, .mv, .dnum")
        self.assertIn("white-space: nowrap", numbers)
        self.assertIn("overflow-wrap: normal", numbers)


class RulesTabTest(pf.PanelCase):
    def test_data(self):
        body = main_of(self.get("/rules")[2])
        self.assertIn("работает с 7 сентября", body)
        self.assertIn("черновик", body)
        self.assertIn("Пост с фото", body)
        self.assertIn('<button class="tog day on" type="submit" name="day" value="mon" '
                      'aria-pressed="true">Пн</button>', body)
        self.assertIn('value="10:00" aria-pressed="true">10:00</button>', body)
        self.assertIn("3 дня в неделю", body)
        self.assertIn("1 раз в день · 3 в неделю", body)
        self.assertIn("FB: до 3 в день, через 3 ч", body)
        self.assertIn("наша оценка, у площадок точной цифры нет", body)
        self.assertRegex(body, r"X: ≈\$\d+\.\d\d в неделю")
        self.assertIn("UTC+1", body)
        self.assertIn('<option value="Europe/Berlin">', body)
        self.assertRegex(body, r"36 из 90 · до 18 дек\.")
        row = body.split('id="rule-tips-ig"')[1]
        self.assertIn('role="alert"', row)
        self.assertIn("is a text lane and cannot feed Instagram", row)
        self.assertNotIn("снять все", body)   # days must stay non-empty: a no-op is hidden

    def test_limits_are_not_editable(self):
        body = self.get("/rules")[2]
        self.assertNotIn("max_per_day", body)
        self.assertNotIn('name="limit', body)


class CalendarTest(pf.PanelCase):
    def test_header_and_grid(self):
        body = main_of(self.get("/calendar")[2])
        self.assertIn("Ноябрь 2026", body)
        self.assertIn("публикаций в неделю", body)
        self.assertIn("правила в работе · ещё 2 в черновике", body)
        self.assertIn('<span class="mono big red">18 декабря 2026</span>', body)
        self.assertIn("контент кончится · city-main", body)
        self.assertNotIn("$", body)            # the X spend lives in the top bar only (§14)
        self.assertIn('class="cell today" id="today"', body)
        self.assertIn("показать ещё 3 месяца", body)
        months = re.findall(r'<section class="month" id="m-(\d{4}-\d\d)"', body)
        self.assertEqual(months, ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02"])
        more = main_of(self.get("/calendar?more=1")[2])
        self.assertEqual(len(re.findall(r'<section class="month"', more)), 8)

    def test_today_cell_is_named_in_words_for_everyone(self):
        body = main_of(self.get("/calendar")[2])
        cell = re.search(r'<a class="cell today" id="today"[^>]*>.*?</a>', body, re.S).group(0)
        self.assertRegex(cell, r'aria-label="11 ноября: [^"]*сегодня"')   # the accessible name
        self.assertIn('<span class="today-word">сегодня</span>', cell)  # visible text
        # a quiet today (no publications listed) is a plain cell whose text says it too
        quiet = main_of(self.get("/calendar?net=telegram")[2])
        today = re.search(r'<(?:a|div) class="cell today" id="today".*?</(?:a|div)>', quiet, re.S)
        self.assertIn("сегодня", today.group(0))
        # no other cell is named as today
        self.assertEqual(len(re.findall(r'aria-label="[^"]*сегодня"', body)), 1)
        with open(os.path.join(os.path.dirname(M.__file__), "static", "panel.css"),
                  encoding="utf-8") as fh:
            css = fh.read()
        narrow = css[css.index("@media (max-width: 899px)"):]
        self.assertNotRegex(narrow, r"\.today-word\s*\{[^}]*display:\s*none")

    def test_every_row_state_has_its_own_words(self):
        cases = {
            "2026-11-06": ["опубликован · city-23", "ошибка: HTTP 500 from LinkedIn",
                           "неизвестно — проверьте аккаунт", "10:00 CET"],
            "2026-10-26": ["X пропущен: бюджет", "10:00 CET"],
            "2026-10-19": ["пропущен: компьютер был выключен", "10:00 CEST"],
            "2026-12-18": ["нет контента"],
            "2026-11-12": ["Цитаты → FB", "правило не запущено", "17:00 WET"],
            "2026-11-03": ["опубликован (вручную)"],
        }
        for day, words in cases.items():
            body = main_of(self.get(f"/calendar?day={day}")[2])
            dialog = body.split('<dialog class="day"')[1].split("</dialog>")[0]
            for w in words:
                self.assertIn(w, dialog, (day, w))
        title = main_of(self.get("/calendar?day=2026-11-11")[2])
        self.assertIn("11 ноября · ср · сегодня", title)

    def test_only_publications_are_counted(self):
        for day, count in (("2026-11-06", "4 публикации"), ("2026-10-26", "3 публикации"),
                           ("2026-10-19", "0 публикаций"), ("2026-12-18", "0 публикаций"),
                           ("2026-11-12", "4 публикации")):
            head = main_of(self.get(f"/calendar?day={day}")[2]).split('<div class="day-head">')[1]
            self.assertIn(count, text_of(head.split("</div>")[0]), day)

    def test_network_filter(self):
        body = main_of(self.get("/calendar?day=2026-11-06&net=x")[2])
        dialog = body.split('<dialog class="day"')[1].split("</dialog>")[0]
        self.assertIn("неизвестно", dialog)
        self.assertNotIn("fb:", dialog)


class ReachTest(pf.PanelCase):
    def test_data(self):
        page = self.get("/reach")[2]
        sub = html.unescape(page.split('<p class="sub-left">')[1].split("</p>")[0])
        self.assertRegex(sub, r"^\d+ публикац\w+ · .+ просмотр\w* · .+ лайк\w* · .+ коммент")
        body = main_of(page)
        self.assertIn("Нет доступа: instagram_manage_insights", body)
        self.assertIn('class="sbtn on" href="/reach?sort=popular" aria-current="true">Популярные', page)
        self.assertIn("тыс", body)
        self.assertIn("открыть", body)
        self.assertIn('class="mono mv">—</span><span class="ml">сохран.', body)

    def test_weak_is_popular_reversed_with_unmeasured_posts_last(self):
        def views(body):
            return [m for m in re.findall(r'<div class="m m-views"><span class="mono mv">([^<]+)<',
                                          body)]
        popular = main_of(self.get("/reach")[2])
        weak = main_of(self.get("/reach?sort=weak")[2])
        n = popular.count('<li class="post">')
        measured = n - sum(1 for p in popular.split('<li class="post">')[1:]
                           if p.split("</li>")[0].count(">—</span>") == 5)
        self.assertEqual(views(weak)[:measured], views(popular)[:measured][::-1])
        self.assertIn("0", views(weak)[:measured])          # zero-view posts are listed
        body = weak
        last = body.split('<li class="post">')[-1]
        self.assertEqual(last.count(">—</span>"), 5, "a post without stats comes last")

    def test_never_collected(self):
        os.remove(os.path.join(self.fx.paths.state, "stats", "latest.json"))
        body = main_of(self.get("/reach")[2])
        self.assertIn("Статистика ещё не собиралась — python3 -m factory stats collect",
                      text_of(body))
        self.assertNotIn('<li class="post">', body)


class FollowersTest(pf.PanelCase):
    def test_data(self):
        page = self.get("/followers")[2]
        self.assertIn("подписчиков", page.split('<p class="sub-left">')[1].split("</p>")[0])
        self.assertIn('<span class="mono">4</span> аккаунта', page)
        body = main_of(page)
        self.assertRegex(body, r'<span class="delta mono red">−\d+</span>')
        self.assertIn('<svg class="spark down"', body)
        self.assertRegex(body, r'<span class="delta mono green">\+\d+</span>')
        self.assertIn("за 30 дней", body)
        self.assertIn("нет доступа: статистика профиля только для организаций", body)
        self.assertIn("выключено: чтение X платное (X_STATS=off)", body)
        numbers = [int(n.replace(" ", "")) for n in
                   re.findall(r'<span class="mono fnum">([\d ]+)</span>', body)]
        self.assertEqual(numbers, sorted(numbers, reverse=True))
        week = main_of(self.get("/followers?period=week")[2])
        self.assertIn("за 7 дней", week)

    def test_one_point_is_too_little(self):
        path = os.path.join(self.fx.paths.state, "stats", "latest.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["followers"] = {"fb:demo": [["2026-11-11", 400]]}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        body = main_of(self.get("/followers")[2])
        self.assertIn("мало данных", body)
        self.assertNotIn('class="delta', body)
        self.assertNotIn("<svg class=\"spark", body)


class DialogsTest(pf.PanelCase):
    def test_placeholder(self):
        status, _, page = self.get("/dialogs")
        self.assertEqual(status, 200)
        body = main_of(page)
        self.assertIn("Помощник в директе не подключён (отложено)", body)
        self.assertNotIn("<form", body)
        self.assertNotIn("<a ", body)


class EmptyTest(pf.PanelCase):
    FIXTURE = "empty"

    def test_every_tab_has_its_empty_state(self):
        expected = {
            "/connection": ["Ни у одной сети нет ключей", "нет ключей", "FB_PAGE_"],
            "/files": ["Папок пока нет", "новая папка в этой полосе"],
            "/rules": ["Правил пока нет", '<details class="newrule" open'],
            "/calendar": ["нет активных правил", "публикаций в неделю"],
            "/reach": ["Публикаций пока нет"],
            "/followers": ["Статистика ещё не собиралась — python3 -m factory stats collect",
                           "нет доступа: статистика профиля только для организаций",
                           "выключено: чтение X платное (X_STATS=off)"],
        }
        for path, words in expected.items():
            status, _, page = self.get(path)
            self.assertEqual(status, 200, path)
            body = main_of(page)
            for w in words:
                self.assertIn(w, body + text_of(body), (path, w))
        ring = main_of(self.get("/connection")[2])
        self.assertRegex(ring, r'class="ring-n"[^>]*>0<tspan')
        self.assertEqual(main_of(self.get("/files")[2]).count("новая папка в этой полосе"), 2)
        self.assertIn("таймер: ещё не запускался", self.get("/files")[2])


class ErrorStatesTest(pf.PanelCase):
    def test_missing_env_file(self):
        os.remove(self.fx.paths.env_file)
        for path in TABS:
            body = main_of(self.get(path)[2])
            self.assertIn("Нет файла ключей", body, path)
            self.assertIn("env file not found", body, path)
        self.assertIn("Помощник в директе", self.get("/dialogs")[2])

    def test_malformed_env_file(self):
        with open(self.fx.paths.env_file, "a", encoding="utf-8") as fh:
            fh.write("this is not a pair\n")
        body = main_of(self.get("/rules")[2])
        self.assertIn("Файл ключей с ошибкой", body)
        self.assertIn("malformed line(s)", body)

    def test_broken_rules_file(self):
        with open(self.fx.paths.rules, "w", encoding="utf-8") as fh:
            fh.write('{"schema": 1, "rules": [{"id": "Bad Id", "folder": "city"}]}\n')
        for path in ("/rules", "/files", "/calendar"):
            body = main_of(self.get(path)[2])
            self.assertIn("Файл правил с ошибкой", body, path)
            self.assertIn("id must match", body, path)
        self.assertIn("сети постера", main_of(self.get("/connection")[2]))
        self.assertIn('<li class="post">', main_of(self.get("/reach")[2]))
        self.assertIn("за 30 дней", main_of(self.get("/followers")[2]))

    def test_unreadable_stats_file(self):
        with open(os.path.join(self.fx.paths.state, "stats", "latest.json"), "w") as fh:
            fh.write("{not json")
        for path in ("/reach", "/followers"):
            self.assertIn("Статистика не читается", main_of(self.get(path)[2]), path)
            self.assertIn("latest.json", main_of(self.get(path)[2]), path)
        self.assertIn("работает с", main_of(self.get("/rules")[2]))
        with open(os.path.join(self.fx.paths.state, "stats", "collect.json"), "w") as fh:
            fh.write('{"results": []}')
        os.remove(os.path.join(self.fx.paths.state, "stats", "latest.json"))
        self.assertIn("collect.json", main_of(self.get("/reach")[2]))


class StringsTest(unittest.TestCase):
    def test_plural(self):
        words = ("папка", "папки", "папок")
        for n, w in ((1, "папка"), (2, "папки"), (5, "папок"), (11, "папок"), (21, "папка"),
                     (22, "папки"), (112, "папок"), (0, "папок")):
            self.assertEqual(S.plural(n, words), w, n)

    def test_numbers(self):
        self.assertEqual(S.abbrev(7_100_000), "7,1 млн")
        self.assertEqual(S.abbrev(48_000_000), "48 млн")
        self.assertEqual(S.abbrev(70_000), "70 тыс")
        self.assertEqual(S.abbrev(1_200), "1,2 тыс")
        self.assertEqual(S.abbrev(999_600), "1,0 млн")
        self.assertEqual(S.abbrev(459), "459")
        self.assertEqual(S.group(531_571), "531 571")
        self.assertEqual(S.signed(2025), "+2 025")
        self.assertEqual(S.signed(-12), "−12")
        self.assertEqual(S.signed(0), "0")

    def test_dates(self):
        d = dt.date(2026, 12, 19)
        self.assertEqual(S.day_month(d), "19 декабря")
        self.assertEqual(S.day_short(d), "19 дек.")
        self.assertEqual(S.month_title(2026, 11), "Ноябрь 2026")
        self.assertEqual(S.ago(35), "35 мин")
        self.assertEqual(S.ago(125), "2 ч")


class ModelTest(unittest.TestCase):
    def row(self, metrics, day):
        return M.ReachRow("t", "facebook", str(day), None,
                          dt.datetime(2026, 11, day, tzinfo=dt.timezone.utc), "p", "x", None,
                          metrics)

    def test_reach_sorts(self):
        a = self.row({"views": 10, "likes": 1}, 1)
        b = self.row({"views": 0}, 2)
        c = self.row({"likes": 50, "comments": 5}, 3)      # no views: after posts with views
        d = self.row({}, 4)                                 # not measured: last
        self.assertEqual(M.sort_reach([a, b, c, d], "popular"), [a, b, c, d])
        self.assertEqual(M.sort_reach([a, b, c, d], "weak"), [c, b, a, d])
        self.assertEqual(M.sort_reach([a, b, c, d], "new"), [d, c, b, a])
        self.assertEqual(M.sort_reach([a, b, c, d], "old"), [a, b, c, d])
        self.assertEqual(M.sort_reach([a, b, c, d], "likes"), [c, a, b, d])

    def test_zone_offset(self):
        now = dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc)
        self.assertEqual(M.zone_offset("Europe/Berlin", now), "UTC+1")
        self.assertEqual(M.zone_offset("America/St_Johns", now), "UTC−3:30")
        self.assertEqual(M.zone_offset("Mars/Base", now), "")


if __name__ == "__main__":
    unittest.main()
