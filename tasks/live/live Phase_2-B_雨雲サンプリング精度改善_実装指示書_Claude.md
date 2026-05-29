````md
# /live Phase 2-B 雨雲サンプリング精度改善 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md
- tasks/live/live_phase1b_danger_cards_codex_verification.md
- tasks/live/live_phase2a_rain_summary_codex_verification.md
- tests/test_live_rain_summary_service.py
- tests/test_live_summary_api.py

既存ナビ本体には触らないこと。

---

# 目的

Phase 2-B では、Phase 2-A の雨雲危険度集計 MVP を改善する。

Phase 2-A は全国 11 地点サンプリングで成立しているが、地点間の狭い強雨域を取り逃す可能性がある。

Phase 2-B の目的は以下。

```text
軽量性を維持したまま、雨雲サンプリング地点を増やし、全国監視としての取り逃しを減らす
````

---

# 現状

Phase 2-A:

```text
全国 11 地点サンプリング
TTL 120秒
strong → warning
severe → danger
warning / danger のみ dangerous_areas へ追加
unknown 50%以上 → evaluated=false
source failure → offline
```

この契約は維持する。

---

# 絶対に守ること

以下は禁止。

* frontend/index.html を変更する
* frontend/js/navigation.js を変更する
* frontend/js/state.js に依存追加する
* frontend/js/hazard-layers.js を変更する
* nav / reroute / OSRM に触る
* frontend 側で全国ラスタ解析を行う
* 全タイル・全ピクセル解析を行う
* JMA へ過剰アクセスする
* unknown / failure を `強雨域なし` にする
* moderate/watch を dangerous_areas に混ぜる
* サーバ負荷を大きく増やす

---

# 基本方針

## 11地点から都道府県代表点ベースへ拡張する

Phase 2-B では、サンプリング地点を以下へ拡張する。

```text
全国 47 都道府県代表点
```

ただし、すべてを毎回必ず厳密に解析する必要はない。

負荷を見ながら、以下のような実装でもよい。

```text
47地点を対象
TTL 120秒維持
並列数制限
タイムアウト設定
unknown過多は evaluated=false
```

---

# 推奨サンプリング地点

各都道府県の県庁所在地付近を代表点とする。

最低限、以下の情報を持つこと。

```python
{
    "id": "tokyo",
    "label": "東京都付近",
    "prefecture": "東京都",
    "lat": 35.6895,
    "lng": 139.6917
}
```

## 注意

ラベルは「東京都」だけではなく、UI 表示では以下のようにする。

```text
東京都付近
福岡県付近
鹿児島県付近
```

厳密な市区町村判定は Phase 2-B では不要。

---

# サンプリング地点定義

既存 `backend/app/services/live_rain_summary_service.py` 内の 11地点を拡張してよい。

ただし、可能であれば以下のように分離する。

```text
LIVE_RAIN_SAMPLE_POINTS
```

または:

```text
backend/app/services/live_rain_sample_points.py
```

Phase 2-B ではどちらでもよいが、テストしやすさを優先する。

---

# 47都道府県代表点

以下をベースにしてよい。

```python
LIVE_RAIN_SAMPLE_POINTS = [
    {"id": "hokkaido", "label": "北海道付近", "prefecture": "北海道", "lat": 43.0642, "lng": 141.3469},
    {"id": "aomori", "label": "青森県付近", "prefecture": "青森県", "lat": 40.8244, "lng": 140.7400},
    {"id": "iwate", "label": "岩手県付近", "prefecture": "岩手県", "lat": 39.7036, "lng": 141.1527},
    {"id": "miyagi", "label": "宮城県付近", "prefecture": "宮城県", "lat": 38.2688, "lng": 140.8721},
    {"id": "akita", "label": "秋田県付近", "prefecture": "秋田県", "lat": 39.7186, "lng": 140.1024},
    {"id": "yamagata", "label": "山形県付近", "prefecture": "山形県", "lat": 38.2404, "lng": 140.3633},
    {"id": "fukushima", "label": "福島県付近", "prefecture": "福島県", "lat": 37.7503, "lng": 140.4676},
    {"id": "ibaraki", "label": "茨城県付近", "prefecture": "茨城県", "lat": 36.3418, "lng": 140.4468},
    {"id": "tochigi", "label": "栃木県付近", "prefecture": "栃木県", "lat": 36.5657, "lng": 139.8836},
    {"id": "gunma", "label": "群馬県付近", "prefecture": "群馬県", "lat": 36.3911, "lng": 139.0608},
    {"id": "saitama", "label": "埼玉県付近", "prefecture": "埼玉県", "lat": 35.8569, "lng": 139.6489},
    {"id": "chiba", "label": "千葉県付近", "prefecture": "千葉県", "lat": 35.6047, "lng": 140.1233},
    {"id": "tokyo", "label": "東京都付近", "prefecture": "東京都", "lat": 35.6895, "lng": 139.6917},
    {"id": "kanagawa", "label": "神奈川県付近", "prefecture": "神奈川県", "lat": 35.4478, "lng": 139.6425},
    {"id": "niigata", "label": "新潟県付近", "prefecture": "新潟県", "lat": 37.9026, "lng": 139.0232},
    {"id": "toyama", "label": "富山県付近", "prefecture": "富山県", "lat": 36.6953, "lng": 137.2113},
    {"id": "ishikawa", "label": "石川県付近", "prefecture": "石川県", "lat": 36.5947, "lng": 136.6256},
    {"id": "fukui", "label": "福井県付近", "prefecture": "福井県", "lat": 36.0652, "lng": 136.2216},
    {"id": "yamanashi", "label": "山梨県付近", "prefecture": "山梨県", "lat": 35.6642, "lng": 138.5683},
    {"id": "nagano", "label": "長野県付近", "prefecture": "長野県", "lat": 36.6513, "lng": 138.1810},
    {"id": "gifu", "label": "岐阜県付近", "prefecture": "岐阜県", "lat": 35.3912, "lng": 136.7223},
    {"id": "shizuoka", "label": "静岡県付近", "prefecture": "静岡県", "lat": 34.9769, "lng": 138.3831},
    {"id": "aichi", "label": "愛知県付近", "prefecture": "愛知県", "lat": 35.1802, "lng": 136.9066},
    {"id": "mie", "label": "三重県付近", "prefecture": "三重県", "lat": 34.7303, "lng": 136.5086},
    {"id": "shiga", "label": "滋賀県付近", "prefecture": "滋賀県", "lat": 35.0045, "lng": 135.8686},
    {"id": "kyoto", "label": "京都府付近", "prefecture": "京都府", "lat": 35.0211, "lng": 135.7556},
    {"id": "osaka", "label": "大阪府付近", "prefecture": "大阪府", "lat": 34.6937, "lng": 135.5023},
    {"id": "hyogo", "label": "兵庫県付近", "prefecture": "兵庫県", "lat": 34.6913, "lng": 135.1830},
    {"id": "nara", "label": "奈良県付近", "prefecture": "奈良県", "lat": 34.6851, "lng": 135.8048},
    {"id": "wakayama", "label": "和歌山県付近", "prefecture": "和歌山県", "lat": 34.2260, "lng": 135.1675},
    {"id": "tottori", "label": "鳥取県付近", "prefecture": "鳥取県", "lat": 35.5039, "lng": 134.2383},
    {"id": "shimane", "label": "島根県付近", "prefecture": "島根県", "lat": 35.4723, "lng": 133.0505},
    {"id": "okayama", "label": "岡山県付近", "prefecture": "岡山県", "lat": 34.6618, "lng": 133.9350},
    {"id": "hiroshima", "label": "広島県付近", "prefecture": "広島県", "lat": 34.3963, "lng": 132.4594},
    {"id": "yamaguchi", "label": "山口県付近", "prefecture": "山口県", "lat": 34.1859, "lng": 131.4714},
    {"id": "tokushima", "label": "徳島県付近", "prefecture": "徳島県", "lat": 34.0658, "lng": 134.5593},
    {"id": "kagawa", "label": "香川県付近", "prefecture": "香川県", "lat": 34.3401, "lng": 134.0434},
    {"id": "ehime", "label": "愛媛県付近", "prefecture": "愛媛県", "lat": 33.8416, "lng": 132.7661},
    {"id": "kochi", "label": "高知県付近", "prefecture": "高知県", "lat": 33.5597, "lng": 133.5311},
    {"id": "fukuoka", "label": "福岡県付近", "prefecture": "福岡県", "lat": 33.5902, "lng": 130.4017},
    {"id": "saga", "label": "佐賀県付近", "prefecture": "佐賀県", "lat": 33.2494, "lng": 130.2988},
    {"id": "nagasaki", "label": "長崎県付近", "prefecture": "長崎県", "lat": 32.7448, "lng": 129.8737},
    {"id": "kumamoto", "label": "熊本県付近", "prefecture": "熊本県", "lat": 32.7898, "lng": 130.7417},
    {"id": "oita", "label": "大分県付近", "prefecture": "大分県", "lat": 33.2382, "lng": 131.6126},
    {"id": "miyazaki", "label": "宮崎県付近", "prefecture": "宮崎県", "lat": 31.9111, "lng": 131.4239},
    {"id": "kagoshima", "label": "鹿児島県付近", "prefecture": "鹿児島県", "lat": 31.5602, "lng": 130.5581},
    {"id": "okinawa", "label": "沖縄県付近", "prefecture": "沖縄県", "lat": 26.2124, "lng": 127.6792}
]
```

---

# パフォーマンス制約

## TTL

既存の 120秒 TTL は維持する。

```text
TTL 120s
```

---

## 並列数制限

47地点を一度に無制限並列にしないこと。

推奨:

```text
max_workers = 8
```

または asyncio semaphore 等。

---

## タイムアウト

1地点ごとの取得にタイムアウトを設ける。

外部取得が詰まって `/api/live/summary` 全体が遅くならないようにする。

推奨:

```text
per_sample_timeout = 3s
```

既存 `get_precip_intensity_at` 側に timeout がある場合はそれを利用する。

---

# unknown の扱い

47地点化により unknown が一部混じる可能性が増える。

既存ルールを維持する。

```text
unknown_count / sample_count >= 0.5
→ evaluated=false
→ strong_rain_detected=null
```

ただし、warning/danger が検出されている場合は以下を優先してよい。

```text
強雨検出あり
→ evaluated=true
→ strong_rain_detected=true
```

理由:

```text
一部 unknown でも危険検出は表示すべき
```

---

# areas の件数制限

雨雲 warning/danger が多数出た場合、カードが肥大化しないよう制限する。

推奨:

```text
areas 最大 5件
dangerous_areas への rain 追加も最大 5件
```

優先順位:

```text
danger > warning
```

同レベルなら任意でよい。

---

# level 判定維持

```text
severe   → danger
strong   → warning
moderate → watch
weak/none → normal扱い
unknown → 集計のみ
```

ただし:

```text
watch は dangerous_areas に入れない
```

---

# summary 契約

47地点化後も既存契約を維持する。

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_nowcast",
  "summary": {
    "strong_rain_detected": true,
    "warning_area_count": 3,
    "danger_area_count": 1,
    "sample_count": 47,
    "unknown_count": 2
  },
  "areas": []
}
```

---

# 注意: sample_count

`sample_count` は実際に対象とした地点数を返す。

Phase 2-B では原則:

```text
sample_count = 47
```

ただし明示的に一部地点をスキップした場合は、その理由を test / notes に残すこと。

---

# API failure

全地点取得失敗など source failure の場合:

```json
{
  "status": "offline",
  "evaluated": false,
  "reason": "source_unavailable",
  "summary": {
    "strong_rain_detected": null,
    "warning_area_count": null,
    "danger_area_count": null,
    "sample_count": 47,
    "unknown_count": 47
  },
  "areas": []
}
```

---

# pytest 更新

`tests/test_live_rain_summary_service.py` を更新する。

追加・修正確認:

* サンプル地点が 47件
* 各地点に id / label / prefecture / lat / lng がある
* id が重複しない
* sample_count が 47
* severe は danger
* strong は warning
* moderate は watch だが dangerous_areas には入らない
* areas は warning/danger のみ
* areas 最大 5件
* unknown 50%以上で evaluated=false
* warning/danger がある場合は unknown が混じっても detected=true
* source failure で offline
* キャッシュ TTL は 120s のまま

---

# summary API test 更新

`tests/test_live_summary_api.py` も必要に応じて更新。

確認:

* `/api/live/summary.rain.summary.sample_count == 47` または test mock 上の期待値
* evaluated=false 時 false-safe なし
* rain areas が dangerous_areas に統合される
* rain areas 最大件数制限が守られる

---

# E2E 更新

`e2e/live-basic.spec.js` に追加または既存確認を更新する。

確認:

* rain warning mock で危険地域に雨雲が出る
* 複数 rain areas でもカードが崩れない
* areas 最大 5件程度に制限
* rain evaluated=false で `強雨域なし` を表示しない
* rain offline で `雨雲情報: 取得失敗`
* page error なし

---

# UI 表示

UI は大きく変更しなくてよい。

ただし、雨雲危険地域が複数出る場合もカードが崩れないこと。

例:

```text
危険地域
1 鹿児島県付近  雨雲
2 宮崎県付近    雨雲
3 高知県付近    雨雲
```

---

# 完了条件

以下を満たすこと。

* サンプリング地点が 47地点に増える
* TTL 120秒維持
* 並列数制限または過剰アクセス抑制がある
* sample_count が原則 47
* unknown / failure で false-safe しない
* warning/danger のみ areas / dangerous_areas に追加
* areas 最大件数制限がある
* backend pytest PASS
* `/live` E2E PASS
* 既存ナビ代表 E2E PASS
* 禁止ファイル未変更
* navigation/state/reroute/OSRM 依存なし

---

# 検証コマンド

```bash
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-main.js
node --check frontend/js/live/live-danger-summary.js

pytest tests/test_live_rain_summary_service.py
pytest tests/test_live_summary_api.py

npx playwright test e2e/live-basic.spec.js

npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

---

# 報告内容

完了後、以下を報告すること。

* 変更ファイル
* サンプリング地点数
* 並列数 / timeout / TTL
* unknown の扱い
* areas 最大件数
* `/api/live/summary.rain` のレスポンス例
* pytest 結果
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
