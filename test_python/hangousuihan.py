#!/usr/bin/env python3
"""
hangousuihan - Python版
画像アーカイブ（ZIP, 7Z, RAR, LZH）を展開・画像リサイズ・再パッケージ
外部ツール不要（RAR展開時のみunrar DLLが必要）

Usage:
    python hangousuihan.py          # リサイズあり（最大1920x1920px）
    python hangousuihan.py 1        # リサイズなし（リネーム・再パックのみ）
"""

import argparse
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
CONV_DIR = Path("./tmp_conv")
TARGET_DIR = Path("./target")
RESULT_DIR = Path("./result")
RESIZE_MAX_W = 1920
RESIZE_MAX_H = 1920
JPEG_QUALITY = 90

ARCHIVE_EXTS = {".zip", ".7z", ".rar", ".lzh"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}


def _setup_unrar_lib() -> None:
    """UNRAR_LIB_PATH 未設定時、定番の配置場所から UnRAR DLL を探す

    64-bit Python では UnRAR64.dll、32-bit Python では UnRAR.dll を優先する。
    PyInstaller でフリーズされている場合は EXE と同じフォルダおよび _MEIPASS を検索。
    """
    if os.environ.get("UNRAR_LIB_PATH"):
        return
    import struct
    is_64bit = struct.calcsize("P") * 8 == 64
    names = ["UnRAR64.dll", "unrar64.dll", "UnRAR.dll", "unrar.dll"] if is_64bit \
        else ["UnRAR.dll", "unrar.dll"]

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", str(exe_dir)))
        search_dirs = [
            exe_dir,
            exe_dir / "x64",
            exe_dir / "lib",
            exe_dir / "lib" / "x64",
            meipass,
            meipass / "x64",
        ]
    else:
        script_dir = Path(__file__).resolve().parent
        search_dirs = [
            script_dir,
            script_dir / "x64",
            script_dir.parent / "lib",
            script_dir.parent / "lib" / "x64",
        ]
    for d in search_dirs:
        for n in names:
            c = d / n
            if c.exists():
                os.environ["UNRAR_LIB_PATH"] = str(c)
                return


_setup_unrar_lib()


def main() -> None:
    parser = argparse.ArgumentParser(description="hangousuihan - 画像アーカイブ変換ツール")
    parser.add_argument("noresize", nargs="?", default=None,
                        help="1 を指定するとリサイズなし（リネーム・再パックのみ）")
    parser.add_argument("-g", "--grayscale", action="store_true",
                        help="出力画像をグレースケール化する")
    parser.add_argument("-s", "--suffix", default="_new",
                        help="出力ファイル名に付加するサフィックス（デフォルト: _new、空文字で付与なし）")
    parser.add_argument("--no-copy-extra", action="store_true",
                        help="非画像ファイルを出力ZIPに含めない")
    args = parser.parse_args()

    TARGET_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    CONV_DIR.mkdir(exist_ok=True)
    RESULT_DIR.mkdir(exist_ok=True)

    noresize = args.noresize == "1"
    grayscale = args.grayscale
    suffix = args.suffix
    copy_non_image = not args.no_copy_extra

    archives = [
        f for f in sorted(TARGET_DIR.iterdir())
        if f.is_file() and f.suffix.lower() in ARCHIVE_EXTS
    ]

    if not archives:
        sys.exit(f"error: no archive files found in {TARGET_DIR} (supported: {', '.join(ARCHIVE_EXTS)})")

    success = 0

    for f in archives:
        if suffix and (suffix + ".") in f.name:
            continue

        stat_mtime = f.stat().st_mtime

        renameto = f.stem + suffix + ".zip"
        renameto = safe_filename(renameto)

        # 一時ディレクトリクリア
        echo_line(f"> rm -rf {TEMP_DIR}")
        rm_rf(TEMP_DIR, leave_folder=True)
        echo_line(f"> rm -rf {CONV_DIR}")
        rm_rf(CONV_DIR, leave_folder=True)

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

        # リサイズとリネーム → CONV_DIR に出力
        for f2 in recursive_files(TEMP_DIR):
            p = f2["path"]
            rel_parent = p.parent.relative_to(TEMP_DIR)
            safe_rel = Path(safe_filename(str(rel_parent), include_sep=False)) if str(rel_parent) != "." else Path(".")
            conv_dir = CONV_DIR / safe_rel
            is_image = f2["size"] > 0 and p.suffix.lower() in IMAGE_EXTS

            if is_image:
                safe_base = safe_filename(p.stem)
                conv_dir.mkdir(parents=True, exist_ok=True)

                if not noresize:
                    convert_to = conv_dir / (safe_base + suffix + ".jpg")
                    echo_line(f"> resize {p}")
                    ok = resize_image(p, convert_to, grayscale)

                    if ok and convert_to.exists() and convert_to.stat().st_size > 0:
                        os.utime(convert_to, (f2["mtime"], f2["mtime"]))
                    else:
                        # 変換失敗時はコピーのみ
                        copy_to = conv_dir / (safe_base + p.suffix)
                        shutil.copy2(p, copy_to)
                else:
                    copy_to = conv_dir / (safe_base + p.suffix)
                    shutil.copy2(p, copy_to)
            elif copy_non_image and f2["size"] > 0:
                safe_base = safe_filename(p.stem)
                conv_dir.mkdir(parents=True, exist_ok=True)
                copy_to = conv_dir / (safe_base + p.suffix)
                shutil.copy2(p, copy_to)

        # ZIP再パック（無圧縮、CONV_DIRから）
        result_path = RESULT_DIR / renameto
        if result_path.exists():
            result_path.unlink()

        echo_line(f"> pack {result_path}")
        create_zip(CONV_DIR, result_path)
        os.utime(result_path, (stat_mtime, stat_mtime))

        success += 1

    # 後片付け
    echo_line(f"> rm -rf {TEMP_DIR}")
    rm_rf(TEMP_DIR, leave_folder=True)
    echo_line(f"> rm -rf {CONV_DIR}")
    rm_rf(CONV_DIR, leave_folder=True)

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
    from unrar import rarfile
    rf = rarfile.RarFile(str(path))
    rf.extractall(str(dest))
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
            from unrar import rarfile
            rf = rarfile.RarFile(str(path))
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

def resize_image(src: Path, dest: Path, grayscale: bool = False) -> bool:
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

            if grayscale:
                img = img.convert("L").convert("RGB")

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
