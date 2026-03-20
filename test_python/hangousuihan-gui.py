#!/usr/bin/env python3
"""
hangousuihan GUI版 - tkinter
画像アーカイブ（ZIP, 7Z, RAR, LZH）を展開・画像リサイズ・再パッケージ
"""

import os
import queue
import re
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import unicodedata
import zipfile
from pathlib import Path

from PIL import Image

# --- デフォルト設定 ---
DEFAULT_TARGET_DIR = Path("./target")
DEFAULT_RESULT_DIR = Path("./result")
DEFAULT_TEMP_DIR = Path("./tmp")
RESIZE_MAX_W = 1920
RESIZE_MAX_H = 1920
JPEG_QUALITY = 90

ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".lzh"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

# 出力形式設定: Pillow format名, 拡張子, save時キーワード引数
OUTPUT_FORMATS = {
    "JPEG": {"ext": ".jpg", "save_kwargs": lambda q: {"quality": q}},
    "PNG":  {"ext": ".png", "save_kwargs": lambda q: {"compress_level": min(q // 10, 9)}},
    "WEBP": {"ext": ".webp", "save_kwargs": lambda q: {"quality": q}},
}


# ============================================================
# コアロジック（CLIと共通）
# ============================================================

def extract_archive(path: Path, dest: Path, log) -> bool:
    ext = path.suffix.lower()
    try:
        if ext == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(dest)
            return True
        elif ext == ".7z":
            import py7zr
            with py7zr.SevenZipFile(path, mode="r") as sz:
                sz.extractall(path=dest)
            return True
        elif ext == ".rar":
            import rarfile
            with rarfile.RarFile(path, "r") as rf:
                rf.extractall(dest)
            return True
        elif ext == ".lzh":
            import lhafile
            lha = lhafile.Lhafile(str(path))
            for info in lha.infolist():
                if info.filename.endswith("/") or info.filename.endswith("\\"):
                    continue
                out_path = dest / info.filename.replace("\\", "/")
                out_path.parent.mkdir(parents=True, exist_ok=True)
                with open(out_path, "wb") as f:
                    f.write(lha.read(info.filename))
            return True
    except Exception as e:
        log(f"! error extracting {path}: {e}")
    return False


def archive_contains_root_dir(path: Path, dir_name: str) -> bool:
    ext = path.suffix.lower()
    try:
        if ext == ".zip":
            with zipfile.ZipFile(path, "r") as zf:
                return any(n.startswith(dir_name + "/") for n in zf.namelist())
        elif ext == ".7z":
            import py7zr
            with py7zr.SevenZipFile(path, mode="r") as sz:
                return any(n.startswith(dir_name + "/") for n in sz.getnames())
        elif ext == ".rar":
            import rarfile
            with rarfile.RarFile(path, "r") as rf:
                return any(n.startswith(dir_name + "/") for n in rf.namelist())
        elif ext == ".lzh":
            import lhafile
            lha = lhafile.Lhafile(str(path))
            return any(
                info.filename.replace("\\", "/").startswith(dir_name + "/")
                for info in lha.infolist()
            )
    except Exception:
        pass
    return False


def create_zip(source_dir: Path, dest_zip: Path) -> None:
    base = source_dir.resolve()
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_STORED) as zf:
        for f in recursive_files(source_dir):
            p = f["path"]
            arcname = str(p.resolve().relative_to(base))
            info = zipfile.ZipInfo.from_file(p, arcname)
            info.compress_type = zipfile.ZIP_STORED
            with open(p, "rb") as fh:
                zf.writestr(info, fh.read())


def resize_image(src: Path, dest: Path, log,
                 max_w: int = RESIZE_MAX_W, max_h: int = RESIZE_MAX_H,
                 quality: int = JPEG_QUALITY,
                 out_format: str = "JPEG") -> bool:
    try:
        with Image.open(src) as img:
            if out_format == "PNG":
                img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            w, h = img.size
            if w > max_w or h > max_h:
                ratio = min(max_w / w, max_h / h)
                new_w = round(w * ratio)
                new_h = round(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)
            fmt_info = OUTPUT_FORMATS[out_format]
            img.save(dest, out_format, **fmt_info["save_kwargs"](quality))
        return True
    except Exception as e:
        log(f"! resize failed: {src}: {e}")
        return False


def safe_filename(s: str, include_sep: bool = True) -> str:
    if "_u" in s:
        s = re.sub(
            r"_u([0-9a-f]{4})",
            lambda m: chr(int(m.group(1), 16)),
            s,
        )
    replacements = {
        "\u2013": "-",
        "\u301C": "\uFF5E",
        "\u2661": "\u25BD",
        "\u2665": "\u25BC",
    }
    for old, new in replacements.items():
        s = s.replace(old, new)
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[\U00010000-\U0010FFFF]", "\u25C6", s)
    try:
        tmp = s.encode("cp932", errors="replace")
        s = tmp.decode("cp932")
        s = s.replace("?", "_")
    except Exception:
        pass
    meta_map = {
        "?": "\uFF1F", "*": "\uFF0A", "#": "\uFF03", ":": "\uFF1A",
        ";": "\uFF1B", '"': "\u201C", "'": "\u2018", "`": "\uFF40",
        "$": "\uFF04", "%": "\uFF05", "&": "\uFF06", "<": "\uFF1C",
        ">": "\uFF1E", "+": "\uFF0B", ",": "\uFF0C",
    }
    if include_sep:
        meta_map["/"] = "\uFF0F"
        meta_map["\\"] = "\uFFE5"
    for old, new in meta_map.items():
        s = s.replace(old, new)
    return s


def rename_if_needed(path: Path, safe_dir: Path, safe_base: str, log) -> None:
    dest = safe_dir / (safe_base + path.suffix)
    if dest != path:
        log(f"> mv {path} {dest}")
        path.rename(dest)


def recursive_files(path: Path) -> list[dict]:
    results = []
    for p in sorted(path.rglob("*")):
        if not p.is_file():
            continue
        results.append({
            "path": p,
            "name": p.name,
            "size": p.stat().st_size,
            "mtime": p.stat().st_mtime,
        })
    return results


def rm_rf(path: Path, leave_folder: bool = False) -> None:
    s = str(path)
    if s.startswith("/") or s.startswith("\\"):
        return
    if re.match(r"^(?:file://)?/?[a-zA-Z]:/", s):
        return
    if ".." in s:
        return
    if not path.is_dir():
        return
    for entry in sorted(path.rglob("*"), reverse=True):
        if entry.is_file() or entry.is_symlink():
            entry.unlink()
        elif entry.is_dir():
            try:
                entry.rmdir()
            except OSError:
                pass
    if not leave_folder:
        try:
            path.rmdir()
        except OSError:
            pass


def process_archives(target_dir: Path, result_dir: Path, temp_dir: Path,
                     noresize: bool, log, on_progress, on_done,
                     max_w: int = RESIZE_MAX_W, max_h: int = RESIZE_MAX_H,
                     quality: int = JPEG_QUALITY,
                     out_format: str = "JPEG") -> None:
    """メイン処理（ワーカースレッドから呼ばれる）"""
    target_dir.mkdir(exist_ok=True)
    temp_dir.mkdir(exist_ok=True)
    result_dir.mkdir(exist_ok=True)

    archives = [
        f for f in sorted(target_dir.iterdir())
        if f.is_file() and f.suffix.lower() in ARCHIVE_EXTS
    ]

    if not archives:
        log(f"エラー: {target_dir} にアーカイブが見つかりません")
        on_done(0, 0)
        return

    total = len(archives)
    success = 0

    for idx, f in enumerate(archives):
        if "_new." in f.name:
            continue

        stat_mtime = f.stat().st_mtime
        renameto = (
            f.stem + ".zip" if noresize
            else f.stem + "_new.zip"
        )
        renameto = safe_filename(renameto)

        log(f"> rm -rf {temp_dir}")
        rm_rf(temp_dir, leave_folder=True)

        log(f"> extract {f}")
        if not extract_archive(f, temp_dir, log):
            log(f"! extract failed: {f}")
            on_progress(idx + 1, total)
            continue

        # ネスト書庫展開
        for f2 in recursive_files(temp_dir):
            if f2["size"] > 0 and f2["path"].suffix.lower() in ARCHIVE_EXTS:
                f2_dir = safe_filename(f2["path"].stem)
                has_root = archive_contains_root_dir(f2["path"], f2_dir)
                if has_root:
                    extract_to = temp_dir
                else:
                    extract_to = temp_dir / f2_dir
                    extract_to.mkdir(parents=True, exist_ok=True)
                log(f"> extract nested {f2['path']}")
                extract_archive(f2["path"], extract_to, log)
                f2["path"].unlink()
                log(f"> rm {f2['path']}")

        # リサイズとリネーム
        unlink_dirs: set[str] = set()
        for f2 in recursive_files(temp_dir):
            if f2["size"] <= 0 or f2["path"].suffix.lower() not in IMAGE_EXTS:
                continue
            p = f2["path"]
            rel_parent = p.parent.relative_to(temp_dir)
            safe_rel = Path(safe_filename(str(rel_parent), include_sep=False)) if str(rel_parent) != "." else Path(".")
            safe_dir = temp_dir / safe_rel
            safe_base = safe_filename(p.stem)
            if str(p.parent) != str(safe_dir):
                if not safe_dir.exists():
                    safe_dir.mkdir(parents=True, exist_ok=True)
                    unlink_dirs.add(str(p.parent))
            if not noresize:
                out_ext = OUTPUT_FORMATS[out_format]["ext"]
                convert_to = safe_dir / (safe_base + "_new" + out_ext)
                log(f"> resize {p}")
                ok = resize_image(p, convert_to, log, max_w, max_h, quality, out_format)
                if ok and convert_to.exists() and convert_to.stat().st_size > 0:
                    os.utime(convert_to, (f2["mtime"], f2["mtime"]))
                    log(f"> rm {p}")
                    p.unlink()
                else:
                    rename_if_needed(p, safe_dir, safe_base, log)
            else:
                rename_if_needed(p, safe_dir, safe_base, log)

        for ud in unlink_dirs:
            try:
                os.rmdir(ud)
            except OSError:
                pass

        # ZIP再パック
        result_path = result_dir / renameto
        if result_path.exists():
            result_path.unlink()
        log(f"> pack {result_path}")
        create_zip(temp_dir, result_path)
        os.utime(result_path, (stat_mtime, stat_mtime))
        success += 1
        on_progress(idx + 1, total)

    log(f"> rm -rf {temp_dir}")
    rm_rf(temp_dir, leave_folder=True)
    on_done(success, total)


# ============================================================
# GUI
# ============================================================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("hangousuihan GUI（id-fa 私家版）")
        self.geometry("720x560")
        self.minsize(600, 400)

        self._msg_queue: queue.Queue[str] = queue.Queue()
        self._running = False

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # --- ディレクトリ設定 ---
        frame_dirs = ttk.LabelFrame(self, text="ディレクトリ設定")
        frame_dirs.pack(fill="x", **pad)

        # target
        ttk.Label(frame_dirs, text="対象 (target):").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.var_target = tk.StringVar(value=str(DEFAULT_TARGET_DIR.resolve()))
        ttk.Entry(frame_dirs, textvariable=self.var_target, width=60).grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(frame_dirs, text="参照...", command=lambda: self._browse(self.var_target)).grid(row=0, column=2, padx=4, pady=2)

        # result
        ttk.Label(frame_dirs, text="出力 (result):").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.var_result = tk.StringVar(value=str(DEFAULT_RESULT_DIR.resolve()))
        ttk.Entry(frame_dirs, textvariable=self.var_result, width=60).grid(row=1, column=1, sticky="ew", padx=4, pady=2)
        ttk.Button(frame_dirs, text="参照...", command=lambda: self._browse(self.var_result)).grid(row=1, column=2, padx=4, pady=2)

        frame_dirs.columnconfigure(1, weight=1)

        # --- オプション ---
        frame_opts = ttk.LabelFrame(self, text="オプション")
        frame_opts.pack(fill="x", **pad)

        # リサイズ設定
        frame_resize = ttk.Frame(frame_opts)
        frame_resize.pack(fill="x", padx=4, pady=2)

        ttk.Label(frame_resize, text="最大幅:").pack(side="left")
        self.var_max_w = tk.IntVar(value=RESIZE_MAX_W)
        ttk.Entry(frame_resize, textvariable=self.var_max_w, width=6).pack(side="left", padx=(2, 8))

        ttk.Label(frame_resize, text="最大高:").pack(side="left")
        self.var_max_h = tk.IntVar(value=RESIZE_MAX_H)
        ttk.Entry(frame_resize, textvariable=self.var_max_h, width=6).pack(side="left", padx=(2, 8))

        ttk.Label(frame_resize, text="出力形式:").pack(side="left")
        self.var_format = tk.StringVar(value="JPEG")
        ttk.Combobox(frame_resize, textvariable=self.var_format,
                     values=list(OUTPUT_FORMATS.keys()), state="readonly",
                     width=6).pack(side="left", padx=(2, 8))

        ttk.Label(frame_resize, text="品質:").pack(side="left")
        self.var_quality = tk.IntVar(value=JPEG_QUALITY)
        ttk.Entry(frame_resize, textvariable=self.var_quality, width=4).pack(side="left", padx=(2, 0))

        self.var_noresize = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame_opts, text="リサイズなし（リネーム・再パックのみ）",
                        variable=self.var_noresize).pack(anchor="w", padx=4, pady=2)

        # --- 実行ボタン・プログレスバー ---
        frame_run = ttk.Frame(self)
        frame_run.pack(fill="x", **pad)

        self.btn_run = ttk.Button(frame_run, text="実行", command=self._on_run)
        self.btn_run.pack(side="left")

        self.lbl_status = ttk.Label(frame_run, text="待機中")
        self.lbl_status.pack(side="left", padx=12)

        self.progress = ttk.Progressbar(frame_run, mode="determinate", length=200)
        self.progress.pack(side="right", fill="x", expand=True, padx=4)

        # --- ログ ---
        frame_log = ttk.LabelFrame(self, text="ログ")
        frame_log.pack(fill="both", expand=True, **pad)

        self.txt_log = scrolledtext.ScrolledText(frame_log, height=16, state="disabled",
                                                  font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True, padx=4, pady=4)

        btn_clear = ttk.Button(frame_log, text="ログクリア", command=self._clear_log)
        btn_clear.pack(anchor="e", padx=4, pady=2)

    def _browse(self, var: tk.StringVar):
        d = filedialog.askdirectory(initialdir=var.get())
        if d:
            var.set(d)

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _log(self, msg: str):
        self._msg_queue.put(msg)

    def _poll_queue(self):
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                self.txt_log.configure(state="normal")
                self.txt_log.insert("end", msg + "\n")
                self.txt_log.see("end")
                self.txt_log.configure(state="disabled")
        except queue.Empty:
            pass
        if self._running:
            self.after(100, self._poll_queue)

    def _on_progress(self, current: int, total: int):
        self.progress["maximum"] = total
        self.progress["value"] = current

    def _on_done(self, success: int, total: int):
        self._running = False

        def _finish():
            self._poll_queue()
            self.btn_run.configure(state="normal")
            self.lbl_status.configure(text=f"完了: {success}/{total} ファイル処理済み")
            self._log(f"\n--- 完了: {success} file(s) processed ---")
            self._poll_queue()

        self.after(200, _finish)

    def _on_run(self):
        if self._running:
            return

        target = Path(self.var_target.get())
        result = Path(self.var_result.get())
        temp = target.parent / "tmp"

        if not target.exists():
            messagebox.showerror("エラー", f"対象ディレクトリが存在しません:\n{target}")
            return

        self._running = True
        self.btn_run.configure(state="disabled")
        self.lbl_status.configure(text="処理中...")
        self.progress["value"] = 0
        self._log(f"=== 処理開始 ===")
        self._log(f"対象: {target}")
        self._log(f"出力: {result}")
        max_w = self.var_max_w.get()
        max_h = self.var_max_h.get()
        quality = self.var_quality.get()
        out_format = self.var_format.get()
        self._log(f"リサイズ: {'なし' if self.var_noresize.get() else f'あり (最大 {max_w}x{max_h}, {out_format} 品質 {quality})'}")

        self.after(100, self._poll_queue)

        t = threading.Thread(
            target=process_archives,
            args=(target, result, temp,
                  self.var_noresize.get(),
                  self._log,
                  self._on_progress,
                  self._on_done,
                  max_w, max_h, quality, out_format),
            daemon=True,
        )
        t.start()


if __name__ == "__main__":
    app = App()
    app.mainloop()
