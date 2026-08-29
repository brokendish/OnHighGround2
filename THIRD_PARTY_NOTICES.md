# THIRD-PARTY NOTICES

最終更新: 2026-08-22（Phase 2-D Round 9: Martin imageをimmutable digest pinへ変更）
正本: `docs/third-party-inventory.md` 第5節（本ファイルはそこから導出した要約）

このファイルは、OnHighGround2のリポジトリまたは配布Dockerイメージへ**実際に同梱される**第三者ソフトウェアのnoticeをまとめたものです。CDN経由でエンドユーザーのブラウザが実行時に直接取得するライブラリ（Leaflet等）は、リポジトリにもDockerイメージにも同梱されないため、本ファイルの対象外です（`ATTRIBUTIONS.md`第8節を参照）。

## 1. backend production image（`backend/Dockerfile`）に同梱されるPythonパッケージ

| Package | Version | License (SPDX) | Copyright | 参照 |
|---|---|---|---|---|
| fastapi | 0.104.1 | MIT | © 2018 Sebastián Ramírez | https://github.com/tiangolo/fastapi |
| uvicorn | 0.24.0 | BSD-3-Clause | © 2017-present, Encode OSS Ltd. | https://github.com/encode/uvicorn |
| rasterio | 1.4.3 | BSD-3-Clause | © 2013, Mapbox | https://github.com/rasterio/rasterio |
| numpy | >=1.26,<2 | BSD-3-Clause（一部0BSD/MIT/Zlib/CC0-1.0のvendored構成要素を含む） | © NumPy Developers | https://github.com/numpy/numpy |
| python-multipart | 0.0.6 | Apache-2.0 | © Andrew Dunham / Marcelo Trylesinski | https://github.com/Kludex/python-multipart |
| pydantic | 2.5.0 | MIT | © 2017 to present Pydantic Services Inc. and individual contributors | https://github.com/pydantic/pydantic |
| shapely | >=2.0,<3 | BSD-3-Clause | © 2007, Sean C. Gillies | https://github.com/shapely/shapely |
| pyproj | >=3.6,<4 | MIT | © 2006-present, PyProj contributors | https://github.com/pyproj4/pyproj |
| ijson | >=3.2,<4 | BSD-3-Clause AND ISC | © Ivan Sagalaev and contributors | https://github.com/ICRAR/ijson |
| websockets | >=10.4 | BSD-3-Clause | © Aymeric Augustin and contributors | https://github.com/python-websockets/websockets |
| astral | >=3.2 | Apache-2.0 | © Simon Kennedy | https://github.com/sffjunkie/astral |
| Pillow | >=10.0,<12 | MIT-CMU | © Jeffrey A. Clark and contributors | https://github.com/python-pillow/Pillow |

上記いずれも許容ライセンス（MIT/BSD/Apache-2.0/ISC相当）であり、AGPL等の強いcopyleftは検出されていない。ライセンス全文はPyPI配布物内、または各GitHubリポジトリの`LICENSE`ファイルを参照。

`pytest`・`httpx`は`requirements-dev.txt`のみに記載され、production image（`backend/Dockerfile`）のビルドには使用しない（開発・テスト専用）。

## 2. Dockerベースイメージ

| Image | Governance |
|---|---|
| `python:3.11-slim` | Debian Projectベースの公式イメージ。単一のSPDX識別子はなく、含まれるOSパッケージ群がGPL/LGPL/MIT/BSD等混在。Python本体はPSF License。 |
| `debian:bookworm-slim`（`streamer/Dockerfile`のみ、`--profile streamer`時のみ使用） | 同上。追加でapt installする`chromium`・`ffmpeg`・`fonts-noto-cjk`等はDebian公式リポジトリのパッケージであり、本プロジェクトはソースの改変・再頒布を行わない。 |
| `osrm/osrm-backend:latest` | BSD-2-Clause（Project OSRM）。https://github.com/Project-OSRM/osrm-backend/blob/master/LICENSE.TXT |
| `nginx:alpine` | nginx独自の2条項BSD類似license。Alpineベースパッケージ群はMIT/BSD/Apache混在。 |
| `ghcr.io/maplibre/martin:1.14.0@sha256:fe5e8952312ca8ea0a25c4b1f72ceb13676f2b50dca310843e48b31c8ceb2264` | デュアルライセンス（MIT OR Apache-2.0）。https://github.com/maplibre/martin |

これらはDocker Hub / GHCR から取得するプレビルド済みイメージであり、リポジトリへソースコードとして同梱されるものではない。イメージ自体を再配布する場合は、各イメージの配布元が定めるnotice義務（該当する場合）に従うこと。

## 3. 同梱していない第三者ソフトウェア（参考情報）

以下はOnHighGround2が**使用するが同梱しない**ソフトウェアである。エンドユーザーのブラウザがCDN（unpkg.com / fonts.googleapis.com）から実行時に直接取得するため、本プロジェクトのリポジトリにもDockerイメージにも含まれない。

| Library | Version | License |
|---|---|---|
| Leaflet | 1.9.4 | BSD-2-Clause |
| Leaflet.markercluster | 1.5.3 | MIT |
| Leaflet Routing Machine | 3.2.12 | ISC |
| Leaflet.VectorGrid | 1.3.0 | "Beerware"（継続利用、OWNER承認済み。完全notice全文は下記3.1節） |
| protomaps-leaflet | 4.1.1 | BSD-3-Clause |
| Google Fonts（Zen Kaku Gothic New, Share Tech Mono） | — | SIL Open Font License 1.1（`docs/third-party-inventory.md`CDN-GFONTS参照、2026-08-21確認済み） |

### 3.1 Leaflet.VectorGrid — 完全license notice（Round 2、"Beerware"）

OWNER判断（Round 2 remediation指示書第0節・第8節）により`leaflet.vectorgrid@1.3.0`は継続利用する。upstream repositoryの`README.md`「Legalese」節にある正式license全文を、著作権表示を含めてそのまま保持する。

- **Package名**: `leaflet.vectorgrid`
- **Exact version**: `1.3.0`
- **Runtime CDN URL**: `https://unpkg.com/leaflet.vectorgrid@1.3.0/dist/Leaflet.VectorGrid.bundled.js`（`frontend/index.html`が参照。リポジトリ・Dockerイメージへは非同梱、エンドユーザーのブラウザがunpkg.comから実行時に直接取得する）
- **Upstream URL**: `https://github.com/Leaflet/Leaflet.VectorGrid`
- **Exact notice全文**（2026-08-21、upstream `README.md`の「Legalese」節より逐語確認、`https://raw.githubusercontent.com/Leaflet/Leaflet.VectorGrid/master/README.md`）:

```text
"THE BEER-WARE LICENSE":
<ivan@sanchezortega.es> wrote this file. As long as you retain this notice you
can do whatever you want with this stuff. If we meet some day, and you think
this stuff is worth it, you can buy me a beer in return.
```

- **同梱形態**: runtime-only（CDN経由）。本リポジトリのソースにもビルド済みDockerイメージにも当該パッケージのソースコード自体は同梱されない。CDN配信物自体にnotice fileが同梱されていないことは、本notice記載を省略する理由にはならないため、本ファイルへ全文を保持する。
- **Notice確認日**: 2026-08-21

## 4. AGPL/強いcopyleft/ライセンス不明の検出結果

本Phaseの機械的・目視監査の範囲では、application-layer（backend Pythonパッケージ、フロントエンドで直接使用するライブラリ、公式基盤イメージのプロジェクト自身のコード部分）にAGPL/GPL等の強いcopyleftライセンスは検出されなかった。

例外として明示するもの:
- `leaflet.vectorgrid@1.3.0`の"Beerware"licenseは非標準だが、OWNER承認により継続利用する（上記3.1節に完全notice全文を保持）。
- `streamer/Dockerfile`がインストールするDebianパッケージ（`ffmpeg`含む）は、Debian配布物の性質上GPL/LGPL系コンポーネントを含み得るが、これは標準的なOSパッケージマネージャ経由のインストールであり、本プロジェクトが追加でソースやNOTICEを同梱すべき「vendoring」には該当しないと判断する。streamer imageを外部へ配布する場合は、この判断をOWNERが再確認すること。

## 5. 確認日

2026-08-21時点でPyPI・npm registry・各GitHubリポジトリのLICENSEファイルを直接確認した。
