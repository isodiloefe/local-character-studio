"""WanGP (LTX-2.3) video sunucusunu başlatır ve görselden video üretir.
Video üretimi WanGP ile yapılır: https://github.com/deepbeepmeep/Wan2GP
"""
import os
import subprocess
import time
from pathlib import Path

import requests
from PIL import Image

from .config import APP_DIR, LOG_DIR

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SIZES = {
    "480p": {"landscape": "832x480", "portrait": "480x832", "square": "640x640"},
    "720p": {"landscape": "1280x720", "portrait": "720x1280", "square": "960x960"},
}


WAN22_LIGHTNING = "https://huggingface.co/DeepBeepMeep/Wan2.2/resolve/main/loras_accelerators/"


def model_extra(model, seconds):
    """Modele ozel WanGP ayarlari. Wan 2.2: 16 fps, resmi Lightning hizlandiricisiyla 4 adim
    (WanGP profili 'Lightning i2v v2025-10-14 2 Phases - 4 Steps')."""
    if model.startswith("i2v_2_2"):
        return {
            "force_fps": 16, "video_length": seconds * 16 + 1, "num_inference_steps": 4,
            "guidance_scale": 1, "guidance2_scale": 1, "switch_threshold": 876, "model_switch_phase": 1,
            "guidance_phases": 2, "flow_shift": 5, "sample_solver": "euler", "loras_multipliers": "1;0 0;1",
            "activated_loras": [
                WAN22_LIGHTNING + "Wan2.2_I2V_A14B_HIGH_lightx2v_MoE_distill_lora_rank_64_bf16.safetensors",
                WAN22_LIGHTNING + "Wan2.2_I2V_A14B_LOW_4steps_lora_rank64_Seko_V1_forKJ.safetensors"],
        }
    return {}


def free_comfy(url="http://127.0.0.1:8188"):
    """Başka bir program ComfyUI açtıysa resim modelini ekran kartından boşaltır."""
    try:
        requests.post(f"{url}/free", json={"unload_models": True, "free_memory": True}, timeout=10)
    except requests.RequestException:
        pass


def resolution_for(image_path, quality):
    """Videonun en-boy oranını başlangıç resmine göre seçer."""
    with Image.open(image_path) as im:
        w, h = im.size
    shape = "landscape" if w > h * 1.15 else "portrait" if h > w * 1.15 else "square"
    return SIZES.get(quality, SIZES["720p"])[shape]


class Wan:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        LOG_DIR.mkdir(exist_ok=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.cfg['wan_port']}"

    def _ready(self):
        try:
            h = requests.get(f"{self.url}/health", timeout=2).json()
        except requests.RequestException:
            return False
        if h.get("error"):
            raise RuntimeError("WanGP başlatılamadı:\n" + h["error"][-1500:])
        return h.get("ready")

    def ensure(self, status_cb=None):
        # Başka bir program aynı portta bir video motoru açtıysa onu kullan, ikinci kopyayı açma
        if self._ready():
            return
        free_comfy()
        d = Path(self.cfg["wan_dir"])
        log = open(LOG_DIR / "wangp.log", "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [str(d / "env" / "Scripts" / "python.exe"), str(APP_DIR / "wan_worker.py"), str(d), str(self.cfg["wan_port"])],
            cwd=d, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        start = time.time()
        while time.time() - start < 600:
            if self.proc.poll() is not None:
                raise RuntimeError(f"WanGP kapandı. Ayrıntı: {LOG_DIR / 'wangp.log'}")
            if self._ready():
                return
            if status_cb:
                status_cb(f"Video motoru (WanGP) açılıyor... {int(time.time() - start)} sn")
            time.sleep(2)
        raise TimeoutError("WanGP 10 dakikada açılamadı.")

    def stop(self, shared=True):
        """Video motorunu kapatır. shared=False: sadece bu programın açtığını kapatır
        (program kapanırken; başka bir program o an motoru kullanıyor olabilir)."""
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=30)
        elif shared:
            try:
                requests.post(f"{self.url}/shutdown", timeout=3)
            except requests.RequestException:
                pass
        self.proc = None

    def make_video(self, image_path, prompt, out_dir, status_cb=None, segments=None, model=None, seconds=None):
        """segments: uzun video icin bolum komutlari (her biri ~5 sn, kaldigi yerden devam eder).
        model/seconds verilirse ortak ayarlar yerine bunlar kullanilir (baska bir islem ayari
        degistirse bile bu isin klip suresi degismesin)."""
        free_comfy()
        self.ensure(status_cb)
        model = model or self.cfg["video_model"]
        seconds = int(seconds or self.cfg["video_seconds"])
        r = requests.post(f"{self.url}/video", json={
            "image": str(image_path), "prompt": prompt, "model": model,
            "resolution": resolution_for(image_path, self.cfg["video_quality"]),
            "seconds": seconds, "output_dir": str(out_dir),
            "segments": segments or [], "extra": model_extra(model, seconds)}, timeout=30)
        r.raise_for_status()
        job_id = r.json()["job_id"]
        start = time.time()
        while True:
            time.sleep(2)
            j = requests.get(f"{self.url}/job/{job_id}", timeout=10).json()
            if j["status"] == "done":
                return Path(j["file"])
            if j["status"] == "error":
                raise RuntimeError(j.get("error", "Video üretilemedi"))
            if status_cb:
                status_cb(f"Video üretiliyor... {j.get('progress', '')} ({int(time.time() - start)} sn)")
