import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
IMAGES_DIR = APP_DIR / "resimler"
VIDEOS_DIR = APP_DIR / "videolar"
LOG_DIR = APP_DIR / "loglar"
CONFIG_FILE = APP_DIR / "ayarlar.json"
LIBRARY_FILE = APP_DIR / "kayit.json"

# Video motorları: (anahtar, görünen ad, açıklama)
ENGINES = [
    ("fp_standart", "FramePack Standart", "Yüzü en iyi korur, hareket sakin (~18 dk / 5 sn)"),
    ("fp_f1", "FramePack F1", "Daha hareketli, uzun videoda yüz kayabilir (~18 dk / 5 sn)"),
    ("wan22", "Wan 2.2", "Komutu ve kamera hareketini en iyi takip eder (~6 dk / 5 sn)"),
    ("ltx", "LTX-2.3", "En hızlısı, kalitesi daha düşük (~3 dk / 5 sn)"),
]

# Kendi kurulumunuza göre ayarlar.json içinde değiştirin (ayarlar.example.json'a bakın).
DEFAULTS = {
    # karakter: Z-Image üzerinde eğittiğiniz LoRA, tetik kelimesi ve kısa görünüş tarifi
    "character_lora": "my_character_zimage.safetensors",
    "trigger": "mychar woman",
    "character_look": "26 years old woman, long dark brown wavy hair, green eyes, light freckles",
    "face_strength": 0.45,
    # sahne modeli: MOSS-Image (Apache 2.0) + isteğe bağlı gerçekçilik LoRA'sı
    "scene_model": "moss_image_sft_bf16.safetensors",
    "scene_text_encoder": "qwen3.5_9b_int8_convrot.safetensors",
    "scene_vae": "flux2-vae.safetensors",
    "scene_lora": "cndamiph_Candid_Amateur_iPhone_MOSS_v1.safetensors",
    "scene_lora_trigger": "cndamiph",
    "scene_lora_strength": 0.9,
    "size": "896x1600",
    "count": 4,
    # yollar (Pinokio varsayılanları)
    "ollama_url": "http://127.0.0.1:11434",
    "llm_model": "gemma3:12b",
    "comfy_url": "http://127.0.0.1:8188",
    "comfy_dir": r"C:\pinokio\api\comfy.git\app",
    "framepack_dir": r"C:\pinokio\api\Frame-Pack\app",
    "framepack_port": 7881,
    "wan_dir": r"C:\pinokio\api\wan.git\app",
    "wan_port": 7870,
    "video_model": "i2v_2_2",
    "video_seconds": 5,
    "video_quality": "720p",
    "engines": ["fp_standart", "wan22"],
    # önceden üretilmiş resimlerin bulunduğu klasörler ("Hazır resim seç" için, boş olabilir)
    "ready_folders": [],
}


def load():
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_library():
    """[{image, prompt, prompt_en, seed, created, videos: {motor: {file, prompt_en, seconds, sure}}}]"""
    if LIBRARY_FILE.exists():
        try:
            return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def save_library(items):
    LIBRARY_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
