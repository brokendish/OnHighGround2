# 第三者ソース監査台帳（Third-Party Inventory）

作成: Phase 2-D（GitHub公開前監査）
最終更新: 2026-08-22（Phase 2-D Round 9: Martin imageをimmutable digest pinへ変更、詳細は本節末尾のStatus注記参照）
正本: 本ファイル。`ATTRIBUTIONS.md`・`THIRD_PARTY_NOTICES.md` は本台帳から導出する。

このファイルは `tasks/public-release/phase2d_claude_design_implementation_instruction.md` 第4節の
schemaに従う。空欄・未着手を示す定型プレースホルダー文言・根拠なしの`probably`は置かない。確認できない項目は
`Status = NOT_CONFIRMED` とし、`Owner action` に必要な対応を明記する。

Statusは次のいずれかのみ。

```text
CONFIRMED_REDISTRIBUTABLE
CONFIRMED_RUNTIME_ONLY
CONFIRMED_ATTRIBUTION_REQUIRED
CONDITIONAL
NOT_CONFIRMED
NOT_APPLICABLE
```

---

## 0. 調査方法と限界

- 全項目は2026-08-21に公式URLを直接取得（WebFetch）して確認した。検索結果・第三者blog・学習データ由来の記憶は根拠にしていない。
- `git ls-files` による全800 tracked fileの棚卸しと、`data_lake/raw/README.md`・`data_lake/registry/tokyo_hazard_registry.csv`・各`scripts/download/`・`scripts/extract/`・`scripts/tile_build/`・`backend/app.properties`のコメント・`data/datasets/*/meta.json` を突合した。
- 一部項目（ODPT公式terms、GSI避難所データの免責事項ページ、東京都防災ポータルの利用規約）は公式ページがJavaScript SPAで内容を取得できない、または本ラウンドで到達できなかった。これらは`NOT_CONFIRMED`とし、法的断定はしていない。
- 本台帳はOnHighGround2内部の`tokyo_hazard_registry.csv`と`meta.json`群の間に実際に存在する記載不一致（provider名・source名の食い違い）をそのまま報告している。矛盾を推定で解消していない。

---

## 1. 地図・地理データ

| ID | Name | Provider | Repository paths | Use mode | Upstream URL | Terms URL | License | Redistribution | Modification notice | Required attribution | UI attribution | Repository notice | Checked at | Status | Owner action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GEO-OSM-ROAD | OSM道路ネットワーク（関東主要道路） | OpenStreetMap contributors | `frontend/layers/roads/kanto_roads_main.geojson`, `frontend/layers/roads/kanto_roads_tertiary.geojson` | generated（`scripts/extract/build_road_geojson.py`が`data/kanto-*.osm.pbf`から抽出・フィルタ・整形） | https://download.geofabrik.de/（PBF取得元） | https://www.openstreetmap.org/copyright, https://osmfoundation.org/wiki/Licence/Attribution_Guidelines, https://opendatacommons.org/licenses/odbl/1-0/ | ODbL 1.0（データ）／CC BY-SA（cartography、本用途は非該当） | CONDITIONAL — ODbL上「Produced Work」（帰属のみ）と「Derivative Database」（ODbL share-alike必須）の区別が本件の具体的成果物（フィルタ済みだが構造化されたGeoJSON）に一意に適用できない。OSMF公式ガイドラインは「substantial extraction」をDerivative Databaseとして扱うと明記しており、保守的にはDerivative Database扱いが妥当 | 要（フィルタ・変換した旨の開示が望ましい） | `© OpenStreetMap contributors`＋ODbLライセンスへのlink（OSMF Attribution Guidelines記載の定型文） | **確認できた範囲でUI上に恒常的な地図全体attributionが存在しない**（後述4節参照） | 未整備（本Phaseで新設） | 2026-08-21 | CONDITIONAL | ODbL上の扱い（Derivative Database方式を採用しODbLで当該extractを併せて提供するか、Produced Work整理で足りるかの法的判断）と、地図表示中の恒常的attribution UIの追加要否をOWNERが決定する |
| GEO-OSM-RAIL | OSM鉄道ネットワーク（全国、PMTiles） | OpenStreetMap contributors | `frontend/layers/railways/railways_japan.pmtiles`, `frontend/layers/railways/kanto_railways.geojson`, `frontend/layers/railways/kanto_stations.geojson` | generated（`scripts/tile_build/build_railway_pmtiles.sh`がGeofabrik `japan-latest.osm.pbf`をosmium+tippecanoeで処理） | https://download.geofabrik.de/asia/japan-latest.osm.pbf | 同上 | ODbL 1.0 | CONDITIONAL（GEO-OSM-ROADと同一理由） | 要 | 同上 | 同上（未確認） | 未整備 | 2026-08-21 | CONDITIONAL | 同上 |
| GEO-KSJ-BOUNDARY | 全国市区町村・都道府県境界（行政区域データ） | 国土交通省 国土数値情報（N03、SmartNews `japan-topography`ミラー経由） | `frontend/layers/administrative/*.geojson`（9ファイル：kanagawa/tokyo/chubu/chugoku/hokkaido/kanto/kinki/kyushu_okinawa/shikoku/tohoku） | generated（`scripts/download/download_municipality_boundaries_nationwide.py`が`raw.githubusercontent.com/smartnews-smri/japan-topography`から取得） | https://nlftp.mlit.go.jp/ksj/, https://github.com/smartnews-smri/japan-topography | https://nlftp.mlit.go.jp/ksj/other/agreement.html | PDL1.0（公共データ利用規約第1.0版）。SmartNews側クレジット表記は不要（同リポジトリREADME記載）だが国土数値情報側クレジットは必要 | CONFIRMED_REDISTRIBUTABLE（PDL1.0は編集・加工物の公開を明示的に許容、出典＋加工表示が条件） | 要：`「国土数値情報（○○データ）」（国土交通省）（当該ページのURL）をもとに○○株式会社作成`相当の文言 | `出典：国土交通省国土数値情報ダウンロードサイト（当該ページのURL）` | **実装済み**（`frontend/js/live-stream/live-stream-municipality-boundary.js`が「国土交通省 国土数値情報（行政区域データ）を加工して作成」を付与、コード内コメントで確認）。ただし`/`（frontend/index.html）側で同レイヤーを表示する経路にも同一attributionが出るかは本ラウンドで未確認 | 未整備（`data_lake/raw/README.md`に出典テーブルはあるが正式notice文書ではない） | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | `/`（通常画面）で同boundaryレイヤーを表示する場合、`/live/stream`と同じattribution文言が出ているか確認する |
| GEO-GEOLONIA-COORDS | 市区町村代表座標（緯度経度辞書） | Geolonia（`japanese-addresses`、原データはMLIT・日本郵便・デジタル庁アドレス・ベース・レジストリ） | `frontend/data/municipality_coords.json` | generated（`scripts/generate_municipality_coords.py`が`raw.githubusercontent.com/geolonia/japanese-addresses/master/data/latest.csv`を集計） | https://github.com/geolonia/japanese-addresses | 同リポジトリREADME記載のライセンス節 | CC BY 4.0（データ）。生成scriptはMIT（別レイヤー、非該当） | CONFIRMED_ATTRIBUTION_REQUIRED（CC BY 4.0は改変・再配布可、要帰属＋変更点表示） | 要（集計・変換した旨） | Geolonia CC BY 4.0表記＋原データ提供元（国土交通省・日本郵便・デジタル庁）への言及 | 未確認（内部座標辞書のため直接UI表示なし、地図中心決定等の内部利用） | 未整備 | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | ATTRIBUTIONS.mdへの記載で足りるか、または直接表示に近い機能（地域ジャンプ等）がある場合はUI表示も検討 |
| GEO-GSI-DEM | 数値標高モデル（DEM、標高解析用） | 国土地理院（基盤地図情報 数値標高モデル） | 実体は`data_runtime/backend/elevation/elevation.tif`（**tracked file 0件、`.gitignore`で除外・deploy時生成**） | generated at deploy time、リポジトリへは同梱しない | https://fgd.gsi.go.jp/download/menu.php | https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html, https://www.gsi.go.jp/LAW/2930-index.html | 基盤地図情報は無償提供（地理空間情報活用推進基本法18条2項）。DEM加工物には専用の加工表示文言例あり | CONFIRMED_RUNTIME_ONLY（バイナリ自体はrepositoryに同梱されない。ただしDEM由来の判定結果はUIへ表示されるため、running app側の帰属表示義務は残る） | 要：`「地理院タイル（標高タイル（基盤地図情報数値標高モデル））を加工して作成」`相当の文言 | `出典：国土地理院ウェブサイト　（当該ページのURL）` | 未確認（DEM由来の避難判定・標高表示に対する出典表示がUI上にあるか未検証） | 未整備 | 2026-08-21 | CONDITIONAL | 測量法29条／30条のどちらに該当する使用態様か（申請不要な出典明示のみで足りるか）をOWNERが確認し、running app側のDEM出典表示を追加するか判断する |

---

## 2. ハザード・避難所データ（Round 2で全面訂正）

`data/datasets/{hazard_type}/tokyo/2026-03-21_v1/` 配下は **`meta.json`のみがtracked**（`.gitignore`が`raw/*.geojson`・`normalized/*.geojson`を除外）であり、実ジオメトリはgit配布物に含まれない（HAZ-TSUNAMI・HAZ-SHELTERのみ例外、下記参照）。ただし、これらのハザード判定・表示はrunning app（`/`, `/live`）で実際にユーザーへ提示されるため、running app自体の帰属表示義務・データ根拠の透明性は別途評価する。

**Round 2訂正**: CODEX第1ラウンドがOPEN判定した4件（HAZ-TSUNAMI, HAZ-FLOOD, HAZ-STORM-SURGE, HAZ-LANDSLIDE）について、OWNER決定＋リポジトリ内の一次証拠（正規化scriptの対応フォーマット・出力ファイル名・`backend/app.properties`のコメント）を根拠に一次ソースを確定した。`tokyo_hazard_registry.csv`のTOKYO-TSUNAMI-001行と`data/datasets/landslide/tokyo/2026-03-21_v1/meta.json`は該当行のみ訂正済み（指示書Round 2第2.1節が許可する範囲、registry全体は無変更）。flood/storm_surgeは元々`meta.json`/registryに虚偽記載はなく空虚な自己参照だっただけのため、registry自体は変更せず本inventoryでの正確な記載に留めた。

| ID | Name | Provider（訂正後） | Repository paths | Distribution class | Upstream URL（公式確認済み） | License | Modification notice | Required attribution | Status | Owner action |
|---|---|---|---|---|---|---|---|---|---|---|
| HAZ-TSUNAMI | 津波浸水想定（東京都） | 国土交通省 国土数値情報（A40 津波浸水想定データ） | `frontend/hazard/tsunami_tokyo.geojson`（tracked、legacy配信経路）＋`data_runtime/backend/hazard/tsunami/`（gitignore、実行時生成） | TRACKED | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40.html（2026-08-21 WebFetch確認、page title「国土数値情報｜津波浸水想定データ」） | PDL1.0（公共データ利用規約第1.0版、`https://nlftp.mlit.go.jp/ksj/other/agreement.html`で確認済み） | 要：`「国土数値情報（津波浸水想定データ）」（国土交通省）（当該ページのURL）をもとに作成`相当の文言 | `出典：国土交通省国土数値情報ダウンロードサイト（当該ページのURL）` | CONFIRMED_ATTRIBUTION_REQUIRED | `tokyo_hazard_registry.csv`のprovider訂正は完了。残作業はUI attribution実装のみ（第4節参照） |
| HAZ-FLOOD | 洪水浸水想定（東京都・想定最大規模） | 国土交通省 国土数値情報（A31a/A31b 洪水浸水想定区域データ） | 実ジオメトリはtracked 0件（`.gitignore`除外）。`scripts/normalize/normalize_river_flood.py`・`scripts/merge_flood_geojson.py`がA31a/A31b GML/ZIPの対応実装を持つことを一次証拠とする | RUNTIME_ONLY | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html（2026-08-21 WebFetch確認、page title「国土数値情報｜浸水想定区域データ」、「国土数値情報　洪水浸水想定区域データ（河川単位）」と明記） | PDL1.0（確認済み） | 要 | 同上（KSJ標準文言） | CONFIRMED_ATTRIBUTION_REQUIRED | `data/datasets/flood/**/meta.json`の空虚な自己参照文言（`既存プロジェクト正規化データ`）はPhase 2-D Round 2のscope外として残置（registry/meta.json双方とも虚偽記載ではなく空虚な記載だったため訂正対象外、指示書第2.1節が明示許可する対象に含まれない）。running app側のUI attributionは第4節で対応 |
| HAZ-STORM-SURGE | 高潮浸水想定（東京都） | 国土交通省 国土数値情報（A49 高潮浸水想定区域データ） | 同上（tracked 0件）。`scripts/normalize/normalize_storm_surge.py`がA49対応実装を持つことを一次証拠とする | RUNTIME_ONLY | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A49-2024.html（2026-08-21 WebFetch確認、page title「国土数値情報｜高潮浸水想定区域データ」） | CC BY 4.0（一部都道府県で追加制限ありと公式ページに記載、東京都データが該当するかは個別未確認） | 要 | 同上（KSJ標準文言） | CONFIRMED_ATTRIBUTION_REQUIRED | A49はCC BY 4.0＋都道府県別追加制限の可能性がある旨、他のPDL1.0系KSJデータと異なる点をOWNERへ周知。東京都データ固有の追加制限有無は次ラウンドで確認 |
| HAZ-LANDSLIDE | 土砂災害警戒区域（東京都） | 国土交通省 国土数値情報（A33 土砂災害警戒区域データ） | 同上（tracked 0件）。`data/datasets/landslide/tokyo/2026-03-21_v1/meta.json`を訂正済み（`既存サンプルデータ`→`土砂災害警戒区域データ（国土数値情報A33）`）。`scripts/normalize/normalize_landslide.py`のdocstringがA33 GML構造への対応を明記していることを一次証拠とする | RUNTIME_ONLY | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A33-2019.html（2026-08-21 WebFetch確認、page title「国土数値情報｜土砂災害警戒区域データ」） | PDL1.0（確認済み） | 要 | 同上（KSJ標準文言） | CONFIRMED_ATTRIBUTION_REQUIRED | `meta.json`訂正完了。`backend/app.properties`のコメント（`データ: 国土数値情報 A33`）と整合したことを確認済み |
| HAZ-SHELTER | 指定緊急避難場所（東京都） | 国土地理院（指定緊急避難場所・指定避難所データダウンロードサイト、一次生産者は市区町村） | `data_runtime/backend/shelters/tokyo_emergency_evacuation_sites.geojson`（tracked、Round 2で再取得・再生成済み）＋`tokyo_emergency_evacuation_sites.provenance.json`（tracked、新設） | TRACKED | https://hinanmap.gsi.go.jp/hinanjocp/defaultFtpData/geoJSON/13000_2.geojson（2026-08-21実取得・SHA-256記録済み） | 国土地理院コンテンツ利用規約＋`hinanbasho-menseki.html`利用上の注意（2026-08-21確認）。再配布可否は明文で許可も禁止もされておらず、CONFIRMED_ATTRIBUTION_REQUIREDとして扱う | 要：「最新かつ詳細の状況などは必ず当該市町村にご確認ください。」を含む出典表示 | `出典：国土地理院「指定緊急避難場所・指定避難所データ」` | CONFIRMED_ATTRIBUTION_REQUIRED | 市区町村単位の個別制限は一般規約からは確認できないため、将来的な追加確認をOWNERへ推奨（低優先度）。**重要発見**: GSI都道府県別ファイルの`_1`/`_2`命名は本プロジェクトの既存script前提と実際が逆であることが判明（`scripts/download/download_shelter_gsi_prefecture.sh`ヘッダー参照） |

---

## 3. 外部API（実行時呼び出し、リポジトリへの同梱なし）

| ID | Name | Provider | Repository paths（呼び出し元） | Use mode | Upstream URL | Terms URL | License/Terms | API use | Redistribution（保存・キャッシュ） | Required attribution | UI attribution | Checked at | Status | Owner action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| API-JMA-QUAKE | 地震情報 | 気象庁 | `backend/services/jma_quake_client.py` | runtime API | www.jma.go.jp | https://www.jma.go.jp/jma/kishou/info/coment.html | 公共データ利用規約第1.0版（PDL1.0） | 許可（登録不要と推定されるが本ページはAPI利用条件を明記せず、website contents向け規約） | 許可（出典＋加工表示条件） | `出典：気象庁ホームページ　（当該ページのURL）`／加工時: `気象庁「情報名」（当該ページのURL）を加工して作成` | 未確認（`/live`・`/live/stream`のUI上表示未検証） | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | UI表示の実機確認、およびAPI JSON配信がwebsite利用規約と同一契約か気象庁へ確認 |
| API-JMA-RAIN | 雨雲レーダー・キキクル | 気象庁 | `backend/services/jma_rain_tile_service.py`, `backend/app/services/live_kikikuru_summary_service.py` | runtime API | www.jma.go.jp | 同上 | 同上 | 同上 | 同上 | 同上 | 未確認 | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | 同上 |
| API-JMA-WEATHER | 気象警報・注意報 | 気象庁 | `backend/app/services/jma_weather_adapter.py`, `backend/app/services/live_weather_jma_service.py` | runtime API | www.jma.go.jp | 同上 | 同上 | 同上 | 同上 | 同上 | 未確認 | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | 同上 |
| API-JMA-TSUNAMI-WARN | 津波警報・注意報（JMA XML／P2P fallback） | 気象庁 | `backend/app/services/tsunami_warning_service.py` | runtime API | www.jma.go.jp | 同上 | 同上 | 同上 | 同上 | 同上 | 未確認 | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | 同上 |
| API-JMA-TIDE | 潮位表 | 気象庁 | `scripts/download/download_tide_jma.py`, `backend/services/amedas_client.py` | offline batch fetch＋runtime | www.data.jma.go.jp | 同上 | 同上 | 同上 | 同上 | 同上 | 未確認 | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | 同上 |
| API-OPEN-METEO | 補助気象データ（`/v1/forecast`） | Open-Meteo | `backend/app/services/`配下（live/live-stream気象関連） | runtime API | https://open-meteo.com/ | https://open-meteo.com/en/licence, https://open-meteo.com/en/terms | データ: CC BY 4.0／API利用: 別途terms（無料枠 <10,000回/日） | 許可（無料枠、商用/非商用の区分あり——本アプリの分類はOWNER判断が必要） | 許可（CC BY 4.0、要帰属＋変更明示） | `<a href="https://open-meteo.com/">Weather data by Open-Meteo.com</a>`（必須、データ表示箇所に隣接） | 未確認 | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | (1) UI上に上記link表示があるか確認、(2) 本アプリの利用区分（商用/非商用）をOpen-Meteo terms上どちらに整理するか決定、(3) 標高データ提供元（Copernicus/C3S）の追加attribution要否を確認 |
| API-JARTIC-TRAFFIC | 道路交通量（区間交通量情報） | 国土交通省 道路局（運用: JARTIC） | `backend/app/services/jartic_traffic_service.py`, `backend/app/api/jartic_traffic.py`, `backend/app/services/live_road_traffic_service.py` | runtime API＋サーバー側snapshotキャッシュ（`data_runtime/backend/jartic/latest_traffic.json`, `manifest.json`、**`.gitignore`で除外・未tracked**） | https://www.jartic-open-traffic.org/ | 交通量API機能利用規約v3（2025-05-12施行、国交省道路局、`xROAD交通量API機能利用規約v3.pdf`） | 無償、登録手続きの明記なし、運用者による負荷時アクセス制限あり得る | 明示の保存・再配布禁止条項なし。ただし公開物には引用書式義務あり | 保存・キャッシュ自体を禁じる条項はなし。ただし帰属義務はキャッシュ経由でも消えない | 必須2種：①常時表示: `「このサービスは、交通量API機能を使用していますが、サービスの内容は国土交通省によって保証されたものではありません。」` ②派生物公開時引用: `「交通量API（国土交通省）機能による交通量(参考値)」`（加工時は「を加工して作成」） | **未確認、恐らく未実装**（grep調査で該当文言は`frontend/`に見つからず） | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | 上記2種の必須文言（特に①の常時表示義務）が`/`・`/live`のJARTICレイヤー使用箇所に実装されているかを確認し、未実装なら追加する（本Phaseではfrontend改変を行っていないため、findingとして報告のみ） |
| API-ODPT-TRAIN | 鉄道運行情報 | ODPT（Open Data Platform for Transportation）、鉄道事業者ごとに個別license | `backend/app/api/live_train.py`, `backend/app/services/live_train_service.py`, `backend/app/services/odpt_allowlist.py`（Round 2新設）, `backend/app/services/odpt_allowlist_data.json`（Round 2新設） | runtime API（`ODPT_API_KEY`必須）＋Round 2でsource-controlled allowlist方式を実装 | https://api.odpt.org/api/v4, https://ckan.odpt.org | https://developer.odpt.org/terms（CODEX第1ラウンドで本文確認済み、`forensic_summary.json`参照）。個別事業者licenseはckan.odpt.orgで確認 | ODPT全体は単一licenseではなく事業者ごとに個別。**Round 2でallowlist化**: TokyoMetro＝`公共交通オープンデータ基本ライセンス`（`ckan.odpt.org/organization/tokyometro`、2026-08-21確認）、Toei＝`CC BY 4.0`（`ckan.odpt.org/organization/toei`、2026-08-21確認）。JR-Eastは`公共交通オープンデータチャレンジ限定ライセンス`（`ckan.odpt.org/organization/jreast`確認）のため意図的にallowlist対象外（表示・cache停止） | allowlist登録2事業者のみ許可、未登録operatorはfetch直後にdeny（cache/UI到達前に除外） | allowlist登録operatorのみcache保持。unknown operatorのpayloadは非cache・非保存 | Y（allowlistの`license`フィールドをitemへ付与） | 実装済み（`item["license"]`/`license_terms_url`/`license_confirmed_at`をTrainInfoItemへ付与、UI表示は第4節参照） | 2026-08-21 | CONFIRMED_ATTRIBUTION_REQUIRED | JR-East除外に伴う機能縮小（運行情報の一部事業者非表示）をOWNERへ周知。将来operator追加時は`odpt_allowlist.py`冒頭のコメント手順に従う |

---

## 4. UI attribution 実地確認（`/`, `/live`, `/live/stream`）

### 4.1 Round 1所見の訂正

Round 1は`frontend/index.html`・`frontend/live.html`・`frontend/live/stream.html`本体だけをgrepし、「`L.tileLayer(`呼び出しが0件、attributionControlが0件」と報告した。これは誤りだった。実際には地図初期化は`frontend/js/map.js`（`/`）・`frontend/js/live/live-map.js`（`/live`）・`frontend/js/live-stream/live-stream-map-view.js`（`/live/stream`）という**別JSファイル**で行われており、3画面とも`L.tileLayer(...).addTo(map)`とLeaflet既定の`attributionControl`（右下corner）が既に機能していた（`/live/stream`は`live-stream-municipality-boundary.js`によるKSJ境界attribution追加も既に実装済みだった）。Round 1の調査範囲（HTML本体のみ）が不十分だったことをここに開示する。

### 4.2 Round 2で実装したUI attribution

OWNER承認（Round 2指示書第0節1点目）に基づき、`frontend/index.html`を含む帰属表示修正を実施した。指示書第6.1節の二層構造で実装した。

- **Layer 1（常時確認できるコンパクトな出典導線）**: 各画面のLeaflet `attributionControl`（右下corner、既存のOSM/CARTO表示を削除・重複・非表示にせず維持）へ、新設`frontend/js/attribution-notices.js`経由で国土数値情報（ハザード）・GSI DEM・気象庁の出典を追加。OSM基本地図のattribution文字列自体もODbLへのlinkを含む形へ更新した（3画面の`L.tileLayer`呼び出し）。
- **Layer 2（個別帰属）**: 行政区域境界レイヤー表示時（`/`の`boundary-layers.js`）、JARTIC道路交通量レイヤーON中（`/`の`jartic-traffic-layer.js`、`/live`の`live-road-traffic-layer.js`——layer ON/OFFと連動し、legendタブの開閉状態に関わらず常時表示）、Open-Meteo気象データ表示中（`/live`の`live-weather-ticker.js`、`/live/stream`の`live-stream-weather-widget.js`——plain textからclickable link + CC BY 4.0表記へ変更）、ODPT鉄道運行情報表示中（`/live`の`live-train-panel.js`——corner属性追加＋詳細モーダルへlicense/terms link・無保証案内を追加）。

| 確認対象 | Round 2実装後の結果 |
|---|---|
| `/` attributionControl | OSM(ODbL) + 国土数値情報ハザード + GSI DEM + 気象庁を実装。行政区域境界表示時は追加でKSJ境界加工表示。JARTIC ON時は必須免責文言（MLIT規約第5条1準拠）を実装 |
| `/live` attributionControl | OSM/CARTO(ODbL) + 国土数値情報ハザード + GSI DEM + 気象庁 + Open-Meteo（CC BY 4.0）+ ODPT + JARTIC同等免責文言を実装 |
| `/live/stream` attributionControl | OSM/CARTO(ODbL) + KSJ境界加工表示（既存）+ 国土数値情報ハザード + GSI DEM + 気象庁を実装（中央メイン地図のみ、小画面widgetは既存のOSM/CARTO表示のみで過密表示を回避） |
| 実機検証 | Playwright（`e2e/attribution.spec.js`、新設6 case）で実HTTP・実DOM上のattributionControl文字列を検証、全件PASS。`docker compose`稼働中のproduction相当container（`http://127.0.0.1:8080`）に対しても個別に確認済み |

**残課題**: `/`のJARTIC UIトグル要素（`#toggle-road-traffic`相当）が想定と異なる可能性がありPlaywrightから直接発見できなかったため、E2Eでは`showJarticTrafficLayer()`関数呼び出しで検証した（実UIのbutton/checkbox経由の操作は別途確認が必要）。ODPT/Open-Meteoの`/`（トップ画面）側での表示は、当該データが`/`では表示されない機能のため対象外（`/live`・`/live/stream`側で確認済み）。

---

## 5. ソフトウェア依存関係

### 5.1 Python backend（production image、`backend/Dockerfile`経由で同梱）

| Package | Pinned | SPDX License | Source | Category |
|---|---|---|---|---|
| fastapi | ==0.104.1 | MIT | pypi.org/project/fastapi/0.104.1/ | bundled |
| uvicorn[standard] | ==0.24.0 | BSD-3-Clause | pypi.org/project/uvicorn/0.24.0/ | bundled |
| rasterio | ==1.4.3 | BSD-3-Clause | pypi.org/project/rasterio/1.4.3/ | bundled |
| numpy | >=1.26,<2 | BSD-3-Clause（+ 一部0BSD/MIT/Zlib/CC0-1.0のvendored構成要素） | pypi.org/project/numpy/ | bundled |
| python-multipart | ==0.0.6 | Apache-2.0 | pypi.org/project/python-multipart/0.0.6/ | bundled |
| pydantic | ==2.5.0 | MIT | github.com/pydantic/pydantic (v2.5.0 LICENSE) | bundled |
| shapely | >=2.0,<3 | BSD-3-Clause | pypi.org/project/shapely/ | bundled |
| pyproj | >=3.6,<4 | MIT | pypi.org/project/pyproj/ | bundled |
| ijson | >=3.2,<4 | BSD-3-Clause AND ISC | pypi.org/project/ijson/ | bundled |
| websockets | >=10.4 | BSD-3-Clause | pypi.org/project/websockets/ | bundled |
| astral | >=3.2 | Apache-2.0 | pypi.org/project/astral/ | bundled |
| Pillow | >=10.0,<12 | MIT-CMU | pypi.org/project/Pillow/ | bundled |
| pytest | >=8.0 | MIT | pypi.org/project/pytest/ | dev/test-only（productionイメージへ同梱されない） |
| httpx | >=0.27,<0.28 | BSD-3-Clause | pypi.org/project/httpx/ | dev/test-only |

Copyleft（GPL/AGPL系）0件。全件許容ライセンス（MIT/BSD/Apache-2.0/ISC相当）。

### 5.2 npm devDependency

| Package | SPDX License | Source | Category |
|---|---|---|---|
| @playwright/test ^1.59.0 | Apache-2.0 | registry.npmjs.org, github.com/microsoft/playwright/blob/main/LICENSE | dev/test-only（E2E、frontendはnginx:alpine配信のためnpm installはproduction imageに含まれない） |

### 5.3 フロントエンドCDNライブラリ（unpkg.com / fonts.googleapis.com、リポジトリへ非同梱・非バンドル）

| ID | Library | Version | SPDX License | Source | Notes |
|---|---|---|---|---|---|
| CDN-LEAFLET | leaflet | 1.9.4 | BSD-2-Clause | github.com/Leaflet/Leaflet | CDN-only |
| CDN-MARKERCLUSTER | leaflet.markercluster | 1.5.3 | MIT | github.com/Leaflet/Leaflet.markercluster | CDN-only |
| CDN-ROUTING-MACHINE | leaflet-routing-machine | 3.2.12 | ISC | github.com/perliedman/leaflet-routing-machine (LICENSE.md本文で確認、GitHub自動検出はNOASSERTION表示のため本文照合を優先) | CDN-only |
| CDN-VECTORGRID | leaflet.vectorgrid | 1.3.0 | **"Beerware"（非標準・OSI非認定、継続利用をOWNER承認済み）** | GitHub `README.md`「Legalese」節（`https://raw.githubusercontent.com/Leaflet/Leaflet.VectorGrid/master/README.md`、2026-08-21確認）。完全notice全文は`THIRD_PARTY_NOTICES.md`第3.1節 | CDN-only。Round 2でOWNERが継続利用を承認、完全notice保持で対応済み |
| CDN-PROTOMAPS | protomaps-leaflet | 4.1.1 | BSD-3-Clause | npm registry, github.com/protomaps/protomaps-leaflet | CDN-only（`frontend/live.html`, `frontend/live/stream.html`が使用、当初調査対象4件に含まれていなかった追加発見） |
| CDN-GFONTS | Google Fonts（Zen Kaku Gothic New, Share Tech Mono） | — | SIL Open Font License 1.1（2026-08-21、Google Fonts公式download-list API `https://fonts.google.com/download/list?family=...` のmanifestにOFL.txtが含まれることを両family個別に確認済み。Zen Kaku Gothic New: © 2022 The Zen Kaku Gothic Project Authors。Share Tech Mono: © Carrois Type Design、Reserved Font Name "Share"） | fonts.googleapis.com | CDN-only。`frontend/live/stream.html`が使用 |

いずれもCDN経由でエンドユーザーのブラウザが直接取得し、git repositoryにもDockerイメージにも同梱されない（"used, not bundled"）。`THIRD_PARTY_NOTICES.md`は「実際に同梱される」ものだけを対象とする指示書第7節の定義により、これらはNOTICES対象外だが、透明性のため`ATTRIBUTIONS.md`に「使用しているが同梱していない」ことを明記する。

Status: CDN-LEAFLET/CDN-MARKERCLUSTER/CDN-ROUTING-MACHINE/CDN-PROTOMAPS/CDN-GFONTS = CONFIRMED_RUNTIME_ONLY。CDN-VECTORGRID = CONFIRMED_RUNTIME_ONLY（Round 2でBeerware全文noticeを`THIRD_PARTY_NOTICES.md`へ保持する対応を実施、第9節参照。継続利用はOWNER承認済み）。

### 5.4 Dockerベースイメージ

| Image | 使用箇所 | Governance | Source |
|---|---|---|---|
| python:3.11-slim | `backend/Dockerfile`, `backend/Dockerfile.operator` | 単一SPDXなし（Debianベース、Python本体はPSF License、パッケージ群はGPL/LGPL/MIT/BSD混在） | hub.docker.com/_/python |
| debian:bookworm-slim | `streamer/Dockerfile` | 同上（Debian Project） | hub.docker.com/_/debian |
| osrm/osrm-backend:latest | docker-compose.yml（osrm-driving, osrm-walking） | BSD-2-Clause | github.com/Project-OSRM/osrm-backend/blob/master/LICENSE.TXT |
| nginx:alpine | docker-compose.yml（frontend, operator nginx） | nginx独自の2条項BSD類似license（Alpineパッケージ群はMIT/BSD/Apache混在） | nginx.org, hub.docker.com/_/nginx |
| ghcr.io/maplibre/martin:1.14.0@sha256:fe5e8952312ca8ea0a25c4b1f72ceb13676f2b50dca310843e48b31c8ceb2264 | docker-compose.yml（martin） | デュアルライセンス MIT OR Apache-2.0 | github.com/maplibre/martin（`LICENSE-APACHE`・`LICENSE-MIT`両方確認） |

`streamer/Dockerfile`（`--profile streamer`時のみ起動、既定非起動）はDebian公式APTパッケージとして`chromium`・`ffmpeg`・`fonts-noto-cjk`等を追加インストールする。これらはDebianプロジェクトが提供するOSパッケージであり、本プロジェクトが個別にソースを同梱・改変しているわけではない。ffmpeg・chromiumは一般にGPL/LGPL系コンポーネントを含み得るが、Debian配布物としての標準的な利用形態（apt install）であり、本プロジェクト側で追加のNOTICE同梱義務が生じる vendoring ではないと判断する。streamer imageを外部へ配布（push）する場合は、この判断の再確認をOwner actionとする。

Status: 全件 CONFIRMED_RUNTIME_ONLY（イメージそのものはビルド時に取得され、リポジトリには同梱されない。Copyleft component 0件（application layer）を確認）。

**Martin image pin（Phase 2-D Round 9、P2D-MARTIN-IMAGE-PIN）**: `ghcr.io/maplibre/martin`は`latest`から`1.14.0`のimmutable digest pin（`<repo>:<tag>@sha256:<digest>`形式）へ変更した。`latest`は再現性が無く、公開後に上流が同じtagへ新bytesを無警告で再pushすれば公開版の挙動が予告なく変わり得るため。digestは`docker buildx imagetools inspect`で取得したtag `1.14.0`が指すOCI image index（multi-arch manifest list）自体の値であり、tag文字列からの推測ではない。amd64/arm64双方のplatform-specific imageを実際にpullし、`martin --version`が`1.14.0`を返すことを直接実行して確認済み（AT-17A focused Docker verification、tasks/public-release/github_public_audit_phase2d_claude_implementation.md Round 9節参照）。現在稼働中のproduction `evacuation-navi-martin` containerは1.3.1のまま変更・再起動していない（Composeファイルのtext編集は稼働中containerへ自動反映されない）。productionへの1.14.0適用はPhase 2-Eで別途、AT-17・image inspection・regressionとOWNER再承認を経て実施する。

### 5.5 バンドル画像・アイコン資産

| Path | 推定 | Status | Owner action |
|---|---|---|---|
| `OnHighGround_image.png`, `frontend/OnHighGround_image.png`, `frontend/favicon.ico`, `frontend/icon.png`, `icon.png` | プロジェクト独自のロゴ・アイコン（ファイル名がプロジェクト名そのもの、stock icon library命名規則（`fa-*`, `material-*`, `noun-*`, `flaticon-*`等）に該当しない） | CONDITIONAL | プロジェクトオーナーによる出所の一言確認（独自作成である旨） |
| `tasks/screenshots/kikikuru_*.png`, `tasks/weather_warning_info_tab.png` | 開発中のスクリーンショット（機能名を冠したファイル名） | CONDITIONAL | 同上。加えてこれらは`tasks/`配下でありpublic配布物の対象か要確認（README等から到達しない限りNOT_APPLICABLE寄り） |

---

## 6. カバレッジ集計（指示書第4.3節）

**Round 2訂正**: Round 1では本節に手動集計の数値を記載していたが、CODEX第1ラウンドがAT-14 check 10の分母算定ロジック自体の不備（prose・定義節の`NOT_CONFIRMED`混入）を指摘した。手動の再集計は同種の誤りを繰り返すリスクがあるため、Round 2からは集計を**第8節の機械可読分類サマリーをAT-14 checkerが構造的にparseして算出する値のみ**を正とし、本節への手動転記をやめる。

実行方法と最新の実測値は`tasks/public-release/evidence/phase2d/phase2d_at14_results.json`（`tools/public_release/phase2d_at14_check.py`実行結果）を参照。集計ロジックの詳細は第8節。

---

---

## 7. stop condition一覧（指示書第14節対応、Round 2で更新）

Round 1で報告した7件のうち6件をRound 2で解消した。解消内容と残存1件を以下に記載する。

| # | Round 1時点の状態 | Round 2での対応 | 現在の状態 |
|---|---|---|---|
| 1（HAZ-TSUNAMI源不一致） | tracked dataの再配布根拠なし | OWNER決定（国土数値情報A40）に基づき`tokyo_hazard_registry.csv`の該当行を訂正、A40公式ページ確認済み | **解消**（CONFIRMED_ATTRIBUTION_REQUIRED） |
| 2（HAZ-SHELTER再配布根拠） | tracked dataの再配布根拠なし | GSI公式サイトから都道府県別データを実際に再取得（`13000_2.geojson`、SHA-256記録）、決定的normalizer実装、provenance manifest新設。GSIのcategory番号がプロジェクトの既存前提と逆であることも判明・是正 | **解消**（CONFIRMED_ATTRIBUTION_REQUIRED、市区町村単位の個別制限確認は低優先度で残置） |
| 3（ODPT license不明） | ODPT個別dataset license不明 | ckan.odpt.orgでTokyoMetro（公共交通オープンデータ基本ライセンス）・Toei（CC BY 4.0）を確認、JR-Eastは「公共交通オープンデータチャレンジ限定ライセンス」と判明したため意図的にallowlist対象外。allowlist実装（`backend/app/services/odpt_allowlist.py`）でfail-closed化 | **解消**（CONFIRMED_ATTRIBUTION_REQUIRED。JR-East表示は縮小——機能面の影響として別途記録） |
| 4（UI attribution不足） | UI必須attribution不足 | OWNER承認（Round 2指示書第0節）に基づき`frontend/index.html`を含む3画面へ実装。Playwright実機検証（`e2e/attribution.spec.js`6 case、既存jartic-traffic-layer.spec.js等37 case含め計79 case）で確認 | **解消**（第4節参照） |
| 5（VectorGrid license） | license不明のfont/icon/JSバンドル | OWNER承認（継続利用）に基づき、upstream GitHub README「Legalese」節の完全license全文を`THIRD_PARTY_NOTICES.md`第3.1節へ保持 | **解消**（CONFIRMED_RUNTIME_ONLY） |
| 6（HAZ-FLOOD/STORM-SURGE源） | tracked dataの再配布根拠なし | OWNER決定（A31a/A31b、A49）＋`scripts/normalize/normalize_river_flood.py`・`normalize_storm_surge.py`の一次証拠により`docs/third-party-inventory.md`で正確に記載。実ジオメトリはtracked 0件（registry/meta.json自体は変更対象外、指示書Round 2第2.1節の許可範囲外のため） | **解消**（CONFIRMED_ATTRIBUTION_REQUIRED） |
| 7（HAZ-LANDSLIDE矛盾） | tracked dataの再配布根拠なし | OWNER決定（A33）に基づき`data/datasets/landslide/tokyo/2026-03-21_v1/meta.json`を訂正（`既存サンプルデータ`→`土砂災害警戒区域データ（国土数値情報A33）`）、`backend/app.properties`のコメントと整合確認 | **解消**（CONFIRMED_ATTRIBUTION_REQUIRED） |

### 残存する新規stop condition（Round 2で発見）

| # | 該当条件 | 詳細 | 対応方針 |
|---|---|---|---|
| 8 | AT-17 Docker開始条件未達 | 指示書第1.3節・第13.4節の容量ゲート（availableが104,857,600 KiB以上）が開始時・終了時とも未達成（約98.5〜99.5 GiB） | Docker-dependent scope（image build・public起動・HTTP境界確認）は未実行。非Docker scope（二段clean clone・prohibited content scan・command parity）は実行しPASS済み |
| 9 | AT-17A実機起動未検証 | `docker-compose.demo.yml`・`tests/fixtures/osm_demo/`を新設し`docker compose config`による静的検証はPASSしたが、実際のcontainer起動・OSRM routing・HTTP境界確認は容量ゲートにより未実施 | 容量条件を満たした次ラウンドで実施。設計・fixture・静的config検証は完了 |
| 10 | KSJ A31自動取得不能（構造的制約、finding） | 国土数値情報A31の配布がHTMLフォーム送信を要し、安定した直接download URLが確認できないため、完全自動化した取得scriptを実装できない | `scripts/download/import_river_flood_manual.py`によるfail-closedな手動import方式を実装済み（指示書第11.4節が明示的に許容する対応） |

上記7件はいずれも法的断定を行わず、公式URL・判明事項・不明事項・対応案を記録する技術的コンプライアンス台帳として報告する。専門家（弁護士等）確認が必要な場合がある。

---

## 8. 機械可読分類サマリー（AT-14 checkerの正本、Round 2新設）

指示書Round 2第4.2節への対応。本節の表が`tools/public_release/phase2d_at14_check.py`のcheck 10・および新設の独立check（terms URL・UI mapping・CDN notice・ODPT allowlist）が**構造的にparseする唯一の対象**である。第1〜3節・第5節の narrative tableは根拠・rationaleの提示に用い、判定そのものはこの表を正とする。

列定義:

- `Distribution Class`: `TRACKED`（geometry/ファイル本体がgit管理下）/ `RUNTIME_ONLY`（実行時生成・非tracked）/ `API_ONLY`（外部API呼び出しのみ、保存物なし）/ `CDN_ONLY`（CDN経由でbrowserが直接取得、repo/imageに非同梱）/ `BUNDLED`（Dockerイメージ等へ同梱）/ `REDISTRIBUTED`（加工の上で再配布）/ `NOT_APPLICABLE`
- `Status`: 冒頭の6値のいずれか
- `TermsURL`: 公式terms/利用規約URLが確認済みならY、未確認ならN
- `ReqAttr`: 必須attribution文言が特定済みならY、未特定ならN
- `UIMapping`: 実際にattributionが表示されている画面（`/`, `/live`, `/live/stream`のカンマ区切り）、未実装なら`NONE`、対象外（内部専用データ等）なら`N/A`
- `OwnerAction`: 未解決のOwner action項目が存在すればY、存在しなければN

| ID | DistributionClass | ArtifactClass | Status | TermsURL | ReqAttr | UIMapping | CheckedAt | OwnerAction |
|---|---|---|---|---|---|---|---|---|
| GEO-OSM-ROAD | TRACKED | geo_data | CONDITIONAL | Y | Y | NONE | 2026-08-21 | Y |
| GEO-OSM-RAIL | TRACKED | geo_data | CONDITIONAL | Y | Y | NONE | 2026-08-21 | Y |
| GEO-KSJ-BOUNDARY | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /live/stream | 2026-08-21 | Y |
| GEO-GEOLONIA-COORDS | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | N/A | 2026-08-21 | Y |
| GEO-GSI-DEM | RUNTIME_ONLY | geo_data | CONDITIONAL | Y | Y | NONE | 2026-08-21 | Y |
| HAZ-TSUNAMI | TRACKED | hazard_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| HAZ-FLOOD | RUNTIME_ONLY | hazard_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| HAZ-STORM-SURGE | RUNTIME_ONLY | hazard_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| HAZ-LANDSLIDE | RUNTIME_ONLY | hazard_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| HAZ-SHELTER | TRACKED | hazard_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | / | 2026-08-21 | Y |
| API-JMA-QUAKE | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| API-JMA-RAIN | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| API-JMA-WEATHER | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| API-JMA-TSUNAMI-WARN | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| API-JMA-TIDE | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live,/live/stream | 2026-08-21 | Y |
| API-OPEN-METEO | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /live,/live/stream | 2026-08-21 | Y |
| API-JARTIC-TRAFFIC | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live | 2026-08-21 | Y |
| API-ODPT-TRAIN | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /live | 2026-08-21 | Y |
| CDN-LEAFLET | CDN_ONLY | cdn_library | CONFIRMED_RUNTIME_ONLY | Y | Y | N/A | 2026-08-21 | N |
| CDN-MARKERCLUSTER | CDN_ONLY | cdn_library | CONFIRMED_RUNTIME_ONLY | Y | Y | N/A | 2026-08-21 | N |
| CDN-ROUTING-MACHINE | CDN_ONLY | cdn_library | CONFIRMED_RUNTIME_ONLY | Y | Y | N/A | 2026-08-21 | N |
| CDN-VECTORGRID | CDN_ONLY | cdn_library | CONFIRMED_RUNTIME_ONLY | Y | Y | N/A | 2026-08-21 | N |
| CDN-PROTOMAPS | CDN_ONLY | cdn_library | CONFIRMED_RUNTIME_ONLY | Y | Y | N/A | 2026-08-21 | N |
| CDN-GFONTS | CDN_ONLY | cdn_library | CONFIRMED_RUNTIME_ONLY | Y | Y | N/A | 2026-08-21 | N |

**check 10のFAIL条件（指示書Round 2第4.2節）**: `Status == NOT_CONFIRMED AND DistributionClass IN {TRACKED, BUNDLED, REDISTRIBUTED}`。上記表で該当するのは`HAZ-SHELTER`（TRACKED）のみ（`API-ODPT-TRAIN`はAPI_ONLYのため対象外——ただし独立checkで別途扱う、後述）。`CDN-VECTORGRID`はRound 2でCONFIRMED_RUNTIME_ONLYへ解消済み。

**独立check（check 10とは別のfail-closed判定）**:

- `runtime_terms_url`: DistributionClassが`RUNTIME_ONLY`または`API_ONLY`の行はTermsURL列がYであることを要求。上表は全件Y。
- `runtime_ui_mapping`: Statusが`CONFIRMED_ATTRIBUTION_REQUIRED`の行はUIMapping列が`NONE`でも許容されるが、これは別途「UI attribution未実装」の集計対象としてAT-14が個別に警告する（fail-closedにはしない、指示書第6節のUI実装が別途進行中であるため）。
- `cdn_dependency_complete`: DistributionClassが`CDN_ONLY`の行は、`THIRD_PARTY_NOTICES.md`に「exact version・license・upstream URL・notice確認日」が記載されていることを要求。`CDN-VECTORGRID`はRound 2で`THIRD_PARTY_NOTICES.md`第3.1節へBeerware全文noticeを保持したため、この独立checkはPASSする。
- `odpt_allowlist_mapping`: `API-ODPT-TRAIN`は、実装するODPT allowlist（第7節参照）の全entryにlicense mappingがあることを要求。allowlist未実装の間はFAILする。
- `odpt_unknown_denied`: allowlist外のODPT operatorが表示・cacheされていないことを要求。

本節はRound 2作業の進行に応じて随時更新する（下記の残phase完了後、最終的な値へ収束させる）。
