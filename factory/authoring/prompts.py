"""Gemini models, schemas and bounded prompts (authoring.md §8.4)."""
import math

from poster import rules
from factory.authoring import cases as fcases, profile

TEXT_MODEL = "gemini-3.8-flash"
VOICE_MODEL = "gemini-3.5-flash-lite"
IMAGE_MODEL = "gemini-nano-banana-2.1"          # slice C (authoring.md §9.2, §18 D32)
OUTPUT = {"topics": 2000, "expand": 6000, "regenerate": 2500, "voice": 2000}
# The highlight's output is bounded by one 2K image (1 680 tokens) plus 1 000 for text and
# thought (D32, G17 unconfirmed until LC3); the request carries no max_output_tokens (§9.2),
# so it stays out of OUTPUT, which is each text call's max_output_tokens.
IMAGE_OUTPUT = {"highlight": 1680 + 1000}
# The photo's tokens on the image model, an upper bound: the request sets no resolution (the
# model refuses the field), so the real count is unobserved (D32, G17).
IMAGE_TOKENS = {"highlight": 2240}
QUOTE_MAX = 140                      # a stored quote (authoring.md §18.2)
INSTRUCTIONS = (
    "You help the author write social posts about their own themes and their own cases: what "
    "they automated, with which AI tools, and what came of it. The subject of a post is the "
    "topic below. A photo, when one is attached, only illustrates the post: never take the "
    "subject from it. Never invent facts beyond the topic, the author profile, the case below "
    "and what the photo shows: no invented cases, clients, numbers, dates, tools or results. "
    "When a fact is not given, leave it out. Never name people in the photo. Do not describe "
    "the photo's technical qualities."
)
# §19.5: the topics tasks, on a draft without a case and on one that carries a case
TOPICS_TASK = (
    "Suggest 3 to 5 distinct post topics. Each topic draws either on the author's themes (the "
    "profile line \"Author's themes\") or on exactly one of the cases listed above; never combine "
    "cases and never suggest a case that is not listed. title: at most 80 characters, in "
    "Russian. angle: one sentence in Russian saying what the post would say and for whom (at "
    "most 1000 characters). case: the id of the case the topic draws on, or an empty string "
    "when it draws on the author's themes."
)
ANGLES_TASK = (
    "Suggest 3 to 5 distinct angles for a post about the case above. Every topic draws on that "
    "case only, so case is its id. title: at most 80 characters, in Russian. angle: one "
    "sentence in Russian saying what the post would say and for whom (at most 1000 "
    "characters)."
)
RULES = {
    "x": (f"English; short and sharp, at most 240 weighted characters (Latin and Cyrillic 1, "
          f"emoji 2); hard limit {rules.X_MAX_WEIGHTED} weighted, at most {rules.X_MAX_CASHTAGS} cashtag. "
          "No URL unless the topic contains one (a URL raises the X price from $0.015 to $0.200)."),
    "linkedin": (f"English; business angle, 600–1300 characters, short paragraphs, at most 3 hashtags; "
                 f"hard limit {rules.LI_MAX_COMMENTARY} after little-format escaping."),
    "instagram": (f"Ukrainian; lively caption with a hook in the first 125 characters, at most 1500 "
                  f"characters, 3–8 hashtags at the end, no links; hard limits {rules.IG_MAX_CAPTION} "
                  f"UTF-16 units, {rules.IG_MAX_HASHTAGS} hashtags, {rules.IG_MAX_MENTIONS} mentions."),
    "facebook": "Ukrainian; conversational, 400–900 characters, 0–3 hashtags.",
}


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties),
            "additionalProperties": False}


STRING = {"type": "string"}
SCHEMAS = {
    "topics": obj({"topics": {"type": "array", "minItems": 3, "maxItems": 5,
                              "items": obj({"title": STRING, "angle": STRING, "case": STRING})}}),
    "expand": obj(dict({n: STRING for n in RULES}, quotes=obj({n: STRING for n in RULES}))),
    "regenerate": obj({"text": STRING}),
}


def case_block(op, draft, cases=()):
    """The case block of §19.5 for this call: the draft's case record when it carries a stored
    one; otherwise the gist of every stored case (topics) or «none chosen» (texts)."""
    case = fcases.find(cases, draft.get("case"))
    if case is not None:
        return case, fcases.record(case)
    if op == "topics":
        return None, fcases.gist(cases)
    return None, fcases.NONE_CHOSEN


def build(op, author, draft, network="", wish="", cases=()):
    if op == "voice":
        task = ("Transcribe this voice note verbatim in the language spoken (Russian, Ukrainian "
                "or English). Output only the transcript, no comments.")
        return task
    case, block = case_block(op, draft, cases)
    if op == "topics":
        task = ANGLES_TASK if case is not None else TOPICS_TASK
    else:
        task = "Write one post per network, in the first person as the author, on the topic below."
        if op == "regenerate":
            task = (f"Rewrite only the {network} post. Keep its language and rules. "
                    f"The author's wish: {wish or 'none'}.\nCurrent text: "
                    + draft.get("variants", {}).get(network, {}).get("text", ""))
        task += "\n" + "\n".join(f"{n}: {r}" for n, r in RULES.items() if op == "expand" or n == network)
        if op == "expand":
            task += ("\nquotes: for each network, one short line for the photo itself, at most 90 "
                     "characters, in that network's language, with no hashtags and no links.")
        task += "\nTopic: " + draft.get("topic", "")
        task += "\nReturn every text whole, at most 5000 characters per text."
    return INSTRUCTIONS + "\n" + profile.prompt(author) + "\n" + block + "\n" + task


# ---------------------------------------------------------------- slice C: highlight (§9.2)

STYLES = {
    "blur": ("Blur the background as with a shallow depth of field. Keep the main person sharp "
             "and every pixel of their face, body and clothes unchanged."),
    "glow": ("Add a soft warm rim light and glow around the main person. Do not change the face, "
             "features, body, clothes or the background content."),
    "outline": "Add a thin soft white outline around the main person, sticker-like. Change nothing else.",
}
ASPECTS = ("1:1", "4:5", "5:4", "3:4", "4:3", "2:3", "3:2", "9:16", "16:9")


def highlight(style, who=""):
    """The highlight instruction (§18.5 item 5): the style's line, the main person, the
    operator's optional description, and the closing rule."""
    lines = [STYLES[style], "The main person is the most prominent person in the photo."]
    if who.strip():
        lines.append("The main person: " + who.strip())
    lines.append("Do not add text, logos or other people.")
    return "\n".join(lines)


def aspect(w, h):
    """The nearest of §9.2's list to w:h, by |log r - log c|."""
    r = math.log(w / h)

    def gap(name):
        a, b = name.split(":")
        return abs(r - math.log(int(a) / int(b)))
    return min(ASPECTS, key=gap)
