# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

[hangousuihan](https://dyama.org/hangousuihan/)（UNIX版）の勝手移植版。画像アーカイブ（ZIP, 7Z, RAR, LZH）を展開・画像リサイズ・再パッケージするユーティリティ。日本語ファイル名のエンコーディング処理に重点を置いている。

本家版との差異:
- **未実装**: グレースケール化、回転、反転、レベル補正、各種フィルタ
- **独自機能**: ファイル名からSJIS（CP932）にないUnicode文字を除去、書庫内書庫（ネスト書庫）の再帰的展開

実装は4バリアント存在する:

| ファイル | 言語 | 対応形式 | 外部ツール |
|---------|------|---------|-----------|
| `hangousuihan.php` | PHP | ZIP/7Z/RAR/LZH | 7z.exe, magick.exe |
| `hangousuihan_standalone_ziponly.php` | PHP | ZIPのみ | 不要（GD + ZipArchive） |
| `test_python/hangousuihan.py` | Python (CLI) | ZIP/7Z/RAR/LZH | 不要（RAR展開時のみunrar DLL） |
| `test_python/hangousuihan-gui.py` | Python (GUI) | ZIP/7Z/RAR/LZH | 不要（RAR展開時のみunrar DLL） |

## 実行方法

### PHP版（メイン）

```bash
# 通常実行（画像リサイズあり、最大1920x1920px）
php hangousuihan.php

# リサイズなし（リネーム・再パックのみ）
php hangousuihan.php 1
```

### PHP版（スタンドアロン・ZIP専用）

```bash
php hangousuihan_standalone_ziponly.php
php hangousuihan_standalone_ziponly.php 1
```

### Python CLI版

```bash
cd test_python
pip install -r requirements.txt
python hangousuihan.py
python hangousuihan.py 1
```

### Python GUI版

```bash
cd test_python
pip install -r requirements.txt
python hangousuihan-gui.py
```

処理対象ファイルは `./target/` に配置し、結果は `./result/` に出力される。一時ファイルは `./tmp/` に展開される。

## アーキテクチャ

処理フロー（全バリアント共通）: アーカイブ展開 → ネスト書庫展開 → 画像リサイズ＋ファイル名安全化 → ZIP再パック（mtime保持）

### PHP版（hangousuihan.php）

単一ファイル構成。旧`libphp7.inc.php`は廃止済み。

主要定数:
- `RESIZE_MAX` — リサイズ上限（ImageMagickジオメトリ指定、デフォルト `1920x1920>`）
- `JPEG_QUALITY` — JPEG出力品質（デフォルト `90`）

主要関数:
- `safeFilename()` — Unicodeエスケープ展開、サロゲートペア合成、絵文字除去、CP932互換チェック、メタ文字全角化
- `renameIfNeeded()` — 安全化後のファイル名が異なる場合のみリネーム
- `recursiveFiles()` — ディレクトリ内ファイル再帰取得
- `rmRf()` — 安全チェック付き再帰削除
- `resolveExe()` — 外部ツールパス解決（`./lib/`およびPATHから検索）
- `echoLine()` — コンソール出力
- `ensureTrailingSlash()` — ディレクトリ末尾スラッシュ保証

### PHP版スタンドアロン（hangousuihan_standalone_ziponly.php）

ZIP専用。7z.exeの代わりにZipArchive、magick.exeの代わりにGD拡張を使用。

### Python CLI版（test_python/hangousuihan.py）

PHP版と同等のロジックをPythonで再実装。Pillow（画像処理）、py7zr（7Z）、rarfile（RAR）、lhafile（LZH）を使用。詳細は `test_python/README.md` を参照。

### Python GUI版（test_python/hangousuihan-gui.py）

CLI版と同等のコアロジックをtkinter GUIで提供。以下の設定をGUI上で変更可能:

- **対象/出力ディレクトリ** — ファイルダイアログで選択
- **リサイズ最大幅・最大高** — デフォルト 1920x1920
- **出力画像形式** — JPEG / PNG / WEBP から選択（デフォルト JPEG）
- **品質** — デフォルト 90（JPEG/WEBPは品質値、PNGは compress_level に変換）
- **リサイズなしモード** — チェックボックスでリネーム・再パックのみに切替
- **処理中断** — 中断ボタンで処理を途中停止可能

処理はワーカースレッドで実行され、ログとプログレスバーでリアルタイム表示。中断は `threading.Event` で制御。

主要構成:
- `OUTPUT_FORMATS` — 出力形式ごとの拡張子・save引数を定義する辞書
- `App` クラス — tkinter.Tk を継承した GUI アプリケーション
- コアロジック関数（`extract_archive`, `resize_image`, `process_archives` 等）はCLI版と共通

## 外部依存

### PHP版（メイン）
- **PHP 8.4+**（mbstring, SPL, intl/Normalizer拡張必須）
- **7z.exe** — アーカイブ展開・作成（`./lib/`またはPATHから検索）
- **magick.exe** (ImageMagick) — 画像リサイズ（`./lib/`またはPATHから検索）

### PHP版スタンドアロン
- **PHP 8.4+**（mbstring, intl, gd, zip拡張必須）

### Python版
- **Python 3.10+**
- `pip install -r test_python/requirements.txt`（Pillow, py7zr, rarfile, lhafile）
- RAR展開時のみ **unrar.dll** が別途必要（詳細は `test_python/README.md`）

## コード規約

- PHP: PHP 8.4、`declare(strict_types=1)`、グローバル関数ベース
- Python: Python 3.10+、型ヒント使用、`pathlib.Path`ベース
- エンコーディングはUTF-8統一
- タイムゾーン: Asia/Tokyo
