"""Görsel/video komutları için sabit kontrol: reşit olmayan izlenimi veren her şey engellenir."""
import re

_MINOR_TERMS = [
    r"child", r"children", r"kid", r"kids", r"minor", r"underage", r"teen", r"teens", r"teenage", r"teenaged",
    r"teenager", r"teenagers", r"adolescent", r"adolescents", r"jailbait",
    r"preteen", r"loli", r"shota", r"toddler", r"infant", r"baby", r"schoolgirl", r"schoolboy",
    r"young girl", r"young boy", r"little girl", r"little boy", r"juvenile", r"pubescent",
    r"school uniform", r"elementary", r"middle school", r"high school",
    r"çocuk", r"cocuk", r"bebek", r"ergen", r"reşit olmayan", r"resit olmayan", r"küçük kız", r"küçük oğlan",
    r"ilkokul", r"ortaokul", r"lise", r"liseli",
]
_MINOR_RE = re.compile(r"\b(" + "|".join(_MINOR_TERMS) + r")\b", re.I)
_AGE_RE = re.compile(r"\b(1[0-7]|[1-9])[\s-]*(year[s]?[\s-]*old|yo|yaşında|yasinda)\b", re.I)


def minor_characters(card):
    """Kartta 18 yaşından küçük ya da yaşı belirsiz görünen karakterlerin adları."""
    names = []
    for c in card.get("karakterler", []):
        try:
            young = int(c.get("yas")) < 18
        except (TypeError, ValueError):
            young = False
        if young or _MINOR_RE.search(c.get("gorsel_en", "")):
            names.append(c.get("ad", ""))
    return [n for n in names if n]


def check_visual_prompt(text, card=None):
    """Sorun varsa açıklama döndürür, yoksa None."""
    m = _MINOR_RE.search(text) or _AGE_RE.search(text)
    if m:
        return f"Bu sahne reşit olmayan birini ima ediyor (\"{m.group(0)}\"), görsel/video üretilmez."
    for name in minor_characters(card or {}):
        if re.search(rf"\b{re.escape(name)}\b", text, re.I):
            return f"\"{name}\" 18 yaşından küçük bir karakter, içinde olduğu sahnelerin görseli/videosu üretilmez."
    return None


def _age_phrase(age, pronoun):
    decade = (age // 10) * 10
    part = "early" if age % 10 <= 3 else "mid" if age % 10 <= 6 else "late"
    return f"in {pronoun} {part} {decade}s"


_TEEN_AGE_RE = re.compile(r"\bin (his|her|their) (early |mid-?|late )?teens\b|\b(late |older )?teen(age|ager)?s?\b", re.I)


def mark_adults(card):
    """Yetişkin karakterlerin görsel tarifinin başına 'adult' ekler. Yaşı 18 ve üstü olduğu halde tarifi
    'teens' diyen karakterlerin tarifini yaşına uygun yetişkin ifadesiyle düzeltir (en az 20'ler)."""
    for c in card.get("karakterler", []):
        g = c.get("gorsel_en", "")
        try:
            age = int(c.get("yas"))
        except (TypeError, ValueError):
            age = None
        if age is not None and age >= 18 and _TEEN_AGE_RE.search(g):
            pron = "her" if re.search(r"\b(woman|female|girl|her)\b", g, re.I) else "his"
            g = _TEEN_AGE_RE.sub(_age_phrase(max(age, 20), pron), g)
            c["gorsel_en"] = g
    young = set(minor_characters(card))
    for c in card.get("karakterler", []):
        g = c.get("gorsel_en", "")
        if c.get("ad") not in young and "adult" not in g.lower():
            c["gorsel_en"] = f"adult, {g}" if g else "adult"
    return card
