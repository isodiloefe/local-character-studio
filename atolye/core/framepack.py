"""FramePack (lllyasviel) — Pinokio'nun kurduğu kopyayı kendi portunda açar, Gradio API ile video üretir, kapatır.

Standart (demo_gradio.py): videoyu sondan başa üretir, yüzü en iyi korur, hareket sakin.
F1 (demo_gradio_f1.py): baştan sona üretir, daha hareketli; uzun videoda yüz sona doğru kayabilir.
FramePack ~22 GB sistem belleği kullandığı için başka video motoruyla aynı anda çalıştırılmaz.
"""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests

from .config import LOG_DIR

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SCRIPTS = {"fp_standart": "demo_gradio.py", "fp_f1": "demo_gradio_f1.py"}
PINOKIO_PORTS = range(42000, 42010)


def _up(url):
    try:
        return requests.get(url, timeout=2).ok
    except requests.RequestException:
        return False


def pinokio_framepack_open():
    """Pinokio'dan elle açılmış bir FramePack var mı (ikisi birden belleğe sığmaz)."""
    for p in PINOKIO_PORTS:
        try:
            r = requests.get(f"http://127.0.0.1:{p}/gradio_api/info", timeout=1)
            if r.ok and "/process" in r.text and "total_second_length" in r.text:
                return p
        except requests.RequestException:
            continue
    return None


class FramePack:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.mode = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.cfg['framepack_port']}/"

    def ensure(self, mode, status_cb=None):
        if self.proc and self.proc.poll() is None and self.mode == mode and _up(self.url):
            return
        self.stop()
        acik = pinokio_framepack_open()
        if acik:
            raise RuntimeError(f"Pinokio'da FramePack açık (port {acik}). İkisi birden belleğe sığmaz; "
                               "Pinokio'daki FramePack'i durdurup tekrar deneyin.")
        d = Path(self.cfg["framepack_dir"])
        LOG_DIR.mkdir(exist_ok=True)
        log = open(LOG_DIR / f"framepack_{mode}.log", "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [str(d / "env" / "Scripts" / "python.exe"), SCRIPTS[mode],
             "--server", "127.0.0.1", "--port", str(self.cfg["framepack_port"])],
            cwd=d, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        self.mode = mode
        start = time.time()
        while time.time() - start < 900:
            if self.proc.poll() is not None:
                raise RuntimeError(f"FramePack kapandı. Ayrıntı: {LOG_DIR / f'framepack_{mode}.log'}")
            if _up(self.url):
                return
            if status_cb:
                status_cb(f"FramePack açılıyor (modeller belleğe yükleniyor)... {int(time.time() - start)} sn")
            time.sleep(3)
        raise TimeoutError("FramePack 15 dakikada açılamadı.")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                           capture_output=True, creationflags=NO_WINDOW)
        self.proc, self.mode = None, None

    def make_video(self, mode, image, prompt, seconds, out_path: Path, status_cb=None):
        from gradio_client import Client, handle_file

        self.ensure(mode, status_cb)
        client = Client(self.url, verbose=False)
        # sıra: resim, komut, negatif, tohum, süre, pencere, adım, cfg, distilled cfg, rescale,
        #       GPU'da ayrılan bellek, TeaCache (kapalı: yüz kalitesi için), mp4 sıkıştırma
        job = client.submit(handle_file(str(image)), prompt, "", 31337, float(seconds), 9, 25, 1.0, 10.0, 0.0,
                            6, False, 16, api_name="/process")
        start = time.time()
        while not job.done():
            time.sleep(5)
            if status_cb:
                desc = ""
                outs = job.outputs()
                if outs and len(outs[-1]) > 3 and isinstance(outs[-1][3], str):
                    desc = re.sub(r"<[^>]+>", "", outs[-1][3]).strip()[:120]
                status_cb(f"{'FramePack Standart' if mode == 'fp_standart' else 'FramePack F1'}: "
                          f"{desc or 'hazırlanıyor'} ({int(time.time() - start)} sn)")
        outs = job.outputs()
        video = outs[-1][0] if outs else None
        path = video.get("video") if isinstance(video, dict) else video
        if not path or not Path(path).exists():
            raise RuntimeError("FramePack video döndürmedi.")
        shutil.copy2(path, out_path)
        return out_path
