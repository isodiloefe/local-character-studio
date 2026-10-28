"""Seçilen video motorlarını aynı resim ve komutla sırayla çalıştırır; her motor bitince belleği boşaltılır."""
import time
from pathlib import Path

from .framepack import FramePack
from .wan import Wan
from .zincir import chain_video

WANGP_MODELS = {"wan22": "i2v_2_2", "ltx": "ltx2_22B_distilled"}
KLIP_SN = 5  # WanGP tek seferde ~5 sn üretir; uzun video 5'er saniyelik kliplerin zinciri


class _SabitKlip:
    """chain_video'ya verilen sarmalayıcı: her klip aynı model ve 5 sn ile üretilir."""

    def __init__(self, wan, model):
        self.wan, self.model = wan, model

    def make_video(self, image, prompt, out_dir, status_cb=None):
        return self.wan.make_video(image, prompt, out_dir, status_cb=status_cb, model=self.model, seconds=KLIP_SN)


class Motorlar:
    def __init__(self, cfg, comfy):
        self.cfg = cfg
        self.comfy = comfy
        self.wan = Wan(cfg)
        self.fp = FramePack(cfg)

    def stop_all(self, shared=False):
        self.fp.stop()
        self.wan.stop(shared=shared)

    def _hazirla(self, motor):
        """Diğer motorların belleğini boşalt: 31 GB RAM ve 16 GB ekran kartı ikisine birden yetmez."""
        self.comfy.free()
        if motor in WANGP_MODELS:
            self.fp.stop()
        else:
            self.wan.stop(shared=True)

    def run(self, motor, image: Path, prompt, seconds, out_dir: Path, status_cb=None, stage_cb=None):
        """Videonun yolunu döner."""
        self._hazirla(motor)
        out_dir.mkdir(parents=True, exist_ok=True)
        hedef = out_dir / f"{Path(image).stem}_{motor}_{time.strftime('%H%M%S')}.mp4"
        if motor in ("fp_standart", "fp_f1"):
            return self.fp.make_video(motor, image, prompt, seconds, hedef, status_cb)
        klip = _SabitKlip(self.wan, WANGP_MODELS[motor])
        n = max(1, round(seconds / KLIP_SN))
        if n == 1:
            yol = klip.make_video(Path(image), prompt, out_dir, status_cb=status_cb)
        else:
            yol = chain_video(klip, Path(image), [prompt] * n, out_dir, stage_cb=stage_cb, status_cb=status_cb)
        return Path(yol).replace(hedef)
