# config/

ランタイム設定関連のファイルを置くディレクトリです。

- `runtime-config.template.js` — ブラウザから参照可能なランタイム公開設定の
  envsubst テンプレート（tracked）。frontend コンテナ起動時に
  `scripts/frontend/generate_runtime_config.sh` が `.env` の
  `CARTO_BASEMAP_API_KEY` で置換して配信物を生成する。直接編集・配信はしない。
- `runtime-config.example.js` / `runtime-config.local.js` — レガシー / 上級者向け
  override 経路（`docker-compose.override.yml` と組み合わせて使う）。通常は
  不要。詳細は [docs/configuration.md](../docs/configuration.md) §7.1。

## 通常の設定方法（`.env` だけで完結）

```bash
cp .env.example .env
vi .env   # CARTO_BASEMAP_API_KEY=your_key_here
docker compose up -d frontend
```

## 置いてよいもの / いけないもの

- 置いてよい: 最終的にブラウザから参照可能でも許容される公開設定値
  （例: `CARTO_BASEMAP_API_KEY`）。
- 置いてはいけない: server-side secret。backend / operator / stream の secret は
  `.env` / `.env.operator` / `.env.stream` に置きます（`CARTO_BASEMAP_API_KEY`
  自体は `.env` に置いても browser-visible な公開設定として扱われ、secret には
  なりません）。

詳細は [docs/configuration.md](../docs/configuration.md) を参照してください。

なお `martin.yaml` / `martin.demo.yaml` / `martin-local.yaml` は Martin
タイルサーバーの設定であり、本ディレクトリのランタイム公開設定とは別用途です。
