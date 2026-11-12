"""Gemini models, schemas and bounded prompts (authoring.md §8.4)."""
from poster import rules
from factory.authoring import profile

TEXT_MODEL = "gemini-3.8-flash"
VOICE_MODEL = "gemini-3.5-flash-lite"
OUTPUT = {"topics": 2000, "expand": 6000, "regenerate": 2500, "voice": 2000}
INSTRUCTIONS = (
    "You help the author write social posts built around this photo. The photo shows the "
    "author or their world. Never invent facts beyond the topic, the author profile and what "
    "the photo shows. Never name people in the photo. Do not describe the photo's technical qualities."
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
                              "items": obj({"title": STRING, "angle": STRING})}}),
    "expand": obj({n: STRING for n in RULES}),
    "regenerate": obj({"text": STRING}),
}


def build(op, author, draft, network="", wish=""):
    if op == "voice":
        task = ("Transcribe this voice note verbatim in the language spoken (Russian, Ukrainian "
                "or English). Output only the transcript, no comments.")
        return task
    if op == "topics":
        task = ("Suggest 3 to 5 distinct post topics that fit this photo and the author's themes "
                "and audiences. title: at most 80 characters, in Russian. angle: one sentence "
                "in Russian saying what the post would say and for whom (at most 1000 characters).")
    else:
        task = "Write one post per network, in the first person as the author, on the topic below."
        if op == "regenerate":
            task = (f"Rewrite only the {network} post. Keep its language and rules. "
                    f"The author's wish: {wish or 'none'}.\nCurrent text: "
                    + draft.get("variants", {}).get(network, {}).get("text", ""))
        task += "\n" + "\n".join(f"{n}: {r}" for n, r in RULES.items() if op == "expand" or n == network)
        task += "\nTopic: " + draft.get("topic", "")
        task += "\nReturn every text whole, at most 5000 characters per text."
    return INSTRUCTIONS + "\n" + profile.prompt(author) + "\n" + task
