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

## 4.1 Web管理画面のlogin / session / shutdown（OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN）

`/admin/`（`http://127.0.0.1:18100/admin/`、またはSSH forward先）を開くと、
未認証の場合は自動的に`/admin/login.html`へ誘導される。`OPERATOR_AUTH_SECRET`
の値（4節のBearer credentialと同一）を入力してログインすると、
server-side in-memory session（TTL 60分、`backend-operator`再起動で全件失効）
が発行され、以後は`ohg_admin_session` cookie（`Secure`・`HttpOnly`・
`SameSite=Strict`・`Path=/admin`）でページ間・reload後も再ログイン不要になる
（従来の「ページごとにBearer tokenを貼り付け直す」運用は不要になった。
既存のBearer経路自体はCLI・自動化向けにそのまま残る）。

state変更API（logout・「管理画面を終了」・既存admin mutation route）は
`X-CSRF-Token` headerも要求する（`SameSite=Strict`との多層防御。値は
`GET /admin/api/session`のresponseから取得し、`operator/frontend-admin/js/admin-shell.js`
が自動付与する）。

画面右上の「管理画面を終了」は、確認dialog後に`POST /admin/api/system/shutdown`
を呼び、`operator-gateway`→`backend-operator`の順に固定2 containerだけを
`docker stop`する（`docker_operation_gateway.py`のallowlistに
`stop:operator-gateway`・`stop:backend-operator`として追加済み。任意
container名をrequestから受け取ることはできない）。再開は引き続き
`docker compose --profile operator up -d`のみ。

## 5. Docker操作のallowlist限定

`backend-operator`は`/var/run/docker.sock`をmountするが、任意のDocker操作を許可するものではない。許可される操作は`backend/app/services/docker_operation_gateway.py`が定義するallowlistに限定される（実装詳細はコード参照、本ドキュメントでは概要のみ記載する）。`backend-public`はDocker socketを一切mountしない。

## 6. data staging / atomic publish / public read-only境界

- `runtime-init`（one-shot、root実行、`network_mode: none`）が`data_runtime/`のlease coordination volumeを起動前に初期化する。
- `backend-operator`は`data_lake/`・`data_runtime/`へ書き込み可能な立場でdataset管理・atomic publishを行う。
- `backend-public`は`data_runtime/`を基本read-only mountし、自身が書き込む運用状態（ログ・reverse geocodeキャッシュ）のみ個別に`rw`で上書きする。

## 7. SSH forward等の一般的接続概念

VPS等のリモート環境でoperator UIへアクセスする場合、`operator-gateway`のhost bindがloopback限定であることを踏まえ、SSHローカルポートフォワード（例: `ssh -L 18100:127.0.0.1:18100 user@vps`）等、リモートホストのloopbackへ安全にトンネルする一般的な接続方法を利用することを想定する。本ドキュメントは特定のVPSホスト名・IP・実運用port番号を記載しない。

SSH forward経由でも、4.1節のWeb login（session cookie + CSRF）は同一に要求される
（「loopback／トンネル経由だから認証不要」という分岐は存在しない）。

OWNER方針として、host上のリバースプロキシ（Caddy等）から`/admin/*`のみを
`operator-gateway`（`127.0.0.1:18100`）へ限定転送する構成も別途検討されている
（このリポジトリのコードは変更せず、host環境固有の設定として追加する想定。
7.1節と同じ「ベースの`docker-compose.yml`は変更しない」原則に従う）。
この構成が適用されるまでは、SSH forwardが唯一の接続経路のままである。

## 7.1 public backend/OSRM を host リバースプロキシから公開する場合

`backend-public`・`osrm-walking` は既定で host port を宣言しない（1節・2節参照）。
host 上で動くリバースプロキシ（systemd 等で稼働する Caddy/nginx で、Docker
コンテナではないもの）から到達させる必要がある場合、host プロセスは Docker
内部 DNS 名を解決できないため、host loopback（`127.0.0.1:<port>`）への限定的な
host publish が必要になる。この場合もベースの `docker-compose.yml` は変更せず、
環境固有の `docker-compose.override.yml`（git 管理外）に `host_ip: 127.0.0.1`
固定の long-form port 宣言を追加する方式を用いる（`0.0.0.0` は使わない）。
具体的な手順は [VPS 起動/再構築チェックリスト](checklists/vps_startup_checklist.md)
4.6 節を参照。`backend-operator` 本体・`operator-gateway` の host publish 範囲
（3節）は、この種の例外の対象に含めない。

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
