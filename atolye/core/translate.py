"""Türkçe komutları Ollama ile İngilizceye çevirir; komut zaten İngilizceyse olduğu gibi kalır."""
import re

import requests

SCENE_SYSTEM = (
    "You turn the author's Turkish description of a photo of a fictional adult woman (the image model already "
    "knows her face) into an English prompt fragment for a text-to-image model. Write a "
    "comma-separated list of visual details: clothing or nudity, pose and what her hands are doing, facial "
    "expression, place, time of day, lighting, camera angle and framing. Do NOT describe her face, hair, eye color "
    "or body type. Nudity is allowed; leave out sexual acts. She is an adult. Output ONLY the English fragment."
)

VIDEO_SYSTEM = (
    "You turn the author's Turkish description into an English prompt for an image-to-video model. The start "
    "image already shows the woman, her look and the place, so describe what HAPPENS in the short clip: body "
    "movement and gestures, facial expression, camera movement, light. At most two actions for a 5 second clip. "
    "Nudity is allowed; leave out sexual acts. She is a fictional adult. Present tense, 2-3 sentences. "
    "End with: same face, consistent appearance. Output ONLY the English prompt."
)

THINK_RE = re.compile(r"<think>.*?</think>", re.S)
_TR_LETTERS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
_TR_WORDS = re.compile(
    r"\b(ve|bir|bu|ile|için|gibi|çok|daha|olsun|olan|kadın|yatak|ayna|oda|gece|sabah|yavaşça|kamera|"
    r"bakıyor|oturuyor|uzanıyor|gülümsüyor|saçını|eliyle|sonra)\b", re.I)


def is_turkish(text):
    return bool(_TR_LETTERS.search(text) or _TR_WORDS.search(text))


class Translator:
    def __init__(self, cfg):
        self.cfg = cfg

    @property
    def url(self):
        return self.cfg["ollama_url"].rstrip("/")

    def _ask(self, system, text):
        body = {"model": self.cfg["llm_model"], "stream": False, "think": False,
                "options": {"temperature": 0.3, "num_predict": 300},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}]}
        r = requests.post(f"{self.url}/api/chat", json=body, timeout=300)
        if r.status_code == 400 and "think" in r.text:
            body.pop("think")
            r = requests.post(f"{self.url}/api/chat", json=body, timeout=300)
        if not r.ok:
            raise RuntimeError(f"Çeviri yapılamadı (Ollama açık mı?): {r.text[:200]}")
        return re.sub(r"\s+", " ", THINK_RE.sub("", r.json()["message"]["content"])).strip().strip('"')

    def unload(self):
        """Çeviri modelini ekran kartından boşaltır (resim/video modeline yer açılsın)."""
        try:
            requests.post(f"{self.url}/api/generate", json={"model": self.cfg["llm_model"], "keep_alive": 0}, timeout=30)
        except requests.RequestException:
            pass

    def scene(self, text):
        """(ingilizce, cevrildi_mi)"""
        text = text.strip()
        return (self._ask(SCENE_SYSTEM, text), True) if is_turkish(text) else (text, False)

    def motion(self, text):
        text = text.strip()
        return (self._ask(VIDEO_SYSTEM, text), True) if is_turkish(text) else (text, False)
