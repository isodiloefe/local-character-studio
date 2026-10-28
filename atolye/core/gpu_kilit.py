"""Ekran kartını kullanan programlar arasında ortak sıra.

İki program da ekran kartını kullanan her işi (metin, resim, video) bu kilitle çalıştırır;
biri çalışırken diğeri bekler. Kilit dosyası iki programın ortak üst klasöründedir.
Program çökerse Windows kilidi kendiliğinden bırakır.
"""
import contextlib
import msvcrt
import os
import time
from pathlib import Path

LOCK_FILE = Path(__file__).resolve().parents[2] / "gpu_kilit.lock"


@contextlib.contextmanager
def gpu_lock(app_name, wait_cb=None):
    LOCK_FILE.touch(exist_ok=True)
    fd = os.open(LOCK_FILE, os.O_RDWR)
    start = time.time()
    try:
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if wait_cb:
                    wait_cb(f"Sıra bekleniyor: diğer program ekran kartını kullanıyor... {int(time.time() - start)} sn")
                time.sleep(2)
        # kimin tuttuğunu dosyaya yaz (sadece bilgi amaçlı)
        with open(LOCK_FILE.with_suffix(".sahip"), "w", encoding="utf-8") as f:
            f.write(f"{app_name} (pid {os.getpid()})")
        yield
    finally:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(fd)
