# 設定・環境変数の扱い

This document describes configuration files used by the current Compose setup.
For installation order, start with [Installation](installation.md).

## 1. example env ファイル一覧

| ファイル | 対象 | コピー先 | 参照元 |
|---|---|---|---|
| `backend/.env.example` | public backend（backend-public） | リポジトリroot直下の`.env` | `docker-compose.yml`の`backend-public.env_file`（`path: .env`, `required: false`） |
| `.env.operator.example` | operator backend（backend-operator） | リポジトリroot直下の`.env.operator` | `docker-compose.yml`の`backend-operator.env_file`（`path: .env.operator`, `required: false`） |
| `.env.stream.example` | streamer（`--profile streamer`、既定非起動） | リポジトリroot直下の`.env.stream` | `docker-compose.yml`の`streamer.env_file`（`path: .env.stream`, `required: false`） |

いずれも`required: false`のため、ファイルが存在しなくてもcompose自体は起動する（各serviceの起動時検証がfail-closedで必要な秘密の欠如を検出する設計、後述4節）。

## 2. 環境変数の分類（public backendが実際に参照するもの）

`app_public.py`とそこからimportされる各`app/api/*.py`・`app/services/*.py`を対象に、実コードのgrep（`os.environ.get`/`os.getenv`）で洗い出した。

| 変数 | 分類 | secret | 既定値未設定時の挙動 |
|---|---|---|---|
| `ODPT_API_KEY` | public-optional | secret | 鉄道運行情報機能が無効化される（fail-closedで起動停止はしない） |
| `ODPT_API_BASE_URL` | public-optional | non-secret | 既定URLを使用 |
| `ODPT_EXCLUDE_KEYWORDS` | public-optional | non-secret | フィルタなし |
| `JARTIC_TRAFFIC_BASE_URL` | public-optional | non-secret | 既定URLを使用 |
| `JARTIC_TRAFFIC_USE_MOCK` | development-only | non-secret | false（実API呼び出し） |
| `ROAD_TRAFFIC_API_BASE_URL` | public-optional | non-secret | 既定URLを使用 |
| `ROAD_TRAFFIC_USE_MOCK` | development-only | non-secret | false |
| `MARTIN_INTERNAL_URL` | public-optional | non-secret | 既定URLを使用 |
| `OHG2_DATA_RUNTIME_ROOT` | public-optional | non-secret | `data_runtime/`を使用 |
| `APP_PROPERTIES_FILE` | public-optional | non-secret | `backend/app.properties`を使用 |
| `OHG2_DEV_MODE` | development-only | non-secret | 未設定（開発docsは無効のまま） |
| `OHG2_DEV_DOCS_ENABLED` | development-only | non-secret | 同上 |
| `DEV_EARTHQUAKE_PUBLISH` | development-only | non-secret | 未設定（デバッグ公開なし） |
| `DEM_FILE_PATH` | public-required | non-secret | `docker-compose.yml`の`environment:`で`/data_runtime/backend/elevation/elevation.tif`に固定設定（`.env`側での上書きは通常不要） |
| `API_HOST` / `API_PORT` | public-required | non-secret | 同上、compose側で固定設定済み |
| `OHG2_LEASE_TTL_SECONDS` | public-optional | non-secret | compose側で既定30秒 |

`OPERATOR_AUTH_SECRET`・`SIMULATION_REPORT_DIR`・`SIMULATION_SCENARIOS_DIR`・`OHG2_LEASES_GID`等はoperator専用（`backend-operator`・`runtime-init`のみが参照）であり、public backendの起動には関与しない。詳細は[docs/operator-setup.md](operator-setup.md)を参照。

CORS設定（`cors.allow_origins`等）は環境変数ではなく`backend/app.properties`のkey-value形式で設定する（exact-origin allowlist、fail-closed。詳細はコメント参照）。

## 3. example値の方針

- 実秘密は一切使用しない（`ODPT_API_KEY=`は空、コメントで取得方法のみ案内）。
- wildcard origin（`cors.allow_origins=*`等）はexample・既定値のいずれにも含めない。
- production hostname・実VPS IP・private registry credentialは一切記載しない。
- operator secretに弱い固定defaultは置かない（`.env.operator.example`の`OPERATOR_AUTH_SECRET=`は空、`openssl rand -hex 32`等での生成を案内）。
- APIキーが不要なsource（気象庁・国土数値情報等）には、不要なキー欄を設けない。

## 4. missing secret時のfail-closed動作

- `backend-operator`は`OPERATOR_AUTH_SECRET`が未設定・空文字・空白のみの場合、起動時検証で非0 exit codeとなり起動しない（`backend/app_operator.py`）。
- `backend-public`のCORS設定（`cors.allow_origins`）は、値が1件でも構文違反（wildcard・path付き・空白付き等）を含む場合、起動時にfail-closedで停止する（`backend/app_config_properties.py::parse_cors_origins`）。
- `ODPT_API_KEY`未設定は起動停止を伴わない機能単位のoptional欠如として扱われる（上記2節参照）。

## 5. Local secret handling

Create `.env`, `.env.operator`, and `.env.stream` locally only when their
respective optional values are required. Keep them out of Git and limit local
file access according to the host's normal secret-handling policy. The
repository does not provide real secret values or production-host settings.

## 6. Container image pin update policy

release-critical image references are pinned to an explicit version and OCI manifest-list digest in the Compose files and backend Dockerfiles. To update one, choose a reviewed upstream version, obtain its manifest-list digest for the supported architectures, update the version and digest together, then run `docker compose config` and the applicable build/test checks before merge. Do not replace a pin with a floating tag such as `latest` or `alpine`.

## 7. Related documents

- [docs/installation.md](installation.md) — clean cloneからの起動手順
- [docs/operator-setup.md](operator-setup.md) — operator構成の信頼境界
- [SECURITY.md](../SECURITY.md) — security-reporting status and boundary summary
- [ATTRIBUTIONS.md](../ATTRIBUTIONS.md) — 外部APIキーが関連する第三者サービスの利用条件
