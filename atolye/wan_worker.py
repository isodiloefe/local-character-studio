"""WanGP video sunucusu. WanGP'nin kendi Python ortamıyla çalıştırılır:
    <wan_dir>\\env\\Scripts\\python.exe wan_worker.py <wan_dir> <port>
Uses WanGP (https://github.com/deepbeepmeep/Wan2GP) through its Python API.
"""
import os
import sys
import threading
import traceback
import uuid
from pathlib import Path

WAN_DIR = Path(sys.argv[1])
PORT = int(sys.argv[2])
os.chdir(WAN_DIR)
sys.path.insert(0, str(WAN_DIR))

import uvicorn  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

app = FastAPI()
state = {"session": None, "init_error": None}
jobs = {}
lock = threading.Lock()


def _init():
    try:
        from shared.api import init
        state["session"] = init(root=WAN_DIR, console_output=True)
    except Exception:
        state["init_error"] = traceback.format_exc()


threading.Thread(target=_init, daemon=True).start()


class VideoReq(BaseModel):
    image: str
    prompt: str
    model: str = "ltx2_22B_distilled"
    resolution: str = "1280x720"
    seconds: int = 5
    output_dir: str
    # Uzun video: her satir bir bolumun komutu. Bolumler WanGP'nin "sliding window"u ile uretilir;
    # her bolum bir oncekinin son WINDOW_OVERLAP karesini gorerek devam eder.
    segments: list[str] = []
    steps: int = 0  # 0: hizli (distilled) modellerde 8, digerlerinde modelin kendi varsayilani
    extra: dict = {}  # modele ozel ek WanGP ayarlari (orn. Wan 2.2 Lightning: activated_loras, guidance...)


WINDOW = 129  # bolum uzunlugu (kare): ~5.4 sn
WINDOW_OVERLAP = 17  # bolumler arasi ortak kare (devamlilik icin)


def _run(job_id, req: VideoReq):
    job = jobs[job_id]
    with lock:
        try:
            fps = 24
            frames = (req.seconds * fps // 8) * 8 + 1
            prompt = req.prompt
            extra = {}
            if len(req.segments) > 1:
                frames = WINDOW + (len(req.segments) - 1) * (WINDOW - WINDOW_OVERLAP)
                prompt = "\n".join(s.replace("\n", " ").strip() for s in req.segments)
                extra = {"sliding_window_size": WINDOW, "sliding_window_overlap": WINDOW_OVERLAP,
                         "multi_prompts_gen_type": "W"}
            settings = {
                "model_type": req.model,
                "prompt": prompt,
                "image_prompt_type": "S",
                "image_start": req.image,
                "resolution": req.resolution,
                "video_length": frames,
                "force_fps": fps,
                **extra,
            }
            steps = req.steps or (8 if "distilled" in req.model else 0)
            if steps:
                settings["num_inference_steps"] = steps
            settings.update(req.extra)
            Path(req.output_dir).mkdir(parents=True, exist_ok=True)
            j = state["session"].submit_task(settings)
            job["status"] = "running"
            for ev in j.events.iter(timeout=0.5):
                if ev.kind == "progress":
                    p = ev.data
                    job["progress"] = f"{p.phase} {p.current_step or 0}/{p.total_steps or 0}"
            res = j.result()
            if res.success and res.generated_files:
                import shutil
                src = Path(res.generated_files[-1])
                dst = Path(req.output_dir) / f"video_{job_id}{src.suffix}"
                shutil.move(str(src), dst)
                job.update(status="done", file=str(dst))
            else:
                job.update(status="error", error="; ".join(e.message for e in res.errors) or "Video üretilemedi")
        except Exception:
            job.update(status="error", error=traceback.format_exc()[-1500:])


@app.get("/health")
def health():
    return {"ready": state["session"] is not None, "error": state["init_error"]}


@app.post("/video")
def video(req: VideoReq):
    if state["session"] is None:
        raise HTTPException(503, state["init_error"] or "WanGP henüz yükleniyor")
    job_id = uuid.uuid4().hex[:10]
    jobs[job_id] = {"status": "queued", "progress": ""}
    threading.Thread(target=_run, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.post("/shutdown")
def shutdown():
    """Başka bir program ekran kartına ihtiyaç duyduğunda bu sunucuyu kapatır."""
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


@app.get("/job/{job_id}")
def job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404)
    return jobs[job_id]


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
