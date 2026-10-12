"""The spoken morning briefing: what NOVA says aloud when asked "what matters today?".

Pure (no I/O). The script is built from facts already computed for the Today page — counts and the top items — with
fixed sentences, not a model: it says nothing that is not on screen, and costs nothing to produce. Items classified
C2/C3 are never read aloud (people nearby could hear them): they are announced as classified, to be read on screen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Lang = Literal["en", "fr"]
SPEAK_LIMIT_CLASSIFICATION = 1  # items above this are not spoken
MAX_ITEMS = 3
MAX_TITLE = 110

_URL = re.compile(r"https?://\S+")
_MARKUP = re.compile(r"[*_`#>\[\]]")

T: dict[str, dict[Lang, str]] = {
    "hello": {"en": "Hello {name}.", "fr": "Bonjour {name}."},
    "nothing": {
        "en": "Nothing needs your attention right now.",
        "fr": "Rien ne demande votre attention pour le moment.",
    },
    "attention_one": {"en": "One item needs you.", "fr": "Un élément a besoin de vous."},
    "attention_many": {"en": "{n} items need you.", "fr": "{n} éléments ont besoin de vous."},
    "running_one": {"en": "NOVA is working on one task.", "fr": "NOVA travaille sur une tâche."},
    "running_many": {"en": "NOVA is working on {n} tasks.", "fr": "NOVA travaille sur {n} tâches."},
    "results_one": {"en": "One result is ready.", "fr": "Un résultat est prêt."},
    "results_many": {"en": "{n} results are ready.", "fr": "{n} résultats sont prêts."},
    "first": {"en": "First: {title}.", "fr": "D’abord : {title}."},
    "next": {"en": "Then: {title}.", "fr": "Ensuite : {title}."},
    "classified": {
        "en": "a classified item, to read on screen",
        "fr": "un élément classifié, à consulter à l’écran",
    },
    "closing": {"en": "Everything is in your Inbox.", "fr": "Tout est dans votre Inbox."},
}


@dataclass(frozen=True, slots=True)
class BriefItem:
    title: str
    classification: int = 1


def _say(lang: Lang, key: str, **values: object) -> str:
    return T[key][lang].format(**values)


def speakable(title: str) -> str:
    """A title as it is read aloud: no links or markup, one line, not too long."""
    text = _MARKUP.sub("", _URL.sub("", title))
    text = " ".join(text.split()).strip(" .:;-—")
    return text if len(text) <= MAX_TITLE else text[: MAX_TITLE - 1].rstrip() + "…"


def script(
    first_name: str, lang: Lang, *, actions_required: int, running: int, results_ready: int, items: list[BriefItem]
) -> tuple[list[str], int]:
    """``(sentences, items_kept_off_the_air)``: the briefing and how many items were not read out."""
    sentences = [_say(lang, "hello", name=speakable(first_name) or "")]
    sentences[0] = sentences[0].replace("  ", " ").replace(" .", ".")
    if actions_required == 0 and running == 0 and results_ready == 0:
        sentences.append(_say(lang, "nothing"))
        return sentences, 0
    if actions_required:
        sentences.append(
            _say(lang, "attention_one") if actions_required == 1 else _say(lang, "attention_many", n=actions_required)
        )
    if running:
        sentences.append(_say(lang, "running_one") if running == 1 else _say(lang, "running_many", n=running))
    if results_ready:
        sentences.append(_say(lang, "results_one") if results_ready == 1 else _say(lang, "results_many", n=results_ready))
    withheld = 0
    for index, item in enumerate(items[:MAX_ITEMS]):
        if item.classification > SPEAK_LIMIT_CLASSIFICATION:
            withheld += 1
            title = _say(lang, "classified")
        else:
            title = speakable(item.title)
            if not title:
                continue
        sentences.append(_say(lang, "first" if index == 0 else "next", title=title))
    sentences.append(_say(lang, "closing"))
    return sentences, withheld
