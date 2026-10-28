"""Video Atölyesi: karakterinin resmini üret (MOSS-Image + karakter LoRA'sıyla yüz düzeltme), sonra aynı resimden
seçtiğin video motorlarıyla (FramePack Standart/F1, Wan 2.2, LTX-2.3) sırayla video yap ve karşılaştır.
Tamamen yerel çalışır. Kural: karakter hayali bir yetişkindir; reşit olmayan izlenimi veren komutlar engellenir.
"""
import atexit
import io
import os
import queue
import threading
import time
import traceback
from pathlib import Path

import flet as ft
from PIL import Image

from core import config
from core.comfy import Comfy
from core.config import ENGINES, IMAGES_DIR, VIDEOS_DIR
from core.gpu_kilit import gpu_lock
from core.motorlar import Motorlar
from core.safety import check_visual_prompt
from core.translate import Translator

cfg = config.load()
translator = Translator(cfg)
comfy = Comfy(cfg)
motorlar = Motorlar(cfg, comfy)
atexit.register(lambda: (motorlar.stop_all(shared=False), comfy.stop()))
ENGINE_NAMES = {k: n for k, n, _ in ENGINES}
HAZIR_KLASORLER = [Path(p) for p in cfg.get("ready_folders", [])]  # ayarlar.json'daki hazır resim klasörleri
_thumbs = {}


def thumb(path, size=256):
    key = (str(path), size, Path(path).stat().st_mtime if Path(path).exists() else 0)
    if key not in _thumbs:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=85)
            _thumbs[key] = buf.getvalue()
    return _thumbs[key]


def hazir_resimler():
    yollar = []
    for k in HAZIR_KLASORLER:
        if k.exists():
            yollar += sorted(p for p in k.rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    return yollar


def main(page: ft.Page):
    page.title = "Video Atölyesi"
    page.padding = 0
    page.window.width = 1500
    page.window.height = 920

    library = config.load_library()
    state = {"image": None, "item": None, "candidates": [], "scene_src": None, "motion_src": None}
    jobs = queue.Queue()

    def toast(msg, error=False):
        page.show_dialog(ft.SnackBar(ft.Text(msg), bgcolor=ft.Colors.ERROR if error else None, duration=7000))

    # ------------------------------------------------------------------ durum çubuğu
    stage_title = ft.Text("Hazır", size=18, weight=ft.FontWeight.BOLD)
    stage_clock = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    status_text = ft.Text("", size=13, color=ft.Colors.ON_SURFACE_VARIANT)
    progress = ft.ProgressBar(value=0, height=3)
    clock = {"start": None}

    def set_stage(title):
        stage_title.value = title
        page.update()

    def set_status(msg):
        status_text.value = msg
        page.update()

    def tick():
        while True:
            time.sleep(1)
            if clock["start"]:
                t = int(time.time() - clock["start"])
                stage_clock.value = f"Toplam: {t // 60}:{t % 60:02d}"
                page.update()

    threading.Thread(target=tick, daemon=True).start()

    def worker():
        while True:
            title, fn = jobs.get()
            clock["start"] = time.time()
            set_stage(title)
            progress.value = None
            set_buttons(False)
            ok = True
            try:
                with gpu_lock("Video Atölyesi", wait_cb=set_status):
                    set_status("")
                    fn()
            except Exception as e:
                ok = False
                traceback.print_exc()
                toast(str(e)[:500], error=True)
            el = int(time.time() - clock["start"])
            clock["start"] = None
            stage_title.value = f"Tamamlandı ({el // 60} dk {el % 60} sn)" if ok else "Hata oluştu"
            stage_clock.value = status_text.value = ""
            progress.value = 0
            set_buttons(True)
            page.update()

    threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ 1. resim (sol)
    scene_field = ft.TextField(label="Resim nasıl olsun? (Türkçe ya da İngilizce)", multiline=True, min_lines=3,
                               max_lines=6, hint_text="Örn: Yatakta çıplak uzanıyor, yukarıdan geniş açı, "
                                                      "tüm vücudu görünüyor, sabah ışığı.")
    scene_en = ft.TextField(label="İngilizce (resim modeline giden; düzeltebilirsiniz)", multiline=True,
                            min_lines=2, max_lines=5, text_size=12)
    size_dd = ft.Dropdown(value=cfg["size"], width=170, label="Boyut", options=[
        ft.DropdownOption(key="832x1216", text="Dikey"), ft.DropdownOption(key="1216x832", text="Yatay"),
        ft.DropdownOption(key="1024x1024", text="Kare")])
    count_dd = ft.Dropdown(value=str(cfg["count"]), width=120, label="Adet",
                           options=[ft.DropdownOption(key=str(n), text=str(n)) for n in (1, 2, 4, 6)])
    candidates = ft.Row(wrap=True, spacing=6, run_spacing=6)

    def english_scene():
        text = (scene_field.value or "").strip()
        if not text:
            raise RuntimeError("Önce resmin nasıl olacağını yazın.")
        if state["scene_src"] == text and (scene_en.value or "").strip():
            return scene_en.value.strip()
        set_status("Komut İngilizceye çevriliyor...")
        en, _ = translator.scene(text)
        scene_en.value, state["scene_src"] = en, text
        page.update()
        return en

    def make_images():
        en = english_scene()
        if blocked := check_visual_prompt((scene_field.value or "") + " " + en):
            raise RuntimeError(blocked)
        translator.unload()
        motorlar.stop_all(shared=True)  # video motorları belleği tutmasın
        IMAGES_DIR.mkdir(exist_ok=True)
        cfg["size"], cfg["count"] = size_dd.value, int(count_dd.value)
        config.save(cfg)
        yeni = []
        for i in range(int(count_dd.value)):
            set_stage(f"Resim {i + 1}/{count_dd.value} üretiliyor...")
            out = IMAGES_DIR / f"resim_{time.strftime('%Y%m%d_%H%M%S')}_{i + 1}.jpg"
            seed = comfy.generate(en, out, status_cb=set_status)
            item = {"image": str(out), "prompt": (scene_field.value or "").strip(), "prompt_en": en, "seed": seed,
                    "created": time.strftime("%Y-%m-%d %H:%M"), "videos": {}}
            library.insert(0, item)
            config.save_library(library)  # sonraki resimde hata çıksa da bu kaybolmasın
            yeni.append(item)
            state["candidates"] = yeni
            show_candidates()
        config.save_library(library)
        comfy.free()
        refresh_history()
        if yeni:
            select(yeni[0])

    def show_candidates():
        candidates.controls = [
            ft.Container(
                content=ft.Image(src=thumb(it["image"], 300), width=130, height=190, fit=ft.BoxFit.COVER, border_radius=6),
                border=ft.Border.all(3, ft.Colors.PRIMARY if state["item"] is it else ft.Colors.TRANSPARENT),
                border_radius=8, on_click=lambda _, it=it: select(it), tooltip="Video için bu resmi seç")
            for it in state["candidates"]]
        page.update()

    def on_images(_):
        if not (scene_field.value or "").strip():
            toast("Önce resmin nasıl olacağını yazın.", error=True)
            return
        set_buttons(False)  # hemen kilitle: çift tıklama aynı işi iki kez sıraya koymasın
        page.update()
        jobs.put(("Resimler hazırlanıyor...", make_images))

    images_btn = ft.Button("Resimleri üret", icon=ft.Icons.BRUSH, on_click=on_images)

    def hazir_sec(_):
        yollar = hazir_resimler()
        if not yollar:
            toast("Hazır resim bulunamadı. ayarlar.json içindeki \"ready_folders\" listesine klasör ekleyin.", error=True)
            return
        grid = ft.Row(wrap=True, spacing=6, run_spacing=6, controls=[
            ft.Container(content=ft.Image(src=thumb(p, 220), width=110, height=160, fit=ft.BoxFit.COVER,
                                          border_radius=6),
                         on_click=lambda _, p=p: (page.pop_dialog(), select_path(p)), tooltip=p.name)
            for p in yollar])
        page.show_dialog(ft.AlertDialog(title=ft.Text("Hazır resimler"),
                                        content=ft.Container(width=760, height=520,
                                                             content=ft.Column([grid], scroll=ft.ScrollMode.AUTO))))

    picker = ft.FilePicker()
    page.services.append(picker)

    async def yukle(_):
        files = await picker.pick_files(dialog_title="Resim seçin", allow_multiple=False,
                                        allowed_extensions=["jpg", "jpeg", "png", "webp"])
        if files and files[0].path:
            src = Path(files[0].path)
            IMAGES_DIR.mkdir(exist_ok=True)
            dst = IMAGES_DIR / f"yuklenen_{time.strftime('%Y%m%d_%H%M%S')}{src.suffix.lower()}"
            Image.open(src).convert("RGB").save(dst.with_suffix(".jpg"), "JPEG", quality=95)
            select_path(dst.with_suffix(".jpg"))

    def select_path(p):
        p = str(p)
        item = next((it for it in library if it["image"] == p), None)
        if item is None:
            item = {"image": p, "prompt": "", "prompt_en": "", "seed": None,
                    "created": time.strftime("%Y-%m-%d %H:%M"), "videos": {}}
            library.insert(0, item)
            config.save_library(library)
            refresh_history()
        select(item)

    left = ft.Container(width=420, padding=14, bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
                        content=ft.Column([
                            ft.Text("1. Resim", size=18, weight=ft.FontWeight.BOLD),
                            ft.Text("MOSS-Image + karakter LoRA'sı, yüz otomatik düzeltilir", size=11,
                                    color=ft.Colors.ON_SURFACE_VARIANT),
                            scene_field, scene_en,
                            ft.Row([size_dd, count_dd], wrap=True),
                            ft.Row([images_btn, ft.TextButton("Hazır resim seç", icon=ft.Icons.PHOTO_LIBRARY,
                                                              on_click=hazir_sec),
                                    ft.TextButton("Resim yükle", icon=ft.Icons.UPLOAD_FILE, on_click=yukle)],
                                   wrap=True),
                            ft.Text("Gerçek kişilerin fotoğraflarını yalnızca rızalarıyla ve çıplaklık/cinsel içerik "
                                    "olmadan kullanın.", size=11, color=ft.Colors.ERROR),
                            ft.Text("Karakterler hayali yetişkinlerdir; reşit olmayan birini ima eden her istek "
                                    "engellenir.", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text("Üretilenler (tıklayıp seçin)", size=13, weight=ft.FontWeight.BOLD),
                            candidates,
                        ], scroll=ft.ScrollMode.AUTO, spacing=10))

    # ------------------------------------------------------------------ 2. video (orta)
    selected_view = ft.Container(width=220, height=320)
    motion_field = ft.TextField(label="Videoda ne olsun? (Türkçe ya da İngilizce)", multiline=True, min_lines=3,
                                max_lines=6, hint_text="Örn: Yavaşça gerinip gözlerini açıyor, kameraya gülümsüyor.")
    motion_en = ft.TextField(label="İngilizce (video motorlarına giden; düzeltebilirsiniz)", multiline=True,
                             min_lines=2, max_lines=5, text_size=12)
    seconds_dd = ft.Dropdown(value=str(cfg["video_seconds"]), width=140, label="Süre",
                             options=[ft.DropdownOption(key=str(s), text=f"{s} sn") for s in (5, 10, 15)])
    engine_checks = {k: ft.Checkbox(label=f"{n}  ·  {d}", value=k in cfg["engines"]) for k, n, d in ENGINES}
    results = ft.Column(spacing=8)

    def select(item):
        state["item"], state["image"] = item, Path(item["image"])
        selected_view.content = ft.Image(src=thumb(item["image"], 640), fit=ft.BoxFit.CONTAIN, width=220, height=320,
                                         border_radius=8)
        show_candidates()
        show_results()

    def english_motion():
        text = (motion_field.value or "").strip()
        if not text:
            raise RuntimeError("Videoda ne olacağını yazın.")
        if state["motion_src"] == text and (motion_en.value or "").strip():
            return motion_en.value.strip()
        set_status("Video komutu İngilizceye çevriliyor...")
        en, _ = translator.motion(text)
        motion_en.value, state["motion_src"] = en, text
        page.update()
        return en

    def make_videos(secili):
        item = state["item"]
        en = english_motion()
        if blocked := check_visual_prompt((motion_field.value or "") + " " + en):
            raise RuntimeError(blocked)
        translator.unload()
        comfy.stop()
        seconds = int(seconds_dd.value)
        hatalar = []
        try:
            for i, motor in enumerate(secili, 1):
                ad = ENGINE_NAMES[motor]
                set_stage(f"{i}/{len(secili)}: {ad} ile video yapılıyor...")
                t = time.time()
                try:
                    yol = motorlar.run(motor, Path(item["image"]), en, seconds, VIDEOS_DIR,
                                       status_cb=set_status, stage_cb=set_status)
                except Exception as e:
                    traceback.print_exc()
                    hatalar.append(f"{ad}: {str(e)[:200]}")
                    continue
                item.setdefault("videos", {})[motor] = {
                    "file": str(yol), "prompt_en": en, "seconds": seconds,
                    "sure": int(time.time() - t), "created": time.strftime("%Y-%m-%d %H:%M")}
                config.save_library(library)
                show_results()
                refresh_history()
        finally:
            motorlar.stop_all(shared=True)  # FramePack ~22 GB bellek tutar; iş bitince kapat
        if hatalar:
            raise RuntimeError("Bazı motorlar çalışmadı:\n" + "\n".join(hatalar))

    def on_videos(_):
        if not state["item"]:
            toast("Önce bir resim seçin.", error=True)
            return
        if not (motion_field.value or "").strip():
            toast("Videoda ne olacağını yazın.", error=True)
            return
        secili = [k for k, _, _ in ENGINES if engine_checks[k].value]
        if not secili:
            toast("En az bir video motoru seçin.", error=True)
            return
        cfg.update(engines=secili, video_seconds=int(seconds_dd.value))
        config.save(cfg)
        set_buttons(False)  # hemen kilitle: çift tıklama aynı işi iki kez sıraya koymasın
        page.update()
        jobs.put((f"{len(secili)} motorla video yapılıyor...", lambda: make_videos(secili)))

    def show_results():
        item = state["item"]
        vids = (item or {}).get("videos", {})
        rows = []
        for k, n, _ in ENGINES:
            v = vids.get(k)
            if not v or not Path(v["file"]).exists():
                continue
            rows.append(ft.Container(
                padding=10, border_radius=10, border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                content=ft.Row([
                    ft.Column([ft.Text(n, weight=ft.FontWeight.BOLD),
                               ft.Text(f"{v['seconds']} sn video · {v['sure'] // 60} dk {v['sure'] % 60} sn sürdü · "
                                       f"{v['created']}", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                               ft.Text(v["prompt_en"], size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)],
                              spacing=2, expand=True),
                    ft.Button("Oynat", icon=ft.Icons.PLAY_ARROW, on_click=lambda _, f=v["file"]: os.startfile(f)),
                    ft.IconButton(ft.Icons.FOLDER_OPEN, tooltip="Klasörde göster",
                                  on_click=lambda _, f=v["file"]: os.startfile(Path(f).parent)),
                ])))
        results.controls = rows or [ft.Text("Bu resim için henüz video yok.", color=ft.Colors.ON_SURFACE_VARIANT)]
        page.update()

    videos_btn = ft.Button("Videoları sırayla üret", icon=ft.Icons.MOVIE, on_click=on_videos)

    def set_buttons(enabled):
        images_btn.disabled = videos_btn.disabled = not enabled

    center = ft.Column([
        ft.Container(padding=16, border_radius=12, margin=ft.Padding.only(left=20, right=20, top=16),
                     bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.PRIMARY),
                     content=ft.Column([ft.Row([stage_title, ft.Container(expand=True), stage_clock]), status_text],
                                       spacing=6)),
        progress,
        ft.Container(expand=True, padding=ft.Padding.symmetric(horizontal=20, vertical=12), content=ft.Column([
            ft.Text("2. Video", size=18, weight=ft.FontWeight.BOLD),
            ft.Row([selected_view, ft.Column([motion_field, motion_en, seconds_dd], expand=True, spacing=8)],
                   vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Text("Motorlar (seçilenler sırayla çalışır, her biri bitince belleği boşaltılır)", size=13,
                    weight=ft.FontWeight.BOLD),
            *engine_checks.values(),
            ft.Row([videos_btn]),
            ft.Text("Sonuçlar", size=14, weight=ft.FontWeight.BOLD),
            results,
            ft.Text("İpucu: 5 saniyeye en fazla iki hareket yazın. FramePack çalışırken Pinokio'daki FramePack "
                    "kapalı olmalı.", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
        ], scroll=ft.ScrollMode.AUTO, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),
    ], expand=True, spacing=0)

    # ------------------------------------------------------------------ geçmiş (sağ)
    history = ft.ListView(expand=True, spacing=8)

    def delete_item(item):
        """Kaydı sadece listeden kaldırır; resim ve video dosyaları diskte kalır."""
        library.remove(item)
        config.save_library(library)
        if state["item"] is item:
            state["item"] = state["image"] = None
            selected_view.content = None
        state["candidates"] = [c for c in state["candidates"] if c is not item]
        show_candidates()
        show_results()
        refresh_history()

    def ask_delete(item):
        ne = ("Bu kayıt listeden kaldırılacak. Resim ve video dosyaları diskte kalır "
              f"({IMAGES_DIR.name} ve {VIDEOS_DIR.name} klasörlerinde).")

        def evet(_):
            page.pop_dialog()
            delete_item(item)

        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Listeden kaldırılsın mı?"), content=ft.Text(ne),
            actions=[ft.TextButton("Vazgeç", on_click=lambda _: page.pop_dialog()),
                     ft.Button("Kaldır", icon=ft.Icons.PLAYLIST_REMOVE, on_click=evet)]))

    def refresh_history():
        rows = []
        for item in library:
            if not Path(item["image"]).exists():
                continue
            n = sum(1 for v in item.get("videos", {}).values() if Path(v["file"]).exists())
            rows.append(ft.Container(
                padding=8, border_radius=10, border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                on_click=lambda _, it=item: select(it),
                content=ft.Row([
                    ft.Image(src=thumb(item["image"], 160), width=60, height=80, fit=ft.BoxFit.COVER, border_radius=6),
                    ft.Column([ft.Text(item.get("prompt") or Path(item["image"]).name, size=12, max_lines=2,
                                       overflow=ft.TextOverflow.ELLIPSIS),
                               ft.Text(item.get("created", "") + (f" · {n} video" if n else ""), size=11,
                                       color=ft.Colors.ON_SURFACE_VARIANT)], expand=True, spacing=2),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip="Listeden kaldır", icon_size=18,
                                  on_click=lambda _, it=item: ask_delete(it)),
                ], vertical_alignment=ft.CrossAxisAlignment.START)))
        history.controls = rows or [ft.Text("Henüz kayıt yok.", color=ft.Colors.ON_SURFACE_VARIANT)]
        page.update()

    right = ft.Container(width=330, padding=12, content=ft.Column([
        ft.Text("Geçmiş", size=16, weight=ft.FontWeight.BOLD), history], expand=True))

    page.add(ft.Row([left, ft.VerticalDivider(width=1), center, ft.VerticalDivider(width=1), right],
                    expand=True, spacing=0))
    refresh_history()
    show_results()


if __name__ == "__main__":
    ft.run(main)
