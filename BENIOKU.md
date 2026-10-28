# Yerel Karakter Stüdyosu — Kullanıcı Rehberi

Kendi hayali karakterinizle **gerçekçi fotoğraflar** ve **kısa videolar** üretmek için tamamen yerel (internetsiz) çalışan bir iş akışı. Tek bir RTX 16 GB ekran kartında test edildi.

Üç parçadan oluşur:

1. **Karakter fotoğrafı + yüz düzeltme** — sahneyi gerçekçi bir model çizer, yüzü sizin karakter LoRA'nız düzeltir.
2. **Video Atölyesi** — aynı resimden birden çok video motoruyla (FramePack, Wan 2.2, LTX) video yapıp sonuçları yan yana karşılaştırır.
3. **Shorts hattı** — 5 saniyelik dikey video + ekrana iki parçalı yazı → YouTube Shorts / Reels'e hazır 1080x1920.

> Bu rehberde örnek karakter yoktur; kendi karakter LoRA'nızı eğitip kullanırsınız.

---

## 1. Gereksinimler

| | Önerilen |
|---|---|
| Ekran kartı | NVIDIA, 16 GB VRAM (RTX 4080/5080 sınıfı) |
| Bellek | 32 GB RAM |
| Disk | ~150 GB boş alan (modeller) |
| Yazılım | Windows 10/11, Python 3.12+, [Pinokio](https://pinokio.co) (ComfyUI, WanGP, FramePack, ai-toolkit kurulumu için), ffmpeg |

## 2. Kurulum

Pinokio üzerinden tek tıkla kurun:

- **ComfyUI** (0.42 veya üstü — MOSS-Image desteği için)
- **WanGP** (Wan 2.2 ve LTX-2.3 video motorları)
- **FramePack** (pinokiofactory sürümü; Standart ve F1)
- **ai-toolkit** (karakter LoRA'sı eğitmek için)

### Modeller

| Model | Ne için | Nereye |
|---|---|---|
| [Z-Image Turbo](https://huggingface.co/Comfy-Org) (`z_image_turbo_bf16`) + `qwen_3_4b` + `zimage_ae` | Karakter LoRA'sı ve yüz düzeltme | ComfyUI `models/diffusion_models`, `text_encoders`, `vae` |
| [MOSS-Image SFT](https://huggingface.co/Comfy-Org/MOSS-Image) (`moss_image_sft_bf16`) + `qwen3.5_9b_int8_convrot` + `flux2-vae` | En gerçekçi sahne üretimi (Apache 2.0) | aynı klasörler |
| [cndamiph — Candid Amateur iPhone](https://civitai.com/models/3012015) (MOSS LoRA) | "Telefonla çekilmiş" hissi | `models/loras` |
| Wan 2.2 I2V 14B + Lightning 4 adım LoRA'ları | Videoda en iyi komut takibi | WanGP kendisi indirir |
| YuNet yüz bulucu (`face_detection_yunet_2023mar.onnx`) | Yüz düzeltmede yüzü bulmak | `modeller/` |

Her modelin kendi lisansını kontrol edin; ticari kullanım için Apache 2.0 / MIT lisanslıları tercih edin.

### Program

```
pip install -r requirements.txt
atolye\Baslat.bat
```

İlk açılışta `atolye/ayarlar.example.json`, `atolye/ayarlar.json` olarak kopyalanır. En önemli alanlar:

| Alan | Açıklama |
|---|---|
| `character_lora` | Karakterinizin Z-Image LoRA dosyası (ComfyUI `models/loras` içinde) |
| `trigger` | LoRA'nın tetik kelimesi, ör. `mychar woman` |
| `character_look` | Karakterin kısa görünüş tarifi (saç, göz, yaş) — sahne modeli buna göre çizer |
| `scene_lora` | Gerçekçilik LoRA'sı (boş bırakılabilir) |
| `comfy_dir`, `wan_dir`, `framepack_dir` | Pinokio kurulum klasörleri |
| `ready_folders` | "Hazır resim seç" için resim klasörleri |
| `llm_model` | Türkçe komutları çeviren Ollama modeli |

## 3. Karakter LoRA'sı eğitmek (ai-toolkit)

1. Karakterinizin **30–60** resmini toplayın: farklı açılar, ifadeler, kıyafetler, yakın çekim ve tam boy. Yüz her resimde aynı kişi olmalı.
2. Her resmin yanına aynı adlı bir `.txt` açıklama koyun. Tetikleyici kelimeyle başlayın: `photo of <tetikleyici> woman, close-up portrait, smiling, ...`
3. ai-toolkit'te mimariyi seçin:
   - **Z-Image Turbo** (`zimage:turbo`) — yüz tutarlılığı en yüksek; ~2,5–3 saat
   - **MOSS-Image** (`moss_image`, `quantize: convrot8`, `low_vram: true`) — en gerçekçi; ~1,5–2 saat
4. 2.500–3.600 adım, rank 32, öğrenme oranı 1e-4 iyi bir başlangıç.
5. Kontrol: Yüz benzerliğini ArcFace ile ölçün (insightface). 0,6 üstü iyi sayılır.

## 4. Yüz düzeltme yöntemi (en önemli ipucu)

Gerçekçi sahne modelleri (MOSS, SDXL gerçekçilik modelleri) karakterin yüzünü tam tutturamaz. Çözüm:

1. Sahneyi gerçekçi modelle üretin (ör. MOSS + cndamiph).
2. Resimdeki **bütün büyük yüzleri** bulun (ayna sahnesinde kişi + yansıması dahil).
3. Her yüzü 2,2 katı bir kare alanla kırpın, 1024x1024'e büyütün.
4. Z-Image + karakter LoRA'nızla **img2img, güç 0,45** ile yeniden çizin.
5. Oval, yumuşak kenarlı bir maskeyle ve renk/ışık eşlemesiyle eski yerine yapıştırın.

Ölçtüğümüz sonuç: benzerlik ~0,43 → ~0,51 (SDXL), ~0,39 → ~0,48 (MOSS). 0,35 güç zayıf, 0,55 aşırı kalıyor.

## 5. Video Atölyesi

Aynı resimden seçtiğiniz motorlarla sırayla video yapar, her motor bitince belleği boşaltır.

| Motor | Güçlü yanı | 5 sn süresi (16 GB) |
|---|---|---|
| **Wan 2.2** | Komutu ve kamera hareketini en iyi takip eder, 800x1168 | ~7–8 dk |
| **FramePack Standart** | Yüzü en sağlam korur, hareket sakin, 512x768 | ~18 dk |
| **FramePack F1** | Daha hareketli; uzun videoda yüz sona doğru kayabilir | ~18 dk |
| **LTX-2.3** | En hızlı; kalite daha düşük | ~3 dk |

Uzun video (10–15 sn) 5'er saniyelik kliplerin zinciridir: her klip öncekinin son karesinden başlar, renkler ilk resme göre düzeltilir, klipler aynı boyuta getirilip birleştirilir.

**Komut ipuçları**
- 5 saniyeye en fazla **iki** hareket yazın.
- Pozisyonu sabitleyin ("she stays lying down"), hareketin yönünü söyleyin ("arms above her head").
- Sonuna ekleyin: `same face, consistent appearance, steady camera`.
- Gözleri kapatan hareketlerden (gözlük takmak vb.) kaçının; model kimliği kaybedebilir — tersini yapın (gözlük takılı başlasın, sonunda çıkarsın).

## 6. Shorts hattı

```
cd araclar
python shorts_uret.py ornek.json --aday 3                      # 3 aday resim üret, en doğalını seç
python shorts_uret.py ornek.json --resim cikti\kafe\aday_2.jpg  # seçilenden videoyu yap
```

`araclar/ornek.json`:

```json
{
  "ad": "kafe",
  "sahne_en": "sitting at an outdoor cafe, knit sweater, holding a coffee cup, serious face",
  "hareket_en": "She looks at the camera seriously, then breaks into a warm laugh and tucks her hair behind her ear.",
  "yazi1": "Herkes çok ciddi görünürmüş…",
  "yazi2": "ta ki gülene kadar",
  "baslik": "Sence de öyle değil mi? 👀"
}
```

Çıktı: 1080x1920, hafif gren/doygunluk filtresi, ekranın ortasında iki parçalı yazı. Müzik platformun kütüphanesinden eklenir (telif sorunu olmaz).

**Viral Shorts formatı (analizden):** 6–9 saniye, tek çekim, telefonla çekilmiş his, gerçek mekân, iki parçalı yazı (kurgu → punchline), başlık her zaman izleyiciye soru.

**Doğallık için:** "amateur photo shot on iPhone, slightly off-center, harsh midday sun, people in the background, everyday clutter" gibi ifadeler; kusursuz poz ve stüdyo ışığından kaçının.

## 7. Sorun giderme

| Sorun | Çözüm |
|---|---|
| ComfyUI'de "list index out of range" (model değişiminde) | Her model değişiminden önce `/free` ile belleği tamamen boşaltın |
| Uzun videoda klipler birleşmiyor | Klipler birkaç piksel farklı boyutta olabilir; birleştirmeden önce ilk klibin boyutuna ölçekleyin |
| ffmpeg'de `ass`/`drawtext` yok | Yazıyı Python (PIL) ile saydam PNG olarak çizip `overlay` ile bindirin |
| Video iki kez üretildi / süre yanlış | Düğmeyi tıklar tıklamaz kilitleyin; klip süresini paylaşılan ayardan değil doğrudan motora verin |
| Arka plan kaldırmada beyaz kıyafet yarı saydam | Hızlı model kararsızsa (maskenin %8+ yarı saydam) BiRefNet'e geçin |

## 8. Sorumlu kullanım

- Karakterler **hayali yetişkinler** olmalı; reşit olmayan izlenimi veren her şey engellenir.
- Gerçek kişilerin fotoğraflarını **yalnızca rızalarıyla** ve çıplaklık/cinsel içerik olmadan kullanın.
- Gerçekçi yapay zekâ insanı içeren videoları YouTube/Instagram'da **"yapay zekâ ile oluşturuldu / sentetik içerik"** olarak etiketleyin.
- Başka içerik üreticilerinin videolarını yalnızca format incelemesi için kullanın; yeniden yüklemeyin.
