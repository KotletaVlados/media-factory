"""Every UI string of the panel, in Russian (design factory.md §11.11), plus Russian dates
and numbers. A second language later is a second table of the same names, not a refactor.

Core messages (checks, attention items, record errors) stay in English and are shown after a
Russian label, so no logic from `factory.checks` or `factory.attention` is copied here.
"""

from __future__ import annotations

import datetime as _dt
import re

TABS = (
    ("create", "Создать"),
    ("connection", "Подключение"),
    ("files", "Медиатека"),
    ("rules", "Правила"),
    ("calendar", "Календарь"),
    ("reach", "Охваты"),
    ("followers", "Подписчики"),
)
DIALOGS_OFF = "Диалоги · выкл"
APP_TITLE = "Медиа-фабрика"
NAV_LABEL = "Разделы"

# ---------------------------------------------------------------- shell and states
ATTENTION = "Внимание"
ATTENTION_NONE = "Ничего не требует внимания"
ATTENTION_HIDE = "скрыть"
PROBLEM = "Проблема:"
ERR_ENV_MISSING = "Нет файла ключей"
ERR_ENV_BAD = "Файл ключей с ошибкой"
ERR_RULES = "Файл правил с ошибкой"
ERR_RULES_HINT = "Исправьте content/rules.json, затем python3 -m factory check"
ERR_STATS = "Статистика не читается"
ERR_OTHER = "Ошибка панели"
NOT_FOUND = "Страница не найдена"
STALE = "Правила изменились в другом месте — обновите страницу"
RULE_REFUSED = "Правило «{id}» не изменено: проверки не пройдены, файл правил остался прежним."
NEW_REFUSED = "Новое правило не сохранено: проверки не пройдены, файл правил остался прежним."
TO_RULE = "к правилу"
TO_FOLDER = "к форме"
FOLDER_REFUSED = "Папка не создана:"
RELOAD = "обновить"
LINKEDIN_DAYS = "LinkedIn: {n} дн."
LINKEDIN_LOGIN = "LinkedIn: нужен вход"
TIMER_AGO = "таймер: {ago} назад"
TIMER_NEVER = "таймер: ещё не запускался"
TIMER_SILENT = "таймер молчит {ago}"
X_METER = "X {month} ${spent} из ${cap}"
X_PLAN = "план +${planned}"

# ---------------------------------------------------------------- networks
MONO = {"facebook": "FB", "instagram": "IG", "x": "X", "linkedin": "in",
        "telegram": "TG", "threads": "TH", "youtube": "YT", "tiktok": "TT", "pinterest": "PI"}
NET_NAME = {"facebook": "Facebook", "instagram": "Instagram", "x": "X", "linkedin": "LinkedIn",
            "telegram": "Telegram", "threads": "Threads", "youtube": "YouTube",
            "tiktok": "TikTok", "pinterest": "Pinterest"}
BUILT = ("instagram", "facebook", "x", "linkedin")
NOT_BUILT = ("telegram", "youtube", "threads", "pinterest", "tiktok")

# ---------------------------------------------------------------- connection
ACCOUNTS = "Аккаунты"
MAIN_PROFILE = "основной профиль"
OTHER_PAGES = "другие страницы"
RING_OF = "{n} из 4"
RING_CAPTION = "сети постера"
TARGETS_IN_ENV = "{n} {word} в файле ключей"
TARGET_WORDS = ("цель", "цели", "целей")
ST_CONNECTED = "подключено"
ST_LOGIN = "нужен вход"
ST_TOKEN = "ошибка токена"
ST_NO_KEYS = "нет ключей"
ST_NOT_BUILT = "не построено"
PICK_NODE = "Выберите сеть на кольце, чтобы увидеть переменные, токен и последнюю публикацию."
VARS = "Переменные"
VAR_PRESENT = "есть"
VAR_MISSING = "нет"
TOKEN_UNTIL = "Токен действует до {date} ({n} дн.)"
TOKEN_EXPIRED = "Токен истёк {date}"
TOKEN_NONE = "Токена нет"
LAST_PUBLISH = "Последняя публикация"
LAST_STATS = "Последний сбор статистики"
NONE_YET = "ещё не было"
COLLECT_OK = "собрано"
COLLECT_OFF = "выключено"
COLLECT_TOKEN = "токен отклонён"
COLLECT_NO_PERMISSION = "нет разрешения {name}"
COLLECT_HTTP = "ошибка HTTP {status}"
HOW_TO = "Как подключить"
HOW_ENV = "Впишите переменные в файл ключей .env (имена — в KEYS.md), значения не показываются здесь."
HOW_LINKEDIN = "python3 -m poster login linkedin"
NOT_BUILT_TEXT = "Постер не публикует в эту сеть: модуль не построен."
EMPTY_CONNECTION = ("Ни у одной сети нет ключей. Заполните файл ключей .env по KEYS.md: "
                    "для каждой сети ниже — имена её переменных.")
OPEN = "открыть"

# ---------------------------------------------------------------- files
LANES = {"photo": "Фото-посты", "text": "Текстовые посты"}
LANE_NONE = "Без полосы"
FOLDER_WORDS = ("папка", "папки", "папок")
PACKAGE_WORDS = ("пакет", "пакета", "пакетов")
FILE_WORDS = ("файл", "файла", "файлов")
FILES_EMPTY = "Папок пока нет"
NEW_FOLDER = "новая папка в этой полосе"
NEW_FOLDER_NAME = "Имя папки (латиница, цифры, -)"
NEW_FOLDER_TITLE = "Заголовок"
NEW_FOLDER_SAVE = "Создать"
FOLDER_EXISTS = "Папка «{name}» уже есть"
FOLDER_BAD_NAME = "Имя папки: строчные латинские буквы, цифры и «-», до 40 знаков"
FOLDER_BAD_LANE = "Полоса: photo или text"
FOLDER_CREATED = "Папка создана"
RUNWAY_NOBODY = "никто не берёт · расход 0"
RUNWAY_LONG = "> 400 дней ✓"
RUNWAY_FULL = "{n} дней ✓"
RUNWAY_OF = "{n} из 90 дней"
FIX_K = "нужно исправить: {n}"
UNAPPROVED_K = "не одобрено: {n}"
ALL_FOLDERS = "← все папки"
NO_FOLDER = "Папки «{name}» нет"
FOLDER_NO_PACKAGES = "В папке пока нет пакетов"
NO_TARGETS = "ни одно правило не берёт эту папку"
PKG_STATE = {"ready": "ждёт", "used": "использован", "invalid": "нужно исправить",
             "not-approved": "не одобрено", "held": "задержан",
             "check-account": "неизвестно — проверьте аккаунт"}
PKG_PUBLISHED = "опубликован · {date}"
PKG_PLANNED = "запланирован · {date}"
NO_IMAGE = "без картинки"

# ---------------------------------------------------------------- photos (authoring.md §6)
PHOTO_WORD = "фото"                     # indeclinable: "1 фото", "120 фото"
PHOTOS_H = "Фото"
UPLOAD_DIR = "Загрузить папку"
UPLOAD_FILES = "Добавить фото"
PHOTOS_EMPTY = "Фото пока нет: загрузите папку или отдельные снимки (JPEG, PNG, WebP)."
PHOTOS_NEED_JS = "Загрузка фото работает только с включённым JavaScript."
PHOTOS_MORE = "показать ещё"
PHOTOS_SHOWN = "{shown} из {total}"
PHOTO_USE = {"draft": "черновик", "queued": "в очереди", "published": "опубликовано"}
# upload refusals (JSON replies of POST /files/photos)
UP_BAD_KIND = "kind: orig, thumb или view"
UP_NO_FOLDER = "такой папки нет"
UP_NOT_PHOTO_LANE = "папка «{name}» не из полосы фото-постов"
UP_PHOTOS_NOT_DIR = "photos в этой папке — не каталог (ссылка или файл)"
UP_NO_PHOTO = "фото не найдено: сначала загружается оригинал"
UP_THUMB_FIRST = "сначала загружается миниатюра"
UP_TOO_MANY = "в папке уже {n} фото — создайте новую папку"
UP_NO_SPACE = "на диске меньше 1 ГБ свободного места"
UP_CUT = "загрузка оборвалась — повторите"
UP_NOT_IMAGE = "не JPEG, PNG или WebP (HEIC: экспортируйте JPEG)"
UP_NOT_JPEG = "копия должна быть JPEG"
UP_NO_SIZE = "размер картинки не читается"
UP_TOO_LARGE = "файл больше {mb} МБ"
UP_BAD_TYPE = "этот тип файла не принимается: JPEG, PNG или WebP"
UP_FORBIDDEN = "запрос отклонён: обновите страницу панели"
UP_LENGTH = "нет или неверный Content-Length"
UP_FAILED = "ошибка панели при загрузке"
# the upload loop in author.js (passed as data-strings; {n}, {done}, {total} are filled there)
UPLOAD_JS = {
    "running": "Загрузка…",
    "done": "Готово:",
    "progress": "загружено {done} из {total}",
    "dup": "уже были: {n}",
    "skipped": "пропущено {n}",
    "too_many": "Выбрано {n} {files} — выберите не больше 300 за раз.",
    "files": ["файл", "файла", "файлов"],
    "stopped": "Загрузка остановлена: {reason}",
    "heic": "формат HEIC не открывается — экспортируйте JPEG",
    "type": "не JPEG, PNG или WebP",
    "decode": "браузер не открыл файл",
    "network": "нет связи с панелью",
    "reload": "обновить",
    "reload_new": "показать загруженные",
}

# ---------------------------------------------------------------- rules
COL_START = "Пуск"
COL_ACCOUNT = "Аккаунт"
COL_SOURCE = "Откуда брать контент"
COL_TARGET = "Куда публиковать"
COL_DAYS = "Дни недели"
COL_HOURS = "Время публикаций"
COL_TZ = "Часовой пояс"
ALL = "Все"
DRAFT = "черновик"
RUNNING_SINCE = "работает с {date}"
START = "Запустить правило {id}"
STOP = "Остановить правило {id}"
FORMAT_PHOTO = "Пост с фото"
FORMAT_TEXT = "Текст"
DAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
DAYS_LOWER = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
DAY_WORDS = ("день", "дня", "дней")
TIMES_WORDS = ("раз", "раза", "раз")
DAYS_A_WEEK = "{n} {word} в неделю"
CLEAR_ALL = "снять все"
SELECT_ALL = "выбрать все"
TIMES_A_DAY = "{n} {word} в день · {w} в неделю"
LIMIT_HINT = "{net}: до {n} в день, через {gap} ч"
LIMIT_NOTE = "наша оценка, у площадок точной цифры нет"
LIMIT_NOTE_X = "наша оценка, у площадок точной цифры нет; для X предел — $5 в месяц"
LIMIT_BASIS = {
    "facebook": "наша оценка; цифры платформы нет",
    "instagram": "наша оценка; потолок API 50 постов за 24 ч",
    "linkedin": "наша оценка; потолок API 150 публикаций в день",
    "x": "наша оценка; настоящий лимит — $5 в месяц",
}
X_WEEK = "X: ≈${cost} в неделю"
ZONE_SAVE = "OK"
ZONE_LABEL = "Часовой пояс правила {id}"
RULES_EMPTY = "Правил пока нет"
NEW_RULE = "+ Новое правило"
NEW_RULE_ID = "Имя правила (латиница, цифры, -)"
NEW_RULE_FOLDER = "Папка"
NEW_RULE_TARGETS = "Цели"
NEW_RULE_SAVE = "Сохранить черновик"
NO_FOLDERS_YET = "На складе ещё нет папок; сначала создайте папку:"
NO_RULE = "Правила «{id}» нет"
RULE_EXISTS = "Правило «{id}» уже есть"
NO_STOCK_FOLDER = "нет папки"

# ---------------------------------------------------------------- calendar
TODAY = "сегодня"
PUBS_WEEK = ("публикация в неделю", "публикации в неделю", "публикаций в неделю")
RULES_RUNNING = ("правило в работе", "правила в работе", "правил в работе")
DRAFTS_MORE = "ещё {n} в черновике"
RUNOUT_LABEL = "контент кончится · {rule}"
RUNOUT_NONE = "нет активных правил"
RUNOUT_LONG = "> 400 дней"
RUNOUT_LONG_LABEL = "контента хватит"
PUB_WORDS = ("публикация", "публикации", "публикаций")
MORE_MONTHS = "показать ещё 3 месяца"
CLOSE = "Закрыть"
DAY_EMPTY = "В этот день ничего нет"
S_PUBLISHED = "опубликован"
S_MANUAL = "опубликован (вручную)"
S_FAILED = "ошибка"
S_UNKNOWN = "неизвестно — проверьте аккаунт"
S_SKIPPED = "пропущен"
S_X_BUDGET = "X пропущен: бюджет"
S_NO_CONTENT = "нет контента"
S_DRAFT = "правило не запущено"
S_DUE = "ждёт таймера"
S_CLAIMED = "публикуется сейчас"
S_REFUSED = "отказ"
S_INTERRUPTED = "прерван — проверьте аккаунт"
S_RESOLVED_YES = "проверен: опубликован"
S_RESOLVED_NO = "проверен: не опубликован"
S_OVER_LIMIT = "не пройдёт лимит"
MISSED_REASONS = {"off": "компьютер был выключен", "superseded": "заменён более поздним слотом",
                  "gap": "слишком близко к прошлому посту", "limit": "лимит сети в день",
                  "no-content": "нет контента"}

# ---------------------------------------------------------------- reach
REACH_NEVER = "Статистика ещё не собиралась —"
STATS_COMMAND = "python3 -m factory stats collect"
REACH_NO_POSTS = "Публикаций пока нет"
SORTS = (("popular", "Популярные"), ("weak", "Слабые"), ("new", "Свежие"), ("old", "Старые"),
         ("likes", "По лайкам"))
METRICS = (("views", "просмотры"), ("likes", "лайки"), ("comments", "коммент."),
           ("saves", "сохран."), ("reposts", "репосты"))
TOTALS_WORDS = {"views": ("просмотр", "просмотра", "просмотров"),
                "likes": ("лайк", "лайка", "лайков"),
                "comments": ("комментарий", "комментария", "комментариев")}
NO_ACCESS = "Нет доступа: {perm}"
NO_METRIC = "—"
NOT_IN_STATS = "нет в статистике"

# ---------------------------------------------------------------- followers
FOLLOWER_WORDS = ("подписчик", "подписчика", "подписчиков")
ACCOUNT_WORDS = ("аккаунт", "аккаунта", "аккаунтов")
PERIODS = (("week", "Неделя"), ("30", "30 дней"), ("90", "90 дней"), ("all", "Всё время"))
FOR_DAYS = "за {n} {word}"
FEW_POINTS = "мало данных"
LINKEDIN_CARD = "нет доступа: статистика профиля только для организаций (Community Management API)"
X_OFF_CARD = "выключено: чтение X платное (X_STATS=off)"
X_ON_CARD = "включено (X_STATS=weekly), данных пока нет"

# ---------------------------------------------------------------- dialogs
DIALOGS_TITLE = "Помощник в директе не подключён (отложено)"
DIALOGS_REASONS = (
    "Нужно отдельное разрешение Meta на сообщения (наша оценка, не проверено).",
    "Нужен адрес, который всегда принимает вебхуки, а этот компьютер не работает круглосуточно.",
    "Каждый ответ — платный вызов модели.",
    "Риск ответить от имени оператора тем, чего он не говорил.",
)
DIALOGS_TRIGGER = "Включается решением оператора («директ: да»)."

# ---------------------------------------------------------------- dates and numbers
MONTHS_NOM = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
              "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
              "сентября", "октября", "ноября", "декабря")
MONTHS_SHORT = ("янв.", "февр.", "мар.", "апр.", "мая", "июн.", "июл.", "авг.", "сент.",
                "окт.", "нояб.", "дек.")
NBSP = " "
MINUS = "−"


def collect_result(result: str) -> str:
    """A stats/collect.json per-target result (design §5: ok, off, not built, token rejected,
    no-permission <name>, HTTP n code c) in Russian; an unknown value is shown as stored."""
    text = str(result).strip()
    fixed = {"ok": COLLECT_OK, "off": COLLECT_OFF, "not built": ST_NOT_BUILT,
             "token rejected": COLLECT_TOKEN}
    if text in fixed:
        return fixed[text]
    if text.startswith("no-permission "):
        return COLLECT_NO_PERMISSION.format(name=text[len("no-permission "):].strip())
    m = re.match(r"HTTP (\d+)(?: code (\S+))?$", text)
    if m:
        out = COLLECT_HTTP.format(status=m.group(1))
        return out + (f", код {m.group(2)}" if m.group(2) else "")
    return text


def plural(n: int, forms: tuple) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def count(n: int, forms: tuple) -> str:
    return f"{group(n)} {plural(n, forms)}"


def day_month(d: _dt.date) -> str:
    """12 ноября"""
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def day_month_year(d: _dt.date) -> str:
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def day_short(d: _dt.date) -> str:
    """19 дек."""
    return f"{d.day} {MONTHS_SHORT[d.month - 1]}"


def month_title(year: int, month: int) -> str:
    return f"{MONTHS_NOM[month - 1]} {year}"


def month_lower(month: int) -> str:
    return MONTHS_NOM[month - 1].lower()


def group(n) -> str:
    """2 025 (thin groups with a no-break space)."""
    sign = MINUS if n < 0 else ""
    return sign + f"{abs(int(n)):,}".replace(",", NBSP)


def signed(n: int) -> str:
    if n > 0:
        return "+" + group(n)
    if n < 0:
        return group(n)
    return "0"


def _decimal(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def abbrev(n) -> str:
    """7,1 млн · 70 тыс · 1,2 тыс · 459, as the video writes them."""
    n = int(n)
    a = abs(n)
    sign = MINUS if n < 0 else ""
    if a >= 1_000_000:
        v = a / 1_000_000
        return sign + (_decimal(v) if v < 10 else str(int(round(v)))) + NBSP + "млн"
    if a >= 1_000:
        v = a / 1_000
        if v >= 999.5:
            return sign + "1,0" + NBSP + "млн"
        return sign + (_decimal(v) if v < 10 else str(int(round(v)))) + NBSP + "тыс"
    return sign + str(a)


def ago(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин"
    if minutes < 48 * 60:
        return f"{minutes // 60} ч"
    return f"{minutes // (24 * 60)} дн."

# ---------------------------------------------------------------- Создать (authoring.md §8)
CREATE_DROP = "Бросьте фото сюда"
CREATE_PICK = "Выбрать фото"
CREATE_FORMATS = "JPEG, PNG или WebP"
CREATE_RECENT_HINT = "Нажмите на фото, чтобы начать пост"
DRAFT_STAGE = {"new": "без темы", "topic": "своя тема", "topics": "темы", "texts": "тексты готовы",
               "over": "длиннее лимита", "error": "ошибка"}
CREATE_PROFILE_EMPTY = "Профиль автора не заполнен — темы и тексты будут общими"
CREATE_PROFILE_FILLED = "Профиль автора · заполнен"
CREATE_PROFILE_HINT = ("Профиль уходит в каждый запрос к Gemini вместе с фото. "
                       "Хранится только на этом компьютере.")
CREATE_NEED_JS = "Создание постов работает только с включённым JavaScript."
CREATE_JS = {
    "uploading": "Загрузка фото…", "drafting": "Создаю черновик…",
    "many": "Перетащите одно фото", "drop": "Отпустите — загружу",
    "topics_loading": "Gemini подбирает темы…", "expand_loading": "Gemini пишет тексты…",
    "saved": "сохранено", "saving": "сохраняю…", "chosen": "выбрано", "voice": "Голос",
    "stop": "Стоп", "transcribing": "расшифровка…", "voice_retry": "Повторить расшифровку",
    "voice_denied": "микрофон запрещён в браузере", "voice_missing": "микрофон не найден",
    "voice_context": "запись голоса работает только по адресу localhost",
    "voice_unsupported": "браузер не записывает звук — откройте панель в Chrome или Edge",
    "network": "нет связи с панелью — повторите", "empty_topic": "выберите тему или впишите свою",
    "expand": "Развернуть", "expand_again": "Развернуть заново — правки пропадут",
    "topics": "Предложить темы", "more_topics": "Ещё темы", "regenerate": "Перегенерировать",
    "wish": "пожелание: короче, без хештегов…", "repeat": "Повторить", "text_long": "текст длиннее 5 000 знаков",
    "topic_long": "тема: не больше 2000 знаков", "before_texts": "Тексты появятся после «Развернуть»",
}
CREATE_NETWORKS = {"x": "X · англ.", "linkedin": "LinkedIn · англ.",
                   "instagram": "Instagram · укр.", "facebook": "Facebook · укр."}
