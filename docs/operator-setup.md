# Operator構成の信頼境界とセットアップ

operator構成は、データセット管理・シミュレーション等の管理者専用機能を提供する。
これはpublic-core installとは別の、privilegedかつoptionalな手順である。実運用の
secret、host、外部公開方針はこのリポジトリに含めない。

## 1. 既定では起動しない

`docker-compose.yml`の`backend-operator`・`operator-gateway`はいずれも`profiles: ["operator"]`が設定されている。`docker compose up`（profile指定なし）では一切起動しない。`.env.operator.example`を確認し、必要なsecretを安全にローカル設定した上で、明示的に次のように指定した場合のみ起動する。

```bash
docker compose --profile operator up -d
```

[docs/installation.md](installation.md)記載のpublic構成の起動手順は、operator profileを一切指定しない。

## 2. public構成とは別entrypoint / image / network

| | public | operator |
|---|---|---|
| backend image | `backend/Dockerfile`（`backend-public`） | `backend/Dockerfile.operator`（`backend-operator`） |
| backend entrypoint | `backend/app_public.py` | `backend/app_operator.py` |
| gateway | `frontend`（nginx、`nginx.conf`） | `operator-gateway`（nginx、`operator/nginx.conf`） |
| frontend静的ファイル | `frontend/` | `operator/frontend-admin/` |
| network | `default` | `operator-internal`, `operator-publish`（`operator-gateway`のみ） |
| Docker socket mount | なし | `backend-operator`のみ（`/var/run/docker.sock`） |

`backend-public`イメージ（`backend/Dockerfile`）はDocker CLI/SDK・データパイプラインツール（osmium-tool, tippecanoe）・admin/simulation/layer_typesモジュールを一切含めない（`backend/Dockerfile.dockerignore`でビルドcontextから除外）。

## 3. host bindはloopback限定

`operator-gateway`のhost publishは`host_ip: 127.0.0.1`にリテラル固定されている（`docker-compose.yml`側で変更不可、変更できるのはport番号のみ）。既定port `18100`は`OPERATOR_HOST_PORT`環境変数で変更できる（`.env.operator`経由、`.env.operator.example`参照）。`backend-operator`自体はhost publishを持たない（`operator-gateway`経由でのみ到達可能）。

## 4. authentication secret必須（fail-closed）

`backend-operator`は`OPERATOR_AUTH_SECRET`が`.env.operator`から未設定・空文字・空白のみで供給された場合、起動時検証で非0 exit codeとなり**起動そのものが失敗する**（`backend/app_operator.py`、Phase 2-B.1で確定済みの契約）。

全operator管理route（`/api/admin/*`, `/api/simulation/*`）は`Authorization: Bearer <OPERATOR_AUTH_SECRETの値>`ヘッダーが必須。token比較はconstant-time（`secrets.compare_digest`）。query/body/form/cookie/別headerからのtoken受理は行わない。`/operator/health`のみ匿名アクセス可（status/roleのみを返す最小liveness）。

秘密の生成・ローテーション手順は`.env.operator.example`のコメントに記載されている（`openssl rand -hex 32`での生成、更新後は`docker compose --profile operator up -d --force-recreate backend-operator`での再起動が必要）。

## 5. Docker操作のallowlist限定

`backend-operator`は`/var/run/docker.sock`をmountするが、任意のDocker操作を許可するものではない。許可される操作は`backend/app/services/docker_operation_gateway.py`が定義するallowlistに限定される（実装詳細はコード参照、本ドキュメントでは概要のみ記載する）。`backend-public`はDocker socketを一切mountしない。

## 6. data staging / atomic publish / public read-only境界

- `runtime-init`（one-shot、root実行、`network_mode: none`）が`data_runtime/`のlease coordination volumeを起動前に初期化する。
- `backend-operator`は`data_lake/`・`data_runtime/`へ書き込み可能な立場でdataset管理・atomic publishを行う。
- `backend-public`は`data_runtime/`を基本read-only mountし、自身が書き込む運用状態（ログ・reverse geocodeキャッシュ）のみ個別に`rw`で上書きする。

## 7. SSH forward等の一般的接続概念

VPS等のリモート環境でoperator UIへアクセスする場合、`operator-gateway`のhost bindがloopback限定であることを踏まえ、SSHローカルポートフォワード（例: `ssh -L 18100:127.0.0.1:18100 user@vps`）等、リモートホストのloopbackへ安全にトンネルする一般的な接続方法を利用することを想定する。本ドキュメントは特定のVPSホスト名・IP・実運用port番号を記載しない。

## 8. デプロイ検証の境界

本ガイドは public な VPS 公開の手順を定めません。ローカル loopback 以外の
アクセスで operator サービスに依存する前に、対象環境でホストの firewall・
リバースプロキシ・IPv4/IPv6 の公開範囲・secret 管理・operator アクセス方針を
検証してください。

## 9. 関連ドキュメント

- [docs/installation.md](installation.md) — public構成の起動手順（operator profileを含まない）
- [docs/configuration.md](configuration.md) — 環境変数・example設定の全体像
- [docs/admin-data-management.md](admin-data-management.md) — `/admin/datasets` の運用手順（本ドキュメントは trust boundary の設計、そちらは日常操作）
- `.env.operator.example` — operator用template（実秘密は含まない）
