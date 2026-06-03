# 情報タブ「天気」警報・注意報表示 Codex検証

## 判定

PASS with notes

Claude修正後に再検証し、初回FAIL要因は解消した。追加確認で残っていた JMA warning code の誤分類と島しょ部の区域絞り込みも修正し、API/UI/回帰確認はPASS。

## 実装差分の概要

- `backend/app/api/weather.py`
  - `GET /api/weather/warnings` を追加。
  - 経度は `lon` / `lng` の両方を受け付ける。両方指定時は `lon` 優先。
- `backend/app/services/jma_warning_service.py`
  - 既存 alert service の結果を `ok/items/max_level` 形式へ変換。
  - 取得失敗時は `ok:false` とし、警報なしと断定しない。
- `backend/app/services/jma_weather_adapter.py`
  - JMA warning JSON の `code` から警報名・区域名を補完。
  - `解除` と `発表警報・注意報はなし` を除外。
  - 現行JSONに合わせて `code 14=雷注意報`, `15=強風注意報`, `16=波浪注意報`, `20=濃霧注意報` などへ補正。
  - 市区町村に対応する一次細分区域が特定できた場合は、その区域のみ返す。
- `backend/app/services/weather_alert_service.py`
  - 逆ジオコードの住所文字列から JMA 区域キーワードを優先抽出。
  - 島しょ部で `city=東京都` となるケースでも `大島町` / `八丈町` などを抽出。
  - 逆ジオコード住所から都道府県名を補正し、重心距離による誤判定を避ける。
- `frontend/js/weather-card.js`
  - `status=unavailable` かつ alerts 空のとき `警報・注意報：取得できません` を表示。
- `data_lake/registry/weather/jma_area_codes.json`
  - JMA区域コード名と一次細分区域キーワードが追加された。

## API確認結果

### 想定API `lng` パラメータ

```bash
curl -i "http://127.0.0.1:8000/api/weather/warnings?lat=35.65&lng=139.54"
```

結果:

- HTTP 200
- `ok: true`
- `area_name: 調布市`
- `max_level: none`
- `items: []`

調布付近はJMA実データ上、発令中の警報・注意報なし。`lng` 指定で取得できることを確認した。

### 島しょ部の区域判定

大島付近:

```bash
curl -s "http://127.0.0.1:8000/api/weather/alerts/current?lat=34.75&lon=139.36"
```

結果:

- `pref_code: 130000`
- `city: 大島町`
- alerts は `伊豆諸島北部` の `雷注意報`, `濃霧注意報` のみ
- `severity: advisory`

八丈島付近:

```bash
curl -s "http://127.0.0.1:8000/api/weather/alerts/current?lat=33.10&lon=139.80"
```

結果:

- `pref_code: 130000`
- `city: 八丈町`
- alerts は `伊豆諸島南部` の `雷注意報`, `強風注意報`, `波浪注意報`, `濃霧注意報` のみ
- `severity: advisory`

### JMA JSON 抽出・解除除外

- `解除` 済み項目は返らない。
- `発表警報・注意報はなし` は警報アイテムとして返らない。
- 発令中の注意報のみ含まれる。
- `code 14/15/16/20` は特別警報ではなく注意報として返る。

## UI確認結果

Playwrightで現在地を調布付近に固定し、情報タブ内の気象カードを確認した。

- 天気カード表示: PASS
- 警報・注意報欄表示: PASS
- 調布付近の発令なし表示: `警報・注意報なし`
- 降水表示: `現在: 降水なし`
- 標高表示: `36 m`
- レイヤー/凡例/地震タブ DOM 存在: PASS
- console error / page error: なし

スクリーンショット:

```text
tasks/weather_warning_info_tab.png
```

## 取得失敗時の確認結果

Playwrightプローブで weather alerts API 失敗をモックし、表示を確認した。

結果:

```text
警報・注意報：取得できません
気象情報を取得できません
```

取得失敗時に `警報・注意報なし` と断定しない表示を確認した。

## 回帰確認結果

実行コマンド:

```bash
python3 -m compileall backend
node --check frontend/js/location-info-panel.js
node --check frontend/js/weather.js
node --check frontend/js/weather-card.js
docker compose ps
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/live/summary
node /private/tmp/weather_warning_info_tab_probe.js
```

結果:

- backend compile: PASS
- JS syntax: PASS
- backend health: PASS
- Docker services: backend/frontend/martin/osrm 起動確認
- 情報タブ表示: PASS
- 降水表示: PASS
- 標高表示: PASS
- レイヤー/凡例/地震タブ: PASS
- `/live` summary: PASS
- `/live` UI基本表示: PASS

補足:

- `frontend/js/jma-warning.js` は存在しないため対象外。

## 残課題

- `resolve_pref_code()` 自体は重心距離ベースのままなので、今回の警報APIでは逆ジオコード補正で吸収している。将来的には都道府県ポリゴンまたはJMA区域ポリゴンでの判定が望ましい。
- 未対応区域で府県全体へフォールバックする挙動は残る。誤表示リスクをさらに下げるなら、区域未判定時は非断定表示に寄せる設計を検討する。
