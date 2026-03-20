# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**hangousuihan** は、画像アーカイブ（ZIP, 7Z, RAR, LZH）を展開・画像リサイズ・再パッケージするPHP CLIユーティリティ。日本語ファイル名のエンコーディング処理に重点を置いている。

## 実行方法

```bash
# 通常実行（画像リサイズあり、最大1920x1920px）
php hangousuihan.php

# リサイズなし（リネーム・再パックのみ）
php hangousuihan.php 1
```

処理対象ファイルは `./target/` に配置し、結果は `./result/` に出力される。一時ファイルは `./tmp/` に展開される。

## アーキテクチャ

単一ファイル構成（`hangousuihan.php`）。旧`libphp7.inc.php`は廃止済み。

処理フロー: アーカイブ展開 → ネスト書庫展開 → 画像リサイズ＋ファイル名安全化 → ZIP再パック（mtime保持）

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

## 外部依存

- **PHP 8.4+**（mbstring, SPL, intl/Normalizer拡張必須）
- **7z.exe** — アーカイブ展開・作成（`./lib/`またはPATHから検索）
- **magick.exe** (ImageMagick) — 画像リサイズ（`./lib/`またはPATHから検索）

## コード規約

- PHP 8.4、`declare(strict_types=1)`
- グローバル関数ベース（フレームワークなし）
- エンコーディングはUTF-8統一（旧版のCP932分岐は廃止）
- タイムゾーン: Asia/Tokyo
