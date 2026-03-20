<?php
declare(strict_types=1);

// 書庫内画像を抽出してリサイズし再圧縮（ZIP専用・PHP拡張のみ版）
// 外部ツール不要: GD + ZipArchive で完結

// 引数1 : 1 リサイズしない(zipへのリパックとUnicode文字リネームのみ)

if (PHP_VERSION_ID < 80400) {
    die('use php8.4 or later' . PHP_EOL);
}

foreach (['mbstring', 'intl', 'gd', 'zip'] as $ext) {
    if (!extension_loaded($ext)) {
        die('required extension not loaded: ' . $ext . PHP_EOL);
    }
}

date_default_timezone_set('Asia/Tokyo');

// --- 設定 ---
const TEMP_DIR     = './tmp/';
const TARGET_DIR   = './target/';
const RESULT_DIR   = './result/';
const DS           = '/';
const RESIZE_MAX_W = 1920;
const RESIZE_MAX_H = 1920;
const JPEG_QUALITY = 90;

// --- ディレクトリ準備 ---
if (!is_dir(TARGET_DIR)) {
    die('target dir ' . TARGET_DIR . ' not found' . PHP_EOL);
}
if (!is_dir(TEMP_DIR)) {
    mkdir(TEMP_DIR, 0777);
}
if (!is_dir(RESULT_DIR)) {
    mkdir(RESULT_DIR, 0777);
}

// --- 引数処理 ---
$noresize = !empty($argv[1]);

// --- メイン処理 ---
$archives = glob(TARGET_DIR . '*.zip');
$success = 0;

foreach ($archives as $f) {
    $basename = basename($f);

    // 処理済skip
    if (str_contains($basename, '_new.')) {
        continue;
    }

    $pathinfo = pathinfo($f);
    $statinfo = stat($f);

    $renameto = $noresize
        ? $pathinfo['filename'] . '.zip'
        : $pathinfo['filename'] . '_new.zip';
    $renameto = safeFilename($renameto);

    // 一時ディレクトリクリア
    echoLine('> rm -rf ' . TEMP_DIR);
    rmRf(TEMP_DIR, leaveFolder: true);

    // ZIP展開
    echoLine('> extract ' . $f);
    if (!extractZip($f, TEMP_DIR)) {
        echoLine('! extract failed: ' . $f);
        continue;
    }

    // 書庫内ZIP展開
    $files = recursiveFiles(TEMP_DIR);
    foreach ($files as $f2) {
        if ($f2['size'] > 0 && preg_match('/\.zip$/i', $f2['name'])) {
            $path2 = pathinfo($f2['fullpath']);
            $f2Dir = safeFilename($path2['filename']);

            // ZIP内にアーカイブ名フォルダがあるか確認
            $hasRootDir = zipContainsRootDir($f2['fullpath'], $f2Dir);

            if ($hasRootDir) {
                $extractTo = TEMP_DIR;
            } else {
                $extractTo = TEMP_DIR . DS . $f2Dir;
                if (!is_dir($extractTo)) {
                    mkdir($extractTo, 0777, true);
                }
            }

            echoLine('> extract nested ' . $f2['fullpath']);
            extractZip($f2['fullpath'], $extractTo);

            unlink($f2['fullpath']);
            echoLine('> rm ' . $f2['fullpath']);
        }
    }

    // リサイズとリネーム
    $files = recursiveFiles(TEMP_DIR);
    $unlinkDirs = [];

    foreach ($files as $f2) {
        if ($f2['size'] <= 0 || !preg_match('/\.(jpg|jpeg|png)$/i', $f2['name'])) {
            continue;
        }

        $path2 = pathinfo($f2['fullpath']);
        $safeDirname = safeFilename($path2['dirname'], includeDs: false);
        $safeBasename = safeFilename($path2['filename']);

        // ディレクトリ名が安全でない場合、安全なディレクトリを作成
        if ($path2['dirname'] !== $safeDirname) {
            if (!file_exists($safeDirname)) {
                mkdir($safeDirname, 0777, true);
                $unlinkDirs[$path2['dirname']] = true;
            }
        }

        if (!$noresize) {
            $convertTo = $safeDirname . DS . $safeBasename . '_new.jpg';
            echoLine('> resize ' . $f2['fullpath']);
            $ok = resizeImage($f2['fullpath'], $convertTo, RESIZE_MAX_W, RESIZE_MAX_H, JPEG_QUALITY);

            if ($ok && file_exists($convertTo) && filesize($convertTo) > 0) {
                touch($convertTo, $f2['mtime']);
                echoLine('> rm ' . $f2['fullpath']);
                unlink($f2['fullpath']);
            } else {
                // 変換失敗時はリネームのみ
                renameIfNeeded($path2, $safeDirname, $safeBasename);
            }
        } else {
            renameIfNeeded($path2, $safeDirname, $safeBasename);
        }
    }

    // 空になった元ディレクトリを削除
    foreach (array_keys($unlinkDirs) as $ud) {
        @rmdir($ud);
    }

    // ZIP再パック（無圧縮）
    $resultPath = RESULT_DIR . $renameto;
    if (file_exists($resultPath)) {
        unlink($resultPath);
    }
    echoLine('> pack ' . $resultPath);
    createZip(TEMP_DIR, $resultPath);
    touch($resultPath, $statinfo['mtime']);

    $success++;
}

// 後片付け
echoLine('> rm -rf ' . TEMP_DIR);
rmRf(TEMP_DIR, leaveFolder: true);

echo $success . ' file(s) processed.' . PHP_EOL;

// ============================================================
// 関数定義
// ============================================================

/**
 * ZIPアーカイブを展開
 */
function extractZip(string $zipPath, string $destDir): bool
{
    $zip = new ZipArchive();
    $res = $zip->open($zipPath);
    if ($res !== true) {
        return false;
    }
    $zip->extractTo($destDir);
    $zip->close();
    return true;
}

/**
 * ZIP内にアーカイブ名と同名のルートディレクトリがあるか確認
 */
function zipContainsRootDir(string $zipPath, string $dirName): bool
{
    $zip = new ZipArchive();
    if ($zip->open($zipPath) !== true) {
        return false;
    }
    for ($i = 0; $i < $zip->numFiles; $i++) {
        $entry = $zip->getNameIndex($i);
        if (str_starts_with($entry, $dirName . '/')) {
            $zip->close();
            return true;
        }
    }
    $zip->close();
    return false;
}

/**
 * ディレクトリ内容からZIPアーカイブを作成（無圧縮、mtime保持）
 */
function createZip(string $sourceDir, string $destZip): bool
{
    $zip = new ZipArchive();
    if ($zip->open($destZip, ZipArchive::CREATE | ZipArchive::OVERWRITE) !== true) {
        return false;
    }

    $files = recursiveFiles($sourceDir);
    $baseLen = strlen(rtrim(str_replace('\\', '/', realpath($sourceDir)), '/')) + 1;

    foreach ($files as $f) {
        $realPath = str_replace('\\', '/', realpath($f['fullpath']));
        $localName = substr($realPath, $baseLen);
        $zip->addFile($f['fullpath'], $localName);
        $zip->setCompressionName($localName, ZipArchive::CM_STORE);
        $zip->setMtimeName($localName, $f['mtime']);
    }

    $zip->close();
    return true;
}

/**
 * GDで画像リサイズしてJPEG保存
 */
function resizeImage(string $src, string $dest, int $maxW, int $maxH, int $quality): bool
{
    $info = @getimagesize($src);
    if ($info === false) {
        return false;
    }

    $srcW = $info[0];
    $srcH = $info[1];
    $type = $info[2];

    $img = match ($type) {
        IMAGETYPE_JPEG => @imagecreatefromjpeg($src),
        IMAGETYPE_PNG  => @imagecreatefrompng($src),
        default        => false,
    };

    if ($img === false) {
        return false;
    }

    // リサイズ計算（元画像が上限以下ならそのまま）
    $newW = $srcW;
    $newH = $srcH;

    if ($srcW > $maxW || $srcH > $maxH) {
        $ratioW = $maxW / $srcW;
        $ratioH = $maxH / $srcH;
        $ratio = min($ratioW, $ratioH);
        $newW = (int) round($srcW * $ratio);
        $newH = (int) round($srcH * $ratio);
    }

    if ($newW !== $srcW || $newH !== $srcH) {
        $resized = imagecreatetruecolor($newW, $newH);
        imagecopyresampled($resized, $img, 0, 0, 0, 0, $newW, $newH, $srcW, $srcH);
        imagedestroy($img);
        $img = $resized;
    }

    $result = imagejpeg($img, $dest, $quality);
    imagedestroy($img);

    return $result;
}

/**
 * リネームが必要な場合のみリネーム
 */
function renameIfNeeded(array $path2, string $safeDirname, string $safeBasename): void
{
    $from = $path2['dirname'] . DS . $path2['filename'] . '.' . $path2['extension'];
    $to   = $safeDirname . DS . $safeBasename . '.' . $path2['extension'];
    if ($to !== $from) {
        echoLine('> mv ' . $from . ' ' . $to);
        rename($from, $to);
    }
}

/**
 * ファイル名の安全化
 */
function safeFilename(string $str, bool $includeDs = true): string
{
    // _uXXXX エスケープシーケンス展開
    if (preg_match('/_u[0-9a-f]{4}/', $str)) {
        $str = preg_replace_callback(
            '/_u([0-9a-f]{4})/',
            fn(array $m): string => mb_convert_encoding(pack('H*', $m[1]), 'UTF-8', 'UTF-16'),
            $str,
        );
    }

    // 特殊文字置換
    $str = str_replace(
        ["\xE2\x80\x93", "\xE3\x80\x9C", "\xE2\x99\xA1", "\xE2\x99\xA5"],
        ['-',             "\xEF\xBD\x9E", "\xE2\x96\xBD", "\xE2\x96\xBC"],
        $str,
    ); // en-dash→hyphen, 波ダッシュ→全角チルダ, ♡→▽, ♥→▼

    // サロゲートペア合成 (Unicode正規化)
    $str = \Normalizer::normalize($str, \Normalizer::FORM_C);

    // 絵文字除去 (4バイトUTF-8)
    $str = preg_replace('/[\xF0-\xF7][\x80-\xBF]{3}/', '◆', $str);

    // CP932往復変換でUnicode文字を安全な文字に置換
    $tmp  = mb_convert_encoding($str, 'CP932', 'UTF-8');
    $tmp2 = mb_convert_encoding($tmp, 'UTF-8', 'CP932');
    $str  = str_replace('?', '_', $tmp2);

    // メタ文字全角化
    $search  = ['?', '*', '#', ':', ';', '"', "'", '`', '$', '%', '&', '<', '>', '+', ','];
    $replace = ['？', '＊', '＃', '：', '；', "\u{201C}", "\u{2018}", '｀', '＄', '％', '＆', '＜', '＞', '＋', '，'];

    if ($includeDs) {
        $search[]  = '/';
        $replace[] = '／';
        $search[]  = '\\';
        $replace[] = '￥';
    }

    return str_replace($search, $replace, $str);
}

/**
 * コンソール出力
 */
function echoLine(string $str): void
{
    echo $str . PHP_EOL;
}

/**
 * ディレクトリ末尾にスラッシュを保証
 */
function ensureTrailingSlash(string $dir): string
{
    if ($dir === '') {
        return $dir;
    }
    return str_ends_with($dir, '/') || str_ends_with($dir, '\\')
        ? $dir
        : $dir . '/';
}

/**
 * ディレクトリ内のファイルを再帰的に取得
 */
function recursiveFiles(string $path): array
{
    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator(
            $path,
            FilesystemIterator::SKIP_DOTS
            | FilesystemIterator::KEY_AS_PATHNAME
            | FilesystemIterator::CURRENT_AS_FILEINFO,
        ),
        RecursiveIteratorIterator::LEAVES_ONLY,
    );

    $results = [];
    foreach ($iterator as $f) {
        if (!$f->isFile()) {
            continue;
        }

        $fullpath = str_replace(DIRECTORY_SEPARATOR, DS, $f->getPathname());

        $results[] = [
            'fullpath' => $fullpath,
            'name'     => $f->getFilename(),
            'size'     => $f->getSize(),
            'mtime'    => $f->getMTime(),
        ];
    }

    return $results;
}

/**
 * ディレクトリを再帰的に削除
 */
function rmRf(string $dir, bool $leaveFolder = false): void
{
    // 安全チェック
    if (preg_match('#^[/\\\\]#', $dir)) {
        echo 'unsafe rm: ' . $dir . PHP_EOL;
        return;
    }
    if (preg_match('#^(file://)?/?[a-z]:/#i', $dir)) {
        echo 'unsafe rm: ' . $dir . PHP_EOL;
        return;
    }
    if (str_contains($dir, '..')) {
        echo 'unsafe rm: ' . $dir . PHP_EOL;
        return;
    }

    if (!is_dir($dir)) {
        return;
    }

    $entries = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($dir, RecursiveDirectoryIterator::SKIP_DOTS),
        RecursiveIteratorIterator::CHILD_FIRST,
    );

    foreach ($entries as $entry) {
        $entry->isDir()
            ? rmdir($entry->getRealPath())
            : unlink($entry->getRealPath());
    }

    if (!$leaveFolder) {
        rmdir($dir);
    }
}
