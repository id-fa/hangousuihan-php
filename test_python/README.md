# hangousuihan (Python版)

画像アーカイブ（ZIP, 7Z, RAR, LZH）を展開・画像リサイズ・再パッケージするCLIツール。

## 必要環境

- Python 3.10+

## セットアップ

```bash
cd test_python
pip install -r requirements.txt
```

### RAR対応（unrar.dll）

RAR形式のアーカイブを処理する場合、別途 **UnRAR DLL** が必要です。

1. [RARLab公式サイト](https://www.rarlab.com/rar_add.htm) から **UnRAR.dll** をダウンロード
2. DLLを以下のいずれかに配置:
   - `hangousuihan.py` と同じディレクトリ
   - PATHが通ったディレクトリ（例: `C:\Windows\System32`）
3. 環境変数を設定（任意の場所に置く場合）:
   ```
   set UNRAR_LIB_PATH=C:\path\to\UnRAR.dll
   ```

※ ZIP, 7Z, LZH のみ使用する場合、unrar.dll は不要です。

## 使い方

処理対象のアーカイブを `./target/` に配置してから実行します。

```bash
# リサイズあり（最大1920x1920px）
python hangousuihan.py

# リサイズなし（リネーム・再パックのみ）
python hangousuihan.py 1
```

結果は `./result/` に出力されます。

## ディレクトリ構成

```
test_python/
├── hangousuihan.py
├── requirements.txt
├── target/          ← 処理対象を配置
├── tmp/             ← 一時展開先（自動作成）
└── result/          ← 処理結果の出力先（自動作成）
```
