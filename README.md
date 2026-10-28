# Local Character Studio — User Guide

A fully local (offline) workflow for producing **realistic photos** and **short videos** of your own fictional character. Tested on a single 16 GB RTX GPU.

It has three parts:

1. **Character photo + face fix** — a realism model draws the scene, your character LoRA fixes the face.
2. **Video Workshop** — turns the same image into videos with several engines (FramePack, Wan 2.2, LTX) one after another, so you can compare them side by side.
3. **Shorts pipeline** — a 5-second vertical clip + two-part on-screen text → ready-to-post 1080x1920 for YouTube Shorts / Reels.

> No sample character is included; you train and use your own character LoRA.

---

## 1. Requirements

| | Recommended |
|---|---|
| GPU | NVIDIA, 16 GB VRAM (RTX 4080/5080 class) |
| RAM | 32 GB |
| Disk | ~150 GB free (models) |
| Software | Windows 10/11, Python 3.12+, [Pinokio](https://pinokio.co) (to install ComfyUI, WanGP, FramePack, ai-toolkit), ffmpeg |

## 2. Installation

Install with one click from Pinokio:

- **ComfyUI** (0.42 or newer — needed for MOSS-Image)
- **WanGP** (Wan 2.2 and LTX-2.3 video engines)
- **FramePack** (pinokiofactory build; Standard and F1)
- **ai-toolkit** (to train a character LoRA)

### Models

| Model | Used for | Folder |
|---|---|---|
| [Z-Image Turbo](https://huggingface.co/Comfy-Org) (`z_image_turbo_bf16`) + `qwen_3_4b` + `zimage_ae` | Character LoRA and face fix | ComfyUI `models/diffusion_models`, `text_encoders`, `vae` |
| [MOSS-Image SFT](https://huggingface.co/Comfy-Org/MOSS-Image) (`moss_image_sft_bf16`) + `qwen3.5_9b_int8_convrot` + `flux2-vae` | Most realistic scenes (Apache 2.0) | same folders |
| [cndamiph — Candid Amateur iPhone](https://civitai.com/models/3012015) (MOSS LoRA) | "Shot on a phone" look | `models/loras` |
| Wan 2.2 I2V 14B + Lightning 4-step LoRAs | Best prompt adherence in video | downloaded by WanGP |
| YuNet face detector (`face_detection_yunet_2023mar.onnx`) | Finding faces for the face fix | `modeller/` |

Check each model's license; prefer Apache 2.0 / MIT models for commercial use.

### The app

```
pip install -r requirements.txt
atolye\Baslat.bat
```

On first start `atolye/ayarlar.example.json` is copied to `atolye/ayarlar.json`. Key fields:

| Field | Meaning |
|---|---|
| `character_lora` | Your character's Z-Image LoRA file (in ComfyUI `models/loras`) |
| `trigger` | The LoRA trigger word, e.g. `mychar woman` |
| `character_look` | Short description of the character (hair, eyes, age) — the scene model draws from this |
| `scene_lora` | Realism LoRA (may be left empty) |
| `comfy_dir`, `wan_dir`, `framepack_dir` | Pinokio install folders |
| `ready_folders` | Image folders for "Hazır resim seç" (pick a ready image) |
| `llm_model` | Ollama model that translates Turkish prompts |

The UI is in Turkish; English prompts are passed through untranslated.

## 3. Training a character LoRA (ai-toolkit)

1. Collect **30–60** images of your character: different angles, expressions, outfits, close-ups and full body. The face must be the same person in every image.
2. Put a `.txt` caption with the same name next to each image, starting with the trigger word: `photo of <trigger> woman, close-up portrait, smiling, ...`
3. Pick the architecture in ai-toolkit:
   - **Z-Image Turbo** (`zimage:turbo`) — best face consistency; ~2.5–3 h
   - **MOSS-Image** (`moss_image`, `quantize: convrot8`, `low_vram: true`) — most realistic; ~1.5–2 h
4. 2,500–3,600 steps, rank 32, learning rate 1e-4 is a good start.
5. Check face similarity with ArcFace (insightface); above 0.6 is good.

## 4. The face-fix method (the key trick)

Realism models (MOSS, SDXL realism checkpoints) can't hit your character's face exactly. The fix:

1. Generate the scene with the realism model (e.g. MOSS + cndamiph).
2. Detect **all large faces** in the image (including the reflection in mirror shots).
3. Crop each face with a square 2.2× the face size and upscale it to 1024x1024.
4. Redraw it with Z-Image + your character LoRA as **img2img at denoise 0.45**.
5. Paste it back with a soft oval mask and colour/light matching.

Measured result: similarity ~0.43 → ~0.51 (SDXL), ~0.39 → ~0.48 (MOSS). Denoise 0.35 is too weak, 0.55 overshoots.

## 5. Video Workshop

Makes a video from the same image with each selected engine in turn and frees memory after each engine.

| Engine | Strength | 5 s on 16 GB |
|---|---|---|
| **Wan 2.2** | Follows the prompt and camera moves best, 800x1168 | ~7–8 min |
| **FramePack Standard** | Keeps the face most stable, calm motion, 512x768 | ~18 min |
| **FramePack F1** | More motion; the face can drift near the end of long clips | ~18 min |
| **LTX-2.3** | Fastest; lower quality | ~3 min |

Longer videos (10–15 s) are chains of 5-second clips: each clip starts from the previous clip's last frame, colours are matched to the first image, and clips are scaled to the same size before merging.

**Prompt tips**
- At most **two** actions per 5 seconds.
- Pin the position ("she stays lying down") and the direction of a move ("arms above her head").
- End with: `same face, consistent appearance, steady camera`.
- Avoid moves that cover the eyes (putting on sunglasses etc.) — the model can lose identity. Do the reverse instead (start with sunglasses on, take them off at the end).

## 6. Shorts pipeline

```
cd araclar
python shorts_uret.py ornek.json --aday 3                      # make 3 candidate images, pick the most natural
python shorts_uret.py ornek.json --resim cikti\kafe\aday_2.jpg  # make the video from the chosen one
```

`araclar/ornek.json` (English example):

```json
{
  "ad": "cafe",
  "sahne_en": "sitting at an outdoor cafe, knit sweater, holding a coffee cup, serious face",
  "hareket_en": "She looks at the camera seriously, then breaks into a warm laugh and tucks her hair behind her ear.",
  "yazi1": "They say she always looks so serious…",
  "yazi2": "until she laughs",
  "baslik": "Agree? 👀"
}
```

Output: 1080x1920, light grain/saturation filter, two-part text in the middle of the screen. Add music from the platform's own library (no copyright issues).

**Viral Shorts format (from channel analysis):** 6–9 seconds, one take, shot-on-a-phone feel, real location, two-part text (setup → punchline), the title always asks the viewer a question.

**For a natural look:** use phrases like "amateur photo shot on iPhone, slightly off-center, harsh midday sun, people in the background, everyday clutter"; avoid perfect poses and studio light.

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| ComfyUI "list index out of range" when switching models | Free memory completely with `/free` before each model switch |
| Long-video clips won't merge | Clips can differ by a few pixels; scale them to the first clip's size before merging |
| ffmpeg has no `ass`/`drawtext` | Draw the text as a transparent PNG with Python (PIL) and use `overlay` |
| Video generated twice / wrong length | Lock the button on click; pass clip length to the engine directly, not through shared settings |
| White clothing turns half-transparent when removing a background | If the fast model is unsure (8%+ of the mask semi-transparent), switch to BiRefNet |

## 8. Responsible use

- Characters must be **fictional adults**; anything suggesting a minor is blocked.
- Use photos of real people **only with their consent** and never for nudity or sexual content.
- Label videos with realistic AI people as **"AI-generated / synthetic content"** on YouTube/Instagram.
- Use other creators' videos only to study their format; never re-upload them.
