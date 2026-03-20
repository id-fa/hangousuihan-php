#!/usr/bin/env python3
"""
hangousuihan - Python版
画像アーカイブ（ZIP, 7Z, RAR, LZH）を展開・画像リサイズ・再パッケージ
外部ツール不要（RAR展開時のみunrar DLLが必要）

Usage:
    python hangousuihan.py          # リサイズあり（最大1920x1920px）
    python hangousuihan.py 1        # リサイズなし（リネーム・再パックのみ）
"""

import os
import re
import shutil
import sys
import unicodedata
import zipfile
from pathlib import Path
from typing import Iterator

from PIL import Image

# --- 設定 ---
TEMP_DIR = Path("./tmp")
TARGET_DIR = Path("./target")
RESULT_DIR = Path("./result")
RESIZE_MAX_W = 1920
RESIZE_MAX_H = 1920
JPEG_QUALITY = 90

ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".lzh"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def main() -> None:
    TARGET_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    RESULT_DIR.mkdir(exist_ok=True)

    noresize = len(sys.argv) > 1 and sys.argv[1] == "1"

    archives = [
        f for f in sorted(TARGET_DIR.iterdir())
        if f.is_file() and f.suffix.lower() in ARCHIVE_EXTS
    ]

    if not archives:
        sys.exit(f"error: no archive files found in {TARGET_DIR} (supported: {', '.join(ARCHIVE_EXTS)})")

    success = 0

    for f in archives:
        if "_new." in f.name:
            continue

        stat_mtime = f.stat().st_mtime

        renameto = (
            f.stem + ".zip" if noresize
            else f.stem + "_new.zip"
        )
        renameto = safe_filename(renameto)

        # 一時ディレクトリクリア
        echo_line(f"> rm -rf {TEMP_DIR}")
        rm_rf(TEMP_DIR, leave_folder=True)

        # アーカイブ展開
        echo_line(f"> extract {f}")
        if not extract_archive(f, TEMP_DIR):
            echo_line(f"! extract failed: {f}")
            continue

        # 書庫内書庫展開
        for f2 in recursive_files(TEMP_DIR):
            if f2["size"] > 0 and f2["path"].suffix.lower() in ARCHIVE_EXTS:
                f2_dir = safe_filename(f2["path"].stem)
                has_root = archive_contains_root_dir(f2["path"], f2_dir)

                if has_root:
                    extract_to = TEMP_DIR
                else:
                    extract_to = TEMP_DIR / f2_dir
                    extract_to.mkdir(parents=True, exist_ok=True)

                echo_line(f"> extract nested {f2['path']}")
                extract_archive(f2["path"], extract_to)

                f2["path"].unlink()
                echo_line(f"> rm {f2['path']}")

        # リサイズとリネーム
        unlink_dirs: set[str] = set()

        for f2 in recursive_files(TEMP_DIR):
            if f2["size"] <= 0 or f2["path"].suffix.lower() not in IMAGE_EXTS:
                continue

            p = f2["path"]
            safe_dir = Path(safe_filename(str(p.parent), include_sep=False))
            safe_base = safe_filename(p.stem)

            if str(p.parent) != str(safe_dir):
                if not safe_dir.exists():
                    safe_dir.mkdir(parents=True, exist_ok=True)
                    unlink_dirs.add(str(p.parent))

            if not noresize:
                convert_to = safe_dir / (safe_base + "_new.jpg")
                echo_line(f"> resize {p}")
                ok = resize_image(p, convert_to)

                if ok and convert_to.exists() and convert_to.stat().st_size > 0:
                    os.utime(convert_to, (f2["mtime"], f2["mtime"]))
                    echo_line(f"> rm {p}")
                    p.unlink()
                else:
                    rename_if_needed(p, safe_dir, safe_base)
            else:
                rename_if_needed(p, safe_dir, safe_base)

        # 空になった元ディレクトリを削除
        for ud in unlink_dirs:
            try:
                os.rmdir(ud)
            except OSError:
                pass

        # ZIP再パック（無圧縮）
        result_path = RESULT_DIR / renameto
        if result_path.exists():
            result_path.unlink()

        echo_line(f"> pack {result_path}")
        create_zip(TEMP_DIR, result_path)
        os.utime(result_path, (stat_mtime, stat_mtime))

        success += 1

    # 後片付け
    echo_line(f"> rm -rf {TEMP_DIR}")
    rm_rf(TEMP_DIR, leave_folder=True)

    print(f"{success} file(s) processed.", flush=True)


# ============================================================
# アーカイブ操作
# ============================================================

def extract_archive(path: Path, dest: Path) -> bool:
    """アーカイブを形式に応じて展開"""
    ext = path.suffix.lower()
    try:
        if ext == ".zip":
            return _extract_zip(path, dest)
        elif ext == ".7z":
            return _extract_7z(path, dest)
        elif ext == ".rar":
            return _extract_rar(path, dest)
        elif ext == ".lzh":
            return _extract_lzh(path, dest)
    except Exception as e:
        echo_line(f"! error extracting {path}: {e}")
    return False


def _extract_zip(path: Path, dest: Path) -> bool:
    with zipfile.ZipFile(path, "r") as zf:
        zf.extractall(dest)
    return True


def _extract_7z(path: Path, dest: Path) -> bool:
    import py7zr
    with py7zr.SevenZipFile(path, mode="r") as sz:
        sz.extractall(path=dest)
    return True


def _extract_rar(path: Path, dest: Path) -> bool:
    import rarfile
    with rarfile.RarFile(path, "r") as rf:
        rf.extractall(dest)
    return True


def _extract_lzh(path: Path, dest: Path) -> bool:
    import lhafile
    lha = lhafile.Lhafile(str(path))
    for info in lha.infolist():
        # ディレクトリエントリはスキップ
        if info.filename.endswith("/") or info.filename.endswith("\\"):
            continue
        out_path = dest / info.filename.replace("\\", "/")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(lha.read(info.filename))
    return True


def archive_contains_root_dir(path: Path, dir_name: str) -> bool:
    """アーカイブ内にdir_name/で始まるエントリがあるか確認"""
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
    """ディレクトリ内容からZIPアーカイブを作成（無圧縮、mtime保持）"""
    base = source_dir.resolve()
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_STORED) as zf:
        for f in recursive_files(source_dir):
            p = f["path"]
            arcname = str(p.resolve().relative_to(base))
            info = zipfile.ZipInfo.from_file(p, arcname)
            info.compress_type = zipfile.ZIP_STORED
            with open(p, "rb") as fh:
                zf.writestr(info, fh.read())


# ============================================================
# 画像処理
# ============================================================

def resize_image(src: Path, dest: Path) -> bool:
    """Pillowで画像リサイズしてJPEG保存"""
    try:
        with Image.open(src) as img:
            img = img.convert("RGB")
            w, h = img.size

            if w > RESIZE_MAX_W or h > RESIZE_MAX_H:
                ratio = min(RESIZE_MAX_W / w, RESIZE_MAX_H / h)
                new_w = round(w * ratio)
                new_h = round(h * ratio)
                img = img.resize((new_w, new_h), Image.LANCZOS)

            img.save(dest, "JPEG", quality=JPEG_QUALITY)
        return True
    except Exception as e:
        echo_line(f"! resize failed: {src}: {e}")
        return False


# ============================================================
# ファイル名安全化
# ============================================================

def safe_filename(s: str, include_sep: bool = True) -> str:
    """ファイル名の安全化（PHP版と同等のロジック）"""
    # _uXXXX エスケープシーケンス展開
    if "_u" in s:
        s = re.sub(
            r"_u([0-9a-f]{4})",
            lambda m: chr(int(m.group(1), 16)),
            s,
        )

    # 特殊文字置換
    replacements = {
        "\u2013": "-",       # en-dash→hyphen
        "\u301C": "\uFF5E",  # 波ダッシュ→全角チルダ
        "\u2661": "\u25BD",  # ♡→▽
        "\u2665": "\u25BC",  # ♥→▼
    }
    for old, new in replacements.items():
        s = s.replace(old, new)

    # サロゲートペア合成 (Unicode正規化)
    s = unicodedata.normalize("NFC", s)

    # 絵文字除去（U+10000以上の文字）
    s = re.sub(
        r"[\U00010000-\U0010FFFF]",
        "\u25C6",  # ◆
        s,
    )

    # CP932往復変換でUnicode文字を安全な文字に置換
    try:
        tmp = s.encode("cp932", errors="replace")
        s = tmp.decode("cp932")
        s = s.replace("?", "_")
    except Exception:
        pass

    # メタ文字全角化
    meta_map = {
        "?": "\uFF1F",  # ？
        "*": "\uFF0A",  # ＊
        "#": "\uFF03",  # ＃
        ":": "\uFF1A",  # ：
        ";": "\uFF1B",  # ；
        '"': "\u201C",  # "
        "'": "\u2018",  # '
        "`": "\uFF40",  # ｀
        "$": "\uFF04",  # ＄
        "%": "\uFF05",  # ％
        "&": "\uFF06",  # ＆
        "<": "\uFF1C",  # ＜
        ">": "\uFF1E",  # ＞
        "+": "\uFF0B",  # ＋
        ",": "\uFF0C",  # ，
    }

    if include_sep:
        meta_map["/"] = "\uFF0F"   # ／
        meta_map["\\"] = "\uFFE5"  # ￥

    for old, new in meta_map.items():
        s = s.replace(old, new)

    return s


# ============================================================
# ユーティリティ
# ============================================================

def rename_if_needed(path: Path, safe_dir: Path, safe_base: str) -> None:
    """リネームが必要な場合のみリネーム"""
    dest = safe_dir / (safe_base + path.suffix)
    if dest != path:
        echo_line(f"> mv {path} {dest}")
        path.rename(dest)


def recursive_files(path: Path) -> list[dict]:
    """ディレクトリ内のファイルを再帰的に取得"""
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
    """ディレクトリを再帰的に削除（安全チェック付き）"""
    s = str(path)
    if s.startswith("/") or s.startswith("\\"):
        print(f"unsafe rm: {s}")
        return
    if re.match(r"^(?:file://)?/?[a-zA-Z]:/", s):
        print(f"unsafe rm: {s}")
        return
    if ".." in s:
        print(f"unsafe rm: {s}")
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


def echo_line(s: str) -> None:
    print(s, flush=True)


if __name__ == "__main__":
    main()
