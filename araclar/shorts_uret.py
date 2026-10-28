"""Kısa video (Shorts/Reels): karakter resmi → Wan 2.2 5 sn video → iki parçalı yazı → 1080x1920.

Resim, Video Atölyesi'nin yöntemiyle üretilir (MOSS-Image sahnesi + karakter LoRA'sıyla yüz düzeltme).
Ayarlar ../atolye/ayarlar.json'dan okunur. Müzik platformun kendi kütüphanesinden eklenir.

Kullanım:
  python shorts_uret.py ornek.json --aday 3            # sadece 3 aday resim üret, gözle en doğalını seç
  python shorts_uret.py ornek.json --resim aday_2.jpg  # seçilen resimden videoyu yap
  python shorts_uret.py ornek.json                     # tek resim üret ve hemen videoya geç
"""
import json
import subprocess
import sys
import time
from pathlib import Path

KLASOR = Path(__file__).resolve().parent
sys.path.insert(0, str(KLASOR.parent / "atolye"))
from core import config  # noqa: E402
from core.comfy import Comfy  # noqa: E402
from core.gpu_kilit import gpu_lock  # noqa: E402
from core.motorlar import Motorlar  # noqa: E402

FONT = r"C:\Windows\Fonts\arialbd.ttf"
log = lambda s: print(time.strftime("%H:%M:%S"), s, flush=True)


def yazi_png(metin, yol, y_merkez=1240, punto=64):
    """1080x1920 saydam PNG: beyaz kalın yazı, siyah kenar; satıra sığmazsa böler.
    (Bazı ffmpeg derlemelerinde libass/drawtext yok; yazı resim olarak bindirilir.)"""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(FONT, punto)
    tuval = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    ciz = ImageDraw.Draw(tuval)
    satirlar, satir = [], ""
    for kelime in metin.split():
        deneme = (satir + " " + kelime).strip()
        if ciz.textlength(deneme, font=font) > 940 and satir:
            satirlar.append(satir)
            satir = kelime
        else:
            satir = deneme
    satirlar.append(satir)
    yukseklik = punto + 14
    y = y_merkez - yukseklik * len(satirlar) // 2
    for s in satirlar:
        ciz.text((540, y), s, font=font, anchor="mt", fill="white", stroke_width=5, stroke_fill="black")
        y += yukseklik
    tuval.save(yol)


def yazi_ekle(video, cikti, yazi1, yazi2, sure):
    """Önce yazi1, ortadan sonra yazi2; hafif gren/doygunluk filtresiyle 1080x1920'ye çevirir."""
    orta = round(sure * 0.48, 2)
    p1, p2 = cikti.with_name("yazi1.png"), cikti.with_name("yazi2.png")
    yazi_png(yazi1, p1)
    yazi_png(yazi2, p2)
    filtre = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,"
              "eq=saturation=0.92:contrast=0.96:gamma=1.02,noise=alls=7:allf=t+u,unsharp=3:3:0.25[v];"
              f"[v][1:v]overlay=0:0:enable='lt(t,{orta})'[a];"
              f"[a][2:v]overlay=0:0:enable='gte(t,{orta})'[out]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-i", str(p1), "-i", str(p2),
                    "-filter_complex", filtre, "-map", "[out]",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", "-an", str(cikti)], check=True)


def main():
    s = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    aday = int(sys.argv[sys.argv.index("--aday") + 1]) if "--aday" in sys.argv else 0
    hazir = Path(sys.argv[sys.argv.index("--resim") + 1]) if "--resim" in sys.argv else None
    cfg = config.load()
    cfg["size"] = "896x1600"
    comfy = Comfy(cfg)
    m = Motorlar(cfg, comfy)
    hedef = KLASOR / "cikti" / s["ad"]
    hedef.mkdir(parents=True, exist_ok=True)
    log("ekran kartı sırası bekleniyor...")
    with gpu_lock("Shorts", wait_cb=None):
        try:
            if hazir:
                resim_yol = hazir
            else:
                for i in range(1, max(aday, 1) + 1):
                    resim_yol = hedef / (f"aday_{i}.jpg" if aday else "resim.jpg")
                    log(f"resim {i} üretiliyor")
                    comfy.generate(s["sahne_en"], resim_yol)
                comfy.stop()
                if aday:
                    log(f"TAMAM: {aday} aday resim → {hedef}")
                    return
            comfy.stop()
            log("video üretiliyor (Wan 2.2, 5 sn)")
            video = m.run("wan22", resim_yol, s["hareket_en"], 5, hedef)
            sure = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                         str(video)], capture_output=True, text=True).stdout)
            cikti = hedef / f"{s['ad']}_short.mp4"
            yazi_ekle(video, cikti, s["yazi1"], s["yazi2"], sure)
            (hedef / "baslik.txt").write_text(s.get("baslik", ""), encoding="utf-8")
            log(f"TAMAM: {cikti}")
        finally:
            m.stop_all(shared=True)
            comfy.stop()


if __name__ == "__main__":
    main()
