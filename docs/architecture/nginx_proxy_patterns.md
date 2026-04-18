# nginx プロキシパターン

## 概要

`frontend` コンテナ（nginx:alpine）はすべてのサービスへのリバースプロキシとして機能する。
このドキュメントは使用しているプロキシパターンとその設計理由、
および VPS デプロイ時に遭遇した落とし穴を記録する。

---

## サービスルーティング一覧

| パスプレフィックス | アップストリーム | 備考 |
|---|---|---|
| `/api/` | `backend:8000` | FastAPI、静的ホスト名 |
| `/osrm/walking/` | `osrm-walking:5001` | OSRM 徒歩ルーティングエンジン |
| `/tiles/` | `martin:3000` | Martin ベクタータイルサーバー |
| `/layers/` | nginx 静的ファイル | GeoJSON を直接配信 |
| `/hazard/` | nginx 静的ファイル | 廃止予定、後方互換のために保持 |
| `/admin/` | nginx 静的ファイル | 管理画面 UI |

---

## 重要パターン：proxy_pass によるプレフィックス除去

### ルール

アップストリームが nginx の location プレフィックスを**含まない**パスを期待する場合は、
`proxy_pass` に**リテラルホスト名**＋**末尾スラッシュ**を使う：

```nginx
location /osrm/walking/ {
    proxy_pass http://osrm-walking:5001/;
}
```

nginx はマッチしたプレフィックス（`/osrm/walking/`）を proxy_pass の URI（`/`）で置き換える。

結果：`/osrm/walking/route/v1/...` → アップストリームは `/route/v1/...` を受け取る

### やってはいけないこと

**proxy_pass のホスト部分に変数を使うとプレフィックスが除去されない：**

```nginx
# NG — 変数を使うと nginx は /osrm/walking/ を除去しない
set $osrm_walking osrm-walking;
proxy_pass http://$osrm_walking:5001/;
# アップストリームは /route/v1/... ではなく /osrm/walking/route/v1/... を受け取る
```

**rewrite + 変数 proxy_pass の組み合わせも不安定：**

```nginx
# NG — proxy_pass に変数を使うと rewrite の結果が反映されないことがある
rewrite ^/osrm/walking/(.*) /$1 break;
proxy_pass http://$osrm_walking:5001;
```

どちらのパターンも `InvalidUrl` エラーを引き起こす
（OSRM が認識できないパスを受け取ると HTTP 400 で
`"URL string malformed close to position 1: \"/\""` を返す）。

### 変数パターンが必要な場合

`resolver 127.0.0.11` と組み合わせた変数パターンは、nginx 起動時に
アップストリームが存在しない場合のホスト名解決失敗を回避するために使う。
その場合、プレフィックス除去は別の方法で対応が必要：

```nginx
# オプション/遅延起動アップストリーム向けパターン（正しいプレフィックス除去付き）
location /osrm/walking/ {
    resolver 127.0.0.11 valid=30s ipv6=off;
    set $upstream "http://osrm-walking:5001";
    # 除去後のパスを変数に格納してから proxy_pass に渡す
    # （高度な設定 — osrm-walking が nginx 起動時に不在の可能性がある場合のみ必要）
}
```

本プロジェクトでは `osrm-walking` が `frontend` サービスの `depends_on` に列挙されているため、
リテラルホスト名パターンで問題ない。

---

## OSRM 徒歩プロキシ設定

```nginx
location /osrm/walking/ {
    proxy_pass http://osrm-walking:5001/;
    proxy_set_header Host $host;
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'GET, OPTIONS' always;
    if ($request_method = 'OPTIONS') { return 204; }
}
```

フロントエンドの JavaScript は `/osrm/walking/route/v1/{profile}/...` にリクエストを送る。
OSRM は `/route/v1/{profile}/...` を期待する。
`proxy_pass` の末尾スラッシュが自動的に置換を行う。

URL 中の `profile` 文字列（`walking`、`foot` など）は OSRM の API レベルでは検証されない。
ルーティングプロファイルはインデックスビルド時（`osrm-extract -p /opt/foot.lua`）に決定される。

---

## osrm-driving：オプションプロファイル

`osrm-driving` は `docker-compose.yml` で `profiles: ["driving"]` として宣言されており、
デフォルトでは起動しない。対応する nginx の location ブロックはコメントアウト済み
（`nginx.conf` 参照）。

車ルーティングを有効にする場合：

```bash
docker compose --profile driving up -d osrm-driving
```

次に nginx の location ブロックを復活させてリロード：

```bash
# nginx.conf のコメントを外す：
# location /osrm/driving/ {
#     proxy_pass http://osrm-driving:5000/;
#     ...
# }
docker compose exec frontend nginx -s reload
```
