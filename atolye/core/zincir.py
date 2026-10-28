"""Uzun video: 5'er saniyelik klipleri art arda uretir ve birlestirir.

Her klip bir oncekinin son karesinden baslar. Son kare kullanilmadan once renkleri ilk resme gore
duzeltilir; boylece klipten klibe renk kaymasi (kararma, solma) birikmez. Sonunda klipler, ekleme
yerlerindeki tekrar eden kare atilarak tek videoda birlestirilir.
"""
import json
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image

NO_WINDOW = 0x08000000
# Her klip komutunun sonuna eklenir: model "slowly" gibi kelimelerle hareketi agir cekime cevirmesin
PACE = " Natural real-time speed, normal pace, no slow motion."


def _run(args):
    r = subprocess.run(args, capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode:
        raise RuntimeError(f"ffmpeg hatası: {r.stderr[-400:]}")
    return r.stdout


def last_frame(video, out_png):
    """Videonun son karesini PNG olarak kaydeder."""
    _run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.3", "-i", str(video), "-update", "1", "-q:v", "1", str(out_png)])
    return out_png


def match_colors(img_path, ref_path):
    """img'nin renk dagilimini (kanal basina ortalama ve sapma) ref'e yaklastirir."""
    img = np.asarray(Image.open(img_path).convert("RGB"), dtype=np.float32)
    ref = np.asarray(Image.open(ref_path).convert("RGB"), dtype=np.float32)
    out = (img - img.mean((0, 1))) / (img.std((0, 1)) + 1e-6) * ref.std((0, 1)) + ref.mean((0, 1))
    # tam esitleme sahne degisince yapay durur; yariya kadar yaklastirmak kaymayi durdurmaya yeter
    out = 0.5 * out + 0.5 * img
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(img_path)


def _has_audio(video):
    out = _run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(video)])
    return bool(json.loads(out).get("streams"))


def merge(clips, out_path, fps=24, keep_audio=False):
    """Klipleri birlestirir; 2. klipten itibaren ilk kareyi (oncekinin son karesinin tekrari) atar.
    Modelin her klip icin urettigi ses/muzik klipten klibe degistigi icin varsayilan olarak atilir;
    muzik paylasirken platformda tek parca eklenir."""
    audio = keep_audio and all(_has_audio(c) for c in clips)
    # WanGP sonraki klibin boyutunu birkaç piksel farklı yuvarlayabiliyor (800x1168 / 800x1152);
    # concat aynı boyut istediği için hepsi ilk klibin boyutuna getirilir
    w, h = _run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                 "-of", "csv=p=0", str(clips[0])]).strip().split(",")[:2]
    args, parts = ["ffmpeg", "-v", "error", "-y"], []
    for c in clips:
        args += ["-i", str(c)]
    for i in range(len(clips)):
        skip = "trim=start_frame=1," if i else ""
        parts.append(f"[{i}:v]{skip}scale={w}:{h}:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[v{i}]")
        if audio:
            askip = f"atrim=start={1 / fps:.4f}," if i else ""
            parts.append(f"[{i}:a]{askip}asetpts=PTS-STARTPTS[a{i}]")
    inputs = "".join(f"[v{i}]" + (f"[a{i}]" if audio else "") for i in range(len(clips)))
    parts.append(f"{inputs}concat=n={len(clips)}:v=1:a={1 if audio else 0}[v]" + ("[a]" if audio else ""))
    args += ["-filter_complex", ";".join(parts), "-map", "[v]"] + (["-map", "[a]", "-c:a", "aac", "-b:a", "192k"] if audio else [])
    args += ["-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    _run(args)
    return out_path


def chain_video(wan, image, prompts, out_dir, stage_cb=None, status_cb=None):
    """prompts: her biri ~5 sn'lik bir klibin komutu. Birlesmis videonun yolunu dondurur.
    Klipler <out_dir>/parcalar_<zaman>/ klasorunde saklanir (tek tek de izlenebilir)."""
    work = Path(out_dir) / f"parcalar_{time.strftime('%Y%m%d_%H%M%S')}"
    work.mkdir(parents=True, exist_ok=True)
    start = work / f"baslangic{Path(image).suffix.lower()}"
    shutil.copy2(image, start)
    clips, current = [], start
    for i, prompt in enumerate(prompts, 1):
        if stage_cb:
            stage_cb(f"Klip {i}/{len(prompts)} hazırlanıyor (her biri ~5 sn)...")
        clip = wan.make_video(current, prompt.rstrip() + PACE, work, status_cb=status_cb)
        clip = clip.rename(work / f"klip_{i:02d}.mp4")
        clips.append(clip)
        if i < len(prompts):
            current = last_frame(clip, work / f"kare_{i:02d}.png")
            match_colors(current, start)
    if stage_cb:
        stage_cb("Klipler birleştiriliyor...")
    return merge(clips, Path(out_dir) / f"uzun_{time.strftime('%Y%m%d_%H%M%S')}.mp4")
