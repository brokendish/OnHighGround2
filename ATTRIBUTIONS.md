# ATTRIBUTIONS

最終更新: 2026-08-21
正本: `docs/third-party-inventory.md`（本ファイルはそこから導出した要約）

## 1. 適用範囲

本ファイルは、OnHighGround2が表示・利用する第三者の地図データ・地理データ・防災データ・気象データ・交通データ・外部APIについて、利用者へ提示すべき出典・帰属・加工表示をまとめたものです。

## 2. プロジェクトコードのライセンスとの分離

OnHighGround2自身のソースコード・ドキュメントは`LICENSE`記載のMIT Licenseです。本ファイルに記載する第三者データ・APIは、それぞれ別の権利者・別のライセンス条件のもとにあり、MIT Licenseの対象ではありません。OnHighGround2はこれらのデータを独自にMIT Licenseへ再ライセンスするものではありません。

## 3. 地図・地理データ

- **OpenStreetMap**（道路・鉄道ネットワーク） — © OpenStreetMap contributors。データはOpen Database License (ODbL) 1.0のもとに提供されています。ライセンス全文: https://opendatacommons.org/licenses/odbl/1-0/ 。本プロジェクトはGeofabrik配布のOSM PBFデータから道路・鉄道網を抽出・フィルタして`frontend/layers/roads/`・`frontend/layers/railways/`のGeoJSON/PMTilesを生成しています。
- **国土数値情報（行政区域データ、国土交通省）** — 出典：国土交通省国土数値情報ダウンロードサイト。`frontend/layers/administrative/`の市区町村・都道府県境界データは、国土数値情報（N03）をもとに加工して作成しています。
- **Geolonia 住所データ**（`japanese-addresses`） — CC BY 4.0。原データは国土交通省・日本郵便・デジタル庁アドレス・ベース・レジストリに由来します。市区町村代表座標（`frontend/data/municipality_coords.json`）の算出に使用しています。
- **国土地理院（数値標高モデル DEM）** — 出典：国土地理院ウェブサイト。標高データは地図表示には同梱されず、避難経路の標高判定に実行時利用しています。
- **CARTO Basemaps**（`/live`・`/live/stream` の背景地図） — © CARTO。ベースタイルは CARTO Basemaps の `dark_all` スタイルを実行時にブラウザが直接取得します（リポジトリ・Docker イメージへは非同梱）。ベースマップのデータは © OpenStreetMap contributors（ODbL 1.0）に由来します。CARTO Basemaps は API キーが必要です（`CARTO_BASEMAP_API_KEY`、各利用者が取得。`docs/configuration.md` 参照）。キー未設定時は OpenStreetMap のラスタタイルへフォールバックします。表示箇所には `© OpenStreetMap contributors (ODbL)` と `© CARTO`（https://carto.com/attributions へのリンク付き）の表示が必要です。

## 4. 防災・ハザードデータ

- 津波浸水想定・洪水浸水想定・高潮浸水想定・土砂災害警戒区域の各レイヤーは、国土数値情報または東京都・国土交通省が公開するハザードマップ関連データをもとに表示しています。**個別データセットの一次ソース確定はPhase 2-Dの時点で未完了の項目があり**、詳細と未解決事項は`docs/third-party-inventory.md`第2節・第7節を参照してください。
- 指定緊急避難場所・指定避難所データは、市区町村が登録し公開に同意したデータを国土地理院・内閣府・消防庁が共同で公開しているものを利用しています。個別の利用条件確認は継続中です（`docs/third-party-inventory.md`HAZ-SHELTER参照）。

## 5. 気象データ

- **気象庁（JMA）** — 地震情報・津波警報/注意報・雨雲レーダー・危険度分布（キキクル）・気象警報/注意報・潮位表。公共データ利用規約（第1.0版）のもとで提供されています。出典：気象庁ホームページ（各情報ページのURL）。
- **Open-Meteo** — 補助的な気象予報データ（`/v1/forecast`）。データはCC BY 4.0で提供されています。表示箇所には `Weather data by Open-Meteo.com`（https://open-meteo.com/ へのリンク付き）の表示が必要です。

## 6. 交通データ

- **JARTIC（公益財団法人日本道路交通情報センター）／国土交通省道路局** — 道路交通量情報（交通量API機能）。国土交通省が定める交通量API機能利用規約（2025年5月12日施行）に基づき利用しています。本サービスの内容は国土交通省が保証したものではありません。
- **ODPT（公共交通オープンデータセンター）** — 鉄道運行情報。ODPTは事業者・データセットごとに個別のライセンス条件を設定しており、統一の単一ライセンスではありません。本プロジェクトはOWNER承認済みのallowlist方式（`backend/app/services/odpt_allowlist_data.json`）を採用し、公式licenseを確認できた事業者（東京メトロ＝公共交通オープンデータ基本ライセンス、都営＝CC BY 4.0）のデータのみを表示します。license不明・期間限定（チャレンジ限定等）の事業者データは表示・保存しません。詳細は`docs/third-party-inventory.md`API-ODPT-TRAIN参照。

## 7. 外部API一覧

上記の気象庁・Open-Meteo・JARTIC・ODPTは、いずれも実行時にAPIを呼び出して取得するデータであり、レスポンス自体をリポジトリへ同梱・再配布するものではありません（JARTICのみサーバー側で短期キャッシュを保持しますが、`.gitignore`によりリポジトリには含まれません）。

## 8. 同梱している/していないデータセット

- **リポジトリに同梱（tracked）**: OSM由来の道路・鉄道GeoJSON/PMTiles、国土数値情報由来の行政区域境界GeoJSON、Geolonia由来の市区町村座標JSON、津波浸水想定GeoJSON（legacy配信経路）、指定緊急避難場所GeoJSON。
- **リポジトリに同梱しない（実行時に生成・取得）**: 標高DEM、洪水/高潮/土砂災害ハザードの実ジオメトリ、JMA/Open-Meteo/JARTIC/ODPTの各API応答。

## 9. UI attribution表示箇所

現状、`/`・`/live`・`/live/stream`のいずれにも、地図全体に対する恒常的なOpenStreetMap等のattributionコントロールは実装されていません（住所逆ジオコーディング結果ポップアップ内の小さな`© OpenStreetMap contributors`表示のみ存在）。`/live/stream`の市区町村境界レイヤーには国土数値情報の加工表示が実装済みです。その他の必須表示（JARTIC常時表示文言、Open-Meteo attribution linkなど）は未実装です。詳細は`docs/third-party-inventory.md`第4節を参照してください。この不足は本ドキュメント整備だけでは解消できないため、frontend改修の別途対応が必要です。

## 10. 加工表示について

本プロジェクトが第三者データを座標変換・フィルタリング・正規化・集計などの形で加工している場合、各データソースの規約が求める加工表示（「〜を加工して作成」等）を、対応するUI表示またはドキュメント上に明記する方針です。現状の実装状況は`docs/third-party-inventory.md`の各行「Modification notice」列を参照してください。

## 11. ライセンス・利用規約リンク

- OpenStreetMap: https://www.openstreetmap.org/copyright / https://opendatacommons.org/licenses/odbl/1-0/
- 国土数値情報: https://nlftp.mlit.go.jp/ksj/other/agreement.html
- 国土地理院: https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html
- 気象庁: https://www.jma.go.jp/jma/kishou/info/coment.html
- Open-Meteo: https://open-meteo.com/en/licence / https://open-meteo.com/en/terms
- JARTIC交通量API: https://www.jartic-open-traffic.org/
- ODPT: https://developer.odpt.org/terms（現時点で本文取得不能、確認継続中）

## 12. 確認日

本ファイルの記載内容は2026-08-21時点で確認した公式情報に基づきます。規約は変更され得るため、公開・運用にあたっては定期的な再確認を推奨します。

## 13. 保証の否認

本プロジェクトは、掲載する第三者データ・APIの提供元から推奨・保証を受けているものではありません。各データの正確性・完全性・最新性について、本プロジェクトは一切の保証を行いません。特に、本プロジェクトは防災・避難支援を目的としますが、掲載する気象・交通・ハザード情報は参考情報であり、公式発表・現地の指示を優先してください。
