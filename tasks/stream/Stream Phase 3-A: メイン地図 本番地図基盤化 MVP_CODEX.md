CODEX用検証指示書
/live/stream Stream Phase 3-A: メイン地図 本番地図基盤化 MVP 検証
目的

Claude Code が実装した /live/stream 中央メイン地図の本番地図基盤化を検証する。

主な検証対象:

中央メイン地図が本番地図に置き換わっている
日本全土が表示される
見るだけ地図として操作UIが無効化されている
既存パルスが本番地図上に表示される
OSM attribution が表示される
既存E2Eが壊れていない
/live と / に影響がない

検証結果を Markdown レポートとして保存する。

レポート保存先
tasks/live/live_stream_phase3a_main_map_codex_verification.md
1. 静的確認

変更ファイルを確認する。

git status --short
git diff --stat

確認観点:

/live/stream 関連ファイル中心の変更である
LiveStreamMapView または同等の地図ラッパーがある
中央メイン地図のみを対象にしている
小窓地図の大規模変更をしていない
通常 /live への影響が最小限である
通常 / への影響がない
2. スコープ逸脱確認

以下へ広げていないことを確認する。

地震小窓OSM化
豪雨小窓OSM化
地震市町村震度マーカー
鉄道簡略路線図
鉄道小窓OSM化
地図クリック/ポップアップ
YouTube/OBS連携
DB追加

Phase 3-A は中央メイン地図のみ。

3. 構文チェック

対象JSに node --check を実行する。

例:

node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-clock.js
node --check frontend/js/live-stream/live-stream-ticker.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-map.js

新規ファイルがある場合:

node --check frontend/js/live-stream/live-stream-map-view.js

E2E:

node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
node --check e2e/tide-mock-verify.spec.js
node --check e2e/rail-mock-verify.spec.js

追加E2Eがある場合:

node --check e2e/live-stream-main-map.spec.js
4. Docker状態確認
docker compose ps

確認対象:

frontend
backend
martin
osrm-walking

既存サービスが壊れていないこと。

5. HTTP確認

以下が 200 で返ること。

/live/stream
/live/stream?chrome=off
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live
/
6. 中央地図の本番地図化確認

対象URL:

/live/stream?chrome=off

確認項目:

live-stream-center-map が表示される
中央メイン地図がモックSVGではなく本番地図基盤で表示される
Leaflet等の地図コンテナが生成されている
地図タイルが読み込まれている
日本全土が表示されている

確認例:

.leaflet-container が存在する
.leaflet-tile が存在する

ただし、実装が Leaflet 以外の場合は相当する地図DOMで確認する。

7. 日本全土表示確認

中央地図に以下が収まっていることを目視またはスクリーンショットで確認する。

北海道
本州
四国
九州
沖縄本島周辺

小笠原は今回必須ではない。

地図が以下になっていないこと。

東京周辺だけにズームしている
本州だけしか見えない
北海道または沖縄が切れている
海だけになっている
真っ白
8. 操作UI無効化確認

対象URL:

/live/stream?chrome=off

確認項目:

ズームボタンが表示されない
ドラッグしても地図が動かない
ホイールズームできない
ダブルクリックズームできない
ポップアップが出ない

Playwrightで可能なら以下を確認する。

.drag操作前後で地図中心が変わらない
.zoom control DOM が存在しない
.leaflet-popup が存在しない
9. OSM attribution確認

OSM由来地図を使っている場合、attribution が表示されること。

確認文言例:

OpenStreetMap
© OpenStreetMap contributors

確認項目:

attribution が中央地図または画面内に表示される
表示が大きすぎてUIを邪魔していない
10. demo=1 パルス確認

対象URL:

/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00

確認項目:

中央地図が本番地図で表示される
地震デモパルスが本番地図上に表示される
豪雨デモパルスが本番地図上に表示される
パルスが地図外や画面端に飛ばない
テロップや小窓は既存通り表示される

DOM確認候補:

live-stream-map-pulse
live-stream-map-pulse-earthquake
live-stream-map-pulse-rain

または class 名で確認。

11. state=calm パルスなし確認

対象URL:

/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00

確認項目:

中央地図は本番地図で表示される
警戒パルスが表示されない
監視中文言が表示される
下部テロップが監視中になる
12. 通常表示の実データパルス確認

対象URL:

/live/stream?chrome=off

確認項目:

実データ由来の対象がある場合はパルスが表示される
実データ対象がない場合はパルスなしでもよい
デモパルスが混入していない
画面が壊れない

検証時点の実データが少ない場合は、パルスなしを理由に FAIL にしない。
ただし、demo固定データが通常表示に混入していたら FAIL。

13. 既存E2E実行

既存E2Eをすべて実行する。

npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/eq-mock-verify.spec.js
npx playwright test e2e/rain-mock-verify.spec.js
npx playwright test e2e/tide-mock-verify.spec.js
npx playwright test e2e/rail-mock-verify.spec.js

追加E2Eがある場合:

npx playwright test e2e/live-stream-main-map.spec.js

期待:

全テスト PASS
14. 表示欠損確認

以下が画面に出ていないこと。

undefined
null
NaN
Invalid Date
[object Object]

中央地図まわりでも以下がないこと。

地図初期化失敗で真っ白
タイル404大量発生
Leaflet初期化例外
Unhandled promise rejection
15. スクリーンショット保存

以下を保存する。

test-results/live-stream-phase3a-main-map-real-1920.png
test-results/live-stream-phase3a-main-map-demo-1920.png
test-results/live-stream-phase3a-main-map-calm-1920.png

対象URL:

/live/stream?chrome=off
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
16. /live 回帰確認

通常 /live を開く。

確認項目:

HTTP 200
console/page error なし
地図表示が壊れていない
地震表示が壊れていない
キキクル・豪雨表示が壊れていない
潮位表示が壊れていない
鉄道表示が壊れていない

特に、/live/stream 用CSS/JSが通常 /live に漏れていないこと。

17. / 回帰確認

ナビ本体 / を開く。

確認項目:

HTTP 200
console/page error なし
基本地図表示が壊れていない
/live/stream CSS/JS が漏れていない
18. レポート作成

保存先:

tasks/live/live_stream_phase3a_main_map_codex_verification.md

レポートに含める内容:

判定: PASS / PASS with notes / FAIL
検証日時
対象ブランチ/コミット
変更ファイル
構文チェック結果
Docker状態
HTTP確認結果
中央地図本番化確認
日本全土表示確認
操作UI無効化確認
OSM attribution確認
demo=1 パルス確認
state=calm 確認
通常表示確認
E2E結果
表示欠損確認
スクリーンショット保存先
/live 回帰
/ 回帰
Notes
修正推奨事項
PASS条件

以下を満たせば PASS。

/live/stream が表示できる
中央メイン地図が本番地図基盤で表示される
日本全土が表示される
地図操作UIが出ない
ドラッグ/ズーム操作が無効
OSM attribution が表示される
demo=1 で本番地図上にパルスが表示される
state=calm で本番地図のみ表示され、警戒パルスが出ない
既存E2EがPASS
console/page error なし
/live が壊れていない
/ が壊れていない
PASS with notes条件

以下は PASS with notes とする。

通常表示時に実データ対象がなくパルスなし
地図タイルが一時的に外部OSM依存
小笠原など離島の一部が初期表示範囲外
パルス位置確認がdemo中心
操作無効化確認が目視中心
FAIL条件

以下の場合は FAIL。

/live/stream が404
画面が真っ白
中央地図が表示されない
モックSVG地図のまま
日本全土が表示されない
地図操作UIが出ている
ドラッグ/ズームできる
OSM attribution がない
demo=1 でパルスが表示されない
パルスが地図外に飛ぶ
既存E2Eが壊れる
重大なconsole/page error
/live が壊れる
/ が壊れる