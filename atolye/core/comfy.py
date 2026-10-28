"""ComfyUI: sahneyi MOSS-Image (+ gerçekçilik LoRA'sı) çizer, yüzü karakterin Z-Image LoRA'sı düzeltir.

Gerçekçi sahne modelleri karakterin yüzünü tam tutturamaz. Yüz bölgesi kırpılıp Z-Image + karakter LoRA'sıyla
düşük güçte (img2img, 0.45) yeniden çizilir ve yumuşak oval maskeyle yerine konur. Testlerde ArcFace benzerliği
~0.39'dan ~0.48'e çıktı (MOSS), ~0.43'ten ~0.51'e (SDXL).
"""
import io
import os
import random
import subprocess
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import requests
from PIL import Image

from .config import APP_DIR, LOG_DIR

NO_WINDOW = 0x08000000 if os.name == "nt" else 0
YUZ_MODELI = APP_DIR / "modeller" / "face_detection_yunet_2023mar.onnx"


def _moss(cfg, prompt, w, h, seed):
    """ComfyUI'nin resmi MOSS-Image şablonu (25 adım, cfg 2.5, er_sde, 22. katmanda skip-layer guidance)."""
    model = ["1", 0]
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": cfg["scene_model"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": cfg["scene_text_encoder"], "type": "moss_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": cfg["scene_vae"]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["2", 0]}},
        "7": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "atolye"}},
    }
    if cfg.get("scene_lora"):
        wf["11"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": model, "lora_name": cfg["scene_lora"], "strength_model": float(cfg["scene_lora_strength"])}}
        model = ["11", 0]
    wf["12"] = {"class_type": "SkipLayerGuidanceDiTSimple", "inputs": {
        "model": model, "double_layers": "", "single_layers": "22", "start_percent": 0.0, "end_percent": 0.5}}
    wf["8"] = {"class_type": "KSampler", "inputs": {
        "model": ["12", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
        "seed": seed, "steps": 25, "cfg": 2.5, "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0}}
    return wf


def _yuz(cfg, image_name, prompt, guc, seed):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "zimage_ae.safetensors"}},
        "12": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": cfg["character_lora"], "strength_model": 1.0}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["12", 0], "shift": 3}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "11": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "7": {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
            "seed": seed, "steps": 10, "cfg": 1.0, "sampler_name": "res_multistep", "scheduler": "simple", "denoise": guc}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "atolye_yuz"}},
    }


def buyuk_yuzler(rgb):
    """En büyük yüz ve ona yakın büyüklükteki diğerleri (ayna sahnesinde kişi + yansıması)."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    olcek = min(1.0, 1280 / max(h, w))
    kucuk = cv2.resize(bgr, (int(w * olcek), int(h * olcek))) if olcek < 1 else bgr
    dedektor = cv2.FaceDetectorYN.create(str(YUZ_MODELI), "", (kucuk.shape[1], kucuk.shape[0]), 0.5, 0.3, 50)
    _, yuzler = dedektor.detect(kucuk)
    if yuzler is None:
        return []
    en_buyuk = max(f[2] for f in yuzler)
    return [(f[:4] / olcek).astype(int) for f in yuzler if f[2] >= en_buyuk * 0.5]


class Comfy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client_id = uuid.uuid4().hex
        self.proc = None

    @property
    def url(self):
        return self.cfg["comfy_url"].rstrip("/")

    def is_up(self):
        try:
            return requests.get(f"{self.url}/system_stats", timeout=2).ok
        except requests.RequestException:
            return False

    def ensure(self, status_cb=None):
        if self.is_up():  # zaten açıksa onu kullan
            return
        d = Path(self.cfg["comfy_dir"])
        port = self.cfg["comfy_url"].rsplit(":", 1)[-1].strip("/")
        LOG_DIR.mkdir(exist_ok=True)
        log = open(LOG_DIR / "comfyui.log", "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [str(d / "env" / "Scripts" / "python.exe"), "main.py", "--port", port],
            cwd=d, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        start = time.time()
        while time.time() - start < 300:
            if self.proc.poll() is not None:
                raise RuntimeError(f"ComfyUI kapandı. Ayrıntı: {LOG_DIR / 'comfyui.log'}")
            if self.is_up():
                return
            if status_cb:
                status_cb(f"Resim motoru (ComfyUI) açılıyor... {int(time.time() - start)} sn")
            time.sleep(2)
        raise TimeoutError("ComfyUI 5 dakikada açılamadı.")

    def stop(self):
        """Sadece bu programın açtığı ComfyUI'yi kapatır."""
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.proc = None

    def free(self):
        try:
            requests.post(f"{self.url}/free", json={"unload_models": True, "free_memory": True}, timeout=30)
        except requests.RequestException:
            pass

    def _run(self, wf, status_cb=None, label="Resim çiziliyor"):
        r = requests.post(f"{self.url}/prompt", json={"prompt": wf, "client_id": self.client_id}, timeout=30)
        if not r.ok:
            raise RuntimeError(f"ComfyUI isteği reddetti: {r.text[:400]}")
        pid, start = r.json()["prompt_id"], time.time()
        while True:
            time.sleep(1)
            hist = requests.get(f"{self.url}/history/{pid}", timeout=10).json().get(pid)
            if hist:
                status = hist.get("status", {})
                if status.get("status_str") == "error":
                    msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                    raise RuntimeError("ComfyUI hatası: " + (msgs[0][1].get("exception_message", "") if msgs else ""))
                for node in hist.get("outputs", {}).values():
                    for img in node.get("images", []):
                        return Image.open(io.BytesIO(requests.get(f"{self.url}/view", params={
                            "filename": img["filename"], "subfolder": img.get("subfolder", ""),
                            "type": img.get("type", "output")}, timeout=60).content)).convert("RGB")
                if status.get("completed"):
                    raise RuntimeError("ComfyUI resim döndürmedi.")
            if status_cb:
                status_cb(f"{label}... {int(time.time() - start)} sn")
            if time.time() - start > 900:
                raise TimeoutError("İşlem 15 dakikayı aştı.")

    def generate(self, scene_en, out_path: Path, status_cb=None, seed=None):
        """Sahne komutundan resim üretir, yüzü düzeltir, kaydeder. Tohum numarasını döner."""
        self.ensure(status_cb)
        seed = seed if seed is not None else random.randint(1, 2**31)
        w, h = (int(x) for x in self.cfg["size"].split("x"))
        onek = (self.cfg.get("scene_lora_trigger", "") + ", ") if self.cfg.get("scene_lora") else ""
        prompt = f"{onek}photo of a {self.cfg['character_look']}, {scene_en}"
        # her model değişiminde belleği tamamen boşalt: ComfyUI 0.42 iki model arasında
        # yarım boşaltırken "list index out of range" verebiliyor
        self.free()
        resim = self._run(_moss(self.cfg, prompt, w, h, seed), status_cb)
        self.free()
        resim = self.fix_faces(resim, scene_en, status_cb)
        resim.save(out_path, "JPEG", quality=95)
        return seed

    def fix_faces(self, resim: Image.Image, scene_en="", status_cb=None):
        for kutu in buyuk_yuzler(np.asarray(resim)):
            resim = self._fix_face(resim, kutu, scene_en, status_cb)
        return resim

    def _fix_face(self, resim, kutu, scene_en, status_cb):
        rgb = np.asarray(resim)
        x, y, w, h = kutu
        H, W = rgb.shape[:2]
        # yüzün 2.2 katı kare: model saç ve çene çizgisini de görsün
        kenar = int(max(w, h) * 2.2)
        cx, cy = x + w // 2, y + h // 2 - int(h * 0.05)
        x1, y1 = max(0, cx - kenar // 2), max(0, cy - kenar // 2)
        x2, y2 = min(W, x1 + kenar), min(H, y1 + kenar)
        x1, y1 = max(0, x2 - kenar), max(0, y2 - kenar)
        kirpik = resim.crop((x1, y1, x2, y2))
        kw, kh = kirpik.size
        ifade = ", ".join(k for k in ("eyes closed", "smil", "side view", "looking at the camera")
                          if k in scene_en).replace("smil", "soft smile")
        prompt = (f"close-up photo of {self.cfg['trigger']}, natural skin texture, realistic, same lighting"
                  + (", " + ifade if ifade else ""))
        ad = f"atolye_{uuid.uuid4().hex[:10]}.png"
        giris = Path(self.cfg["comfy_dir"]) / "input" / ad
        kirpik.resize((1024, 1024), Image.LANCZOS).save(giris)
        try:
            yeni = self._run(_yuz(self.cfg, ad, prompt, float(self.cfg["face_strength"]), random.randint(1, 2**31)),
                             status_cb, "Yüz düzeltiliyor")
        finally:
            giris.unlink(missing_ok=True)
        yeni = np.asarray(yeni.resize((kw, kh), Image.LANCZOS), np.float32)
        eski = np.asarray(kirpik, np.float32)
        maske = np.zeros((kh, kw), np.float32)
        cv2.ellipse(maske, (x + w // 2 - x1, y + h // 2 - y1), (int(w * 0.75), int(h * 0.9)), 0, 0, 360, 1.0, -1)
        maske = cv2.GaussianBlur(maske, (0, 0), max(3, w * 0.12))[..., None]
        m = maske[..., 0] > 0.5
        for k in range(3):  # yeni yüz eski ten ve ışık tonuna otursun
            e, n = eski[..., k][m], yeni[..., k][m]
            yeni[..., k] = (yeni[..., k] - n.mean()) / (n.std() + 1e-6) * e.std() + e.mean()
        rgb = rgb.copy()
        rgb[y1:y2, x1:x2] = np.clip(yeni * maske + eski * (1 - maske), 0, 255).astype(np.uint8)
        return Image.fromarray(rgb)
