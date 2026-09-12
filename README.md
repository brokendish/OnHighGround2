# OnHighGround2

OnHighGround2 は、津波・高潮・洪水のリスク時に、より高く安全な場所への
避難経路を見つけるための地図ベースの避難ナビゲーションアプリケーションです。
Google の地図・標高・ルーティングサービスではなく、オープンな地理データと
セルフホストのサービスを利用します。

## 提供する機能

- 標高を考慮した避難先・避難経路の提案
- ハザードレイヤーとハザード状況の表示
- 指定緊急避難場所の情報と地図オーバーレイ
- 気象・地震情報などを含む公開ライブ情報ビュー
- 公開アプリケーション向けの Docker Compose デプロイ

## はじめに

正式なインストール手順は [インストール](docs/installation.md) です。
サポートされる実行モデル、前提条件、public-core の起動、初期確認について
記載しています。`QUICKSTART.md` はリダイレクトのみであり、インストール手順の
唯一の正本を一箇所に保つためのものです。

| 目的 | ドキュメント |
| --- | --- |
| public core のインストールと起動 | [インストール](docs/installation.md) |
| public / operator / streamer の環境ファイル設定 | [設定](docs/configuration.md) |
| 公開用データセットの準備・atomic publish手順 | [データ準備](docs/data-setup.md) |
| privileged な operator サービスの実行 | [Operator セットアップ](docs/operator-setup.md) |
| データ管理画面（`/admin/datasets`）を使う | [データ管理画面 運用ガイド](docs/admin-data-management.md) |
| VPS への初回構築、または既存 VPS の in-place 再構築 | [VPS 起動/再構築チェックリスト](docs/checklists/vps_startup_checklist.md) |
| runtime 切替・publish 後の動作確認 | [runtime cutover チェックリスト](docs/operations/runtime_cutover_checklist.md) |
| メモリ使用量のチューニング | [メモリチューニング](docs/operations/vps_memory_tuning.md) |
| ドキュメント一覧の閲覧 | [ドキュメント索引](docs/README.md) |
| セキュリティ方針と現在の報告窓口の状況 | [SECURITY.md](SECURITY.md) |
| ライセンスと第三者表記 | [LICENSE](LICENSE), [ATTRIBUTIONS.md](ATTRIBUTIONS.md), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [第三者インベントリ](docs/third-party-inventory.md) |

**問題が発生した場合**: まず [VPS 起動/再構築チェックリスト](docs/checklists/vps_startup_checklist.md)
の「6. 既知の問題と注意事項」を確認してください。個別のハザードレイヤーの不具合は
[ハザードレイヤー](docs/hazard_layers.md) を参照してください。

OSM・DEM・ハザード・OSRM・Martin/PostGIS の準備は
[データ準備](docs/data-setup.md) に従ってください。データ無しの smoke 起動を
フルデータのデプロイとして扱わないでください。

## デプロイの役割

- **Public core:** `backend-public` と `frontend` が最小限の公開起動パスです。
  `runtime-init` はその前提として自動的に実行されます。
- **ルーティングとタイル:** OSRM と Martin は準備済みの地理データが必要であり、
  データ無しの smoke パスには含まれません。
- **Operator:** 任意かつ privileged です。既定では無効で、独立した entrypoint・
  network・secret・セットアップガイドを持ちます。公開側の `/admin` は意図的に
  提供していません。
- **Streamer:** 任意でリソースを多く消費し、個別に設定します。専用の secret と
  `streamer` Compose profile が必要です。
- **ブラウザテスト:** Playwright と npm ツールは開発・テスト用ツールであり、
  runtime の要件ではありません。

## Public / Operator の境界

既定の公開 Compose パスは operator profile を起動しません。operator サービスは
`--profile operator` で明示的に有効化する必要があり、loopback 限定の gateway
経由でのみ公開されます。公開側の `/admin` パスを使おうとするのではなく、
[docs/operator-setup.md](docs/operator-setup.md) に従ってください。

## 設定と secret

設定は主に `.env` 1 つで完結します。

```bash
cp .env.example .env
vi .env   # CARTO_BASEMAP_API_KEY=your_key_here
docker compose up -d frontend
```

- **ブラウザから参照可能なランタイム公開設定**（背景地図の
  `CARTO_BASEMAP_API_KEY` など）: `.env` の `CARTO_BASEMAP_API_KEY` に設定
  します。任意設定で、未設定・空文字なら OpenStreetMap へ自動フォールバック
  します。backend secret ではなくブラウザから参照可能な公開設定である点に
  注意してください。
- **server-side secret**（backend / operator / stream）: `.env`（`ODPT_API_KEY`
  等）・`.env.operator`・`.env.stream` を使います。

いずれの実値もコミットしないでください（example にはプレースホルダーのみ）。
詳細は [docs/configuration.md](docs/configuration.md) を参照してください。

## ライセンスと帰属

本プロジェクトは [MIT License](LICENSE) の下でライセンスされています。地理データ・
外部 API・同梱の第三者ソフトウェアはそれぞれ独自の条件があります。
[ATTRIBUTIONS.md](ATTRIBUTIONS.md) と [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
を参照してください。
