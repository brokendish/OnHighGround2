# config/

ローカルのランタイム設定を置くディレクトリです。

- `runtime-config.example.js` — ブラウザから参照可能なランタイム公開設定の
  テンプレート（tracked）。
- `runtime-config.local.js` — 実値を書くこのホスト専用ファイル（**Git 管理外**）。
  `runtime-config.example.js` をコピーして作成します。

```bash
cp config/runtime-config.example.js config/runtime-config.local.js
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up -d frontend
```

## 置いてよいもの / いけないもの

- 置いてよい: 最終的にブラウザから参照可能でも許容される公開設定値
  （例: `CARTO_BASEMAP_API_KEY`）。
- 置いてはいけない: server-side secret。backend / operator / stream の secret は
  `.env` / `.env.operator` / `.env.stream` に置きます。

詳細は [docs/configuration.md](../docs/configuration.md) を参照してください。

なお `martin.yaml` / `martin.demo.yaml` は Martin タイルサーバーの設定であり、
本ディレクトリの用途とは別です。
