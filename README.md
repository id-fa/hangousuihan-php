# hangousuihan-php

[hangousuihan](https://dyama.org/hangousuihan/) の勝手移植版（PHP CLI）です。UNIX版 hangousuihan をベースに、画像アーカイブ（ZIP, 7Z, RAR, LZH）の展開・画像リサイズ・ZIP再パッケージ機能を移植しています。

本家版にあるグレースケール化・回転・反転・レベル補正・各種フィルタ機能は実装されていません。一方、本家版にない独自機能として以下があります:

- ファイル名からSJIS（CP932）にないUnicode文字を除去
- 書庫内書庫（ネスト書庫）をすべて再帰的に展開

## 動作環境

- Windows
- PHP 8.4以上（mbstring, intl 拡張が必要）

## 外部ツールの導入

以下の外部ツールを別途導入する必要があります。

### 7-Zip

- 公式サイト: https://www.7-zip.org/
- WinGetでインストールする場合: `winget install 7zip.7zip`

`7z.exe`, `7z.dll` をPATHの通った場所に配置するか、スクリプトと同階層の `lib/` フォルダに配置してください。

### ImageMagick

- 公式サイト: https://imagemagick.org/
- WinGetでインストールする場合: `winget install ImageMagick.Q8`

`magick.exe` をPATHの通った場所に配置するか、スクリプトと同階層の `lib/` フォルダに配置してください。

## 使い方

1. `target/` フォルダに処理したい書庫ファイルを配置します
2. スクリプトを実行します

```bash
# 通常実行（画像リサイズあり、最大1920x1920px）
php hangousuihan.php

# リサイズなし（リネーム・再パックのみ）
php hangousuihan.php 1
```

3. `result/` フォルダに `_new` 付きのZIPファイルが作成されます

## 設定

`hangousuihan.php` 冒頭の定数でリサイズの挙動を変更できます。

| 定数 | デフォルト値 | 説明 |
|------|-------------|------|
| `RESIZE_MAX` | `1920x1920>` | リサイズ上限。ImageMagickのジオメトリ指定に準拠します。末尾の `>` は元画像がこのサイズより大きい場合のみ縮小することを意味します。例: `1280x1280>`, `3840x2160>` |
| `JPEG_QUALITY` | `90` | JPEG出力品質（1-100）。値が大きいほど高品質・大容量になります |

---

# hangousuihan-php (English)

An unofficial PHP CLI port of [hangousuihan](https://dyama.org/hangousuihan/), based on the UNIX version. It ports the archive extraction, image resizing, filename sanitization, and ZIP repackaging functionality.

Grayscale conversion, rotation, flipping, level adjustment, and various filter features from the original are not implemented. On the other hand, this port includes the following features not found in the original:

- Strips Unicode characters not present in SJIS (CP932) from filenames
- Recursively extracts nested archives (archives within archives)

## Requirements

- Windows
- PHP 8.4 or later (mbstring and intl extensions required)

## External Tools

The following external tools must be installed separately.

### 7-Zip

- Official site: https://www.7-zip.org/
- Install via WinGet: `winget install 7zip.7zip`

Place `7z.exe` and `7z.dll` in a directory on your PATH, or in the `lib/` folder next to the script.

### ImageMagick

- Official site: https://imagemagick.org/
- Install via WinGet: `winget install ImageMagick.Q8`

Place `magick.exe` in a directory on your PATH, or in the `lib/` folder next to the script.

## Usage

1. Place archive files in the `target/` folder
2. Run the script

```bash
# Normal execution (with image resizing, max 1920x1920px)
php hangousuihan.php

# Without resizing (rename and repack only)
php hangousuihan.php 1
```

3. Processed ZIP files with a `_new` suffix will be created in the `result/` folder

## Configuration

You can change the resize behavior by editing the constants at the top of `hangousuihan.php`.

| Constant | Default | Description |
|----------|---------|-------------|
| `RESIZE_MAX` | `1920x1920>` | Maximum resize dimensions. Follows ImageMagick geometry syntax. The trailing `>` means images are only shrunk if they exceed this size. Examples: `1280x1280>`, `3840x2160>` |
| `JPEG_QUALITY` | `90` | JPEG output quality (1-100). Higher values mean better quality but larger file size |
