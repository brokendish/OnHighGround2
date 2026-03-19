# data_runtime/manifests/ — 配備マニフェスト

このディレクトリには、`scripts/publish/deploy_to_runtime.sh` が生成する配備ログ・マニフェストを置く。

## ファイル形式

| ファイル | 内容 |
|---|---|
| `deploy_YYYYMMDD_HHMMSS.log` | deploy 実行ログ（タイムスタンプ付き） |
| `latest.json` | 最新の配備状態（配備済みファイル一覧 + ハッシュ） |

## 目的

- どのデータが `data_runtime/` に配備されているかを追跡する
- 配備漏れや古いデータの検出に使う
- CI/CD での配備検証の入力として使用できる

## 注意

- このディレクトリ自体は git 管理するが、生成される `.log` / `latest.json` は gitignore 対象とする
- 手動で編集しない
