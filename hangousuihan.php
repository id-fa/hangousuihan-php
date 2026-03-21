<?php
declare(strict_types=1);

// 書庫内画像を抽出してリサイズし再圧縮
// hangousuihan (https://dyama.org/hangousuihan/) がWindows10で動かなくなったので作成
// 2023.01.19 作成
// 2026.03.20 PHP 8.4用にClaude Opus 4.6でrefine

// require: 7z.exe, 7z.dll, magick.exe

// 引数1 : 1 リサイズしない(zipへのリパックとUnicode文字リネームのみ)

if (PHP_VERSION_ID < 80400) {
    die('use php8.4 or later' . PHP_EOL);
}

foreach (['mbstring', 'intl'] as $ext) {
    if (!extension_loaded($ext)) {
        die('required extension not loaded: ' . $ext . PHP_EOL);
    }
}

date_default_timezone_set('Asia/Tokyo');

// --- 設定 ---
const SEVEN_ZIP_EXE = '7z.exe';
const CONVERT_EXE   = 'magick.exe';
const TEMP_DIR      = './tmp/';
const CONV_DIR      = './tmp_conv/';
const TARGET_DIR    = './target/';
const RESULT_DIR    = './result/';
const COPY_NON_IMAGE = true;         // 非画像ファイルも出力ZIPに含める
const DS            = '/';
const RESIZE_MAX    = '1920x1920>';  // リサイズ上限（ImageMagickジオメトリ指定）
const JPEG_QUALITY  = 90;            // JPEG出力品質（1-100）
const GRAYSCALE     = false;         // true: グレースケール化する
const OUTPUT_SUFFIX = '_new';       // 出力ファイル名に付加するサフィックス（空文字で付与なし）

// --- 外部ツール検索 ---
$exe7z      = resolveExe(SEVEN_ZIP_EXE);
$exeConvert = resolveExe(CONVERT_EXE);

// --- ディレクトリ準備 ---
if (!is_dir(TARGET_DIR)) {
    die('target dir ' . TARGET_DIR . ' not found' . PHP_EOL);
}
if (!is_dir(TEMP_DIR)) {
    mkdir(TEMP_DIR, 0777);
}
if (!is_dir(CONV_DIR)) {
    mkdir(CONV_DIR, 0777);
}
if (!is_dir(RESULT_DIR)) {
    mkdir(RESULT_DIR, 0777);
}

// --- 引数処理 ---
$noresize = !empty($argv[1]);

// --- メイン処理 ---
$archives = glob(TARGET_DIR . '{*.zip,*.7z,*.rar,*.lzh}', GLOB_BRACE);
$success = 0;

foreach ($archives as $f) {
    $basename = basename($f);

    // 処理済skip
    if (OUTPUT_SUFFIX !== '' && str_contains($basename, OUTPUT_SUFFIX . '.')) {
        continue;
    }

    $pathinfo = pathinfo($f);
    $statinfo = stat($f);

    $renameto = $pathinfo['filename'] . OUTPUT_SUFFIX . '.zip';
    $renameto = safeFilename($renameto);

    // 一時ディレクトリクリア
    echoLine('> rm -rf ' . TEMP_DIR);
    rmRf(TEMP_DIR, leaveFolder: true);
    echoLine('> rm -rf ' . CONV_DIR);
    rmRf(CONV_DIR, leaveFolder: true);

    // アーカイブ展開
    $cmd = $exe7z . ' x -o"' . TEMP_DIR . '" "' . addslashes($f) . '"';
    echoLine('> ' . $cmd);
    shell_exec($cmd);

    // 書庫内書庫展開
    $files = recursiveFiles(TEMP_DIR);
    foreach ($files as $f2) {
        if ($f2['size'] > 0 && preg_match('/\.(zip|7z|rar|lzh)$/i', $f2['name'])) {
            $path2 = pathinfo($f2['fullpath']);
            $f2Dir = safeFilename($path2['filename']);

            $cmd = $exe7z . ' l "' . $f2['fullpath'] . '"';
            echoLine('> ' . $cmd);
            $shell = shell_exec($cmd);

            if (preg_match('/D\.\.\.\..+\Q' . $f2Dir . '\E/', $shell ?? '')) {
                // リストに書庫名フォルダがある場合そのまま展開
                $cmd = $exe7z . ' x -o"' . TEMP_DIR . '" "' . $f2['fullpath'] . '"';
            } else {
                // リストに書庫名フォルダがない場合書庫名フォルダ作成して展開
                $cmd = $exe7z . ' x -o"' . TEMP_DIR . DS . $f2Dir . '" "' . $f2['fullpath'] . '"';
            }
            echoLine('> ' . $cmd);
            shell_exec($cmd);

            // 元ファイル削除
            unlink($f2['fullpath']);
            echoLine('> rm ' . $f2['fullpath']);
        }
    }

    // リサイズとリネーム → CONV_DIR に出力
    $files = recursiveFiles(TEMP_DIR);

    foreach ($files as $f2) {
        $path2 = pathinfo($f2['fullpath']);
        // TEMP_DIR からの相対パスを算出
        $relDir = ltrim(substr($path2['dirname'], strlen(rtrim(TEMP_DIR, '/'))), '/\\');
        $safeRelDir = $relDir !== '' ? safeFilename($relDir, includeDs: false) : '';
        $convDir = $safeRelDir !== '' ? CONV_DIR . $safeRelDir : rtrim(CONV_DIR, '/');

        $isImage = $f2['size'] > 0 && preg_match('/\.(jpg|jpeg|png)$/i', $f2['name']);

        if ($isImage) {
            $safeBasename = safeFilename($path2['filename']);

            if (!is_dir($convDir)) {
                mkdir($convDir, 0777, true);
            }

            if (!$noresize) {
                $convertTo = $convDir . DS . $safeBasename . OUTPUT_SUFFIX . '.jpg';
                $cmd = $exeConvert . ' "' . $f2['fullpath'] . '"'
                    . (GRAYSCALE ? ' -colorspace Gray' : '')
                    . ' -quality ' . JPEG_QUALITY . ' -resize "' . RESIZE_MAX . '" "' . $convertTo . '"';
                echoLine('> ' . $cmd);
                shell_exec($cmd);

                if (file_exists($convertTo) && filesize($convertTo) > 0) {
                    touch($convertTo, $f2['mtime']);
                } else {
                    // 変換失敗時はコピーのみ
                    $copyTo = $convDir . DS . $safeBasename . '.' . $path2['extension'];
                    copy($f2['fullpath'], $copyTo);
                    touch($copyTo, $f2['mtime']);
                }
            } else {
                $copyTo = $convDir . DS . $safeBasename . '.' . $path2['extension'];
                copy($f2['fullpath'], $copyTo);
                touch($copyTo, $f2['mtime']);
            }
        } elseif (COPY_NON_IMAGE && $f2['size'] > 0) {
            // 非画像ファイルをコピー
            $safeBasename = safeFilename($path2['filename']);
            if (!is_dir($convDir)) {
                mkdir($convDir, 0777, true);
            }
            $copyTo = $convDir . DS . $safeBasename . '.' . $path2['extension'];
            copy($f2['fullpath'], $copyTo);
            touch($copyTo, $f2['mtime']);
        }
    }

    // ZIP再パック（CONV_DIRから）
    $resultPath = RESULT_DIR . $renameto;
    if (file_exists($resultPath)) {
        unlink($resultPath);
    }
    $cmd = $exe7z . ' a "' . $resultPath . '" "' . ensureTrailingSlash(CONV_DIR) . '*" -mx0';
    echoLine('> ' . $cmd);
    shell_exec($cmd);
    touch($resultPath, $statinfo['mtime']);

    $success++;
}

// 後片付け
echoLine('> rm -rf ' . TEMP_DIR);
rmRf(TEMP_DIR, leaveFolder: true);
echoLine('> rm -rf ' . CONV_DIR);
rmRf(CONV_DIR, leaveFolder: true);

echo $success . ' file(s) processed.' . PHP_EOL;

// ============================================================
// 関数定義
// ============================================================

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
 * 実行ファイルのパスを解決
 */
function resolveExe(string $name): string
{
    if (stream_resolve_include_path($name) !== false) {
        return stream_resolve_include_path($name);
    }

    $libPath = './lib';
    $osPath  = getenv('PATH') ?: '';
    set_include_path($libPath . PATH_SEPARATOR . get_include_path() . PATH_SEPARATOR . $osPath);

    $resolved = stream_resolve_include_path($name);
    if ($resolved === false) {
        die($name . ' not found' . PHP_EOL);
    }

    return $resolved;
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
