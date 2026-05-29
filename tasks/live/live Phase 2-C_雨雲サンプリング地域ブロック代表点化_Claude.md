````md
# /live Phase 2-C 雨雲サンプリング地域ブロック代表点化 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md
- tasks/live/live_phase1b_danger_cards_codex_verification.md
- tasks/live/live_phase2a_rain_summary_codex_verification.md
- tasks/live/live_phase2b_rain_sampling_codex_verification.md
- tests/test_live_rain_summary_service.py
- tests/test_live_summary_api.py

既存ナビ本体には触らないこと。

---

# 目的

Phase 2-C では、Phase 2-B の 47 都道府県代表点サンプリングをさらに改善し、地域ブロックごとに追加代表点を入れる。

目的は以下。

```text
47都道府県代表点だけでは拾いにくい局地的な強雨を、軽量性を維持しながら拾いやすくする
````

ただし、全国メッシュ解析や全タイル解析には進まない。

---

# 現状

Phase 2-B:

```text
47都道府県代表点
TTL 120秒
max_workers=8
_TOTAL_SAMPLING_TIMEOUT=24s
areas 最大5件
unknown>=50% かつ warning/danger なし → evaluated=false
warning/danger あり → evaluated=true 優先
warning/danger のみ areas / dangerous_areas へ追加
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
* areas 上限を外す
* サーバ負荷を大きく増やす

---

# 基本方針

## 47地点から 70〜80地点程度へ拡張する

Phase 2-C では、47都道府県代表点に地域ブロック代表点を追加する。

目安:

```text
47地点 + 追加25〜30地点
= 72〜77地点程度
```

上限目安:

```text
最大80地点
```

80地点を超えないこと。

---

# 追加代表点の考え方

追加する地点は、以下を優先する。

```text
- 人口が多い地域
- 広い都道府県内の別地域
- 豪雨確認で重要そうな地域
- 離島・半島など県庁所在地だけでは代表しにくい地域
- 太平洋側 / 日本海側の差が出やすい地域
```

---

# 追加代表点の例

以下をベースに追加してよい。

## 北海道

```python
{"id": "hokkaido_asahikawa", "label": "北海道 旭川付近", "prefecture": "北海道", "lat": 43.7706, "lng": 142.3649},
{"id": "hokkaido_hakodate", "label": "北海道 函館付近", "prefecture": "北海道", "lat": 41.7687, "lng": 140.7288},
{"id": "hokkaido_kushiro", "label": "北海道 釧路付近", "prefecture": "北海道", "lat": 42.9849, "lng": 144.3818},
```

## 東北

```python
{"id": "aomori_hachinohe", "label": "青森県 八戸付近", "prefecture": "青森県", "lat": 40.5123, "lng": 141.4884},
{"id": "iwate_miyako", "label": "岩手県 宮古付近", "prefecture": "岩手県", "lat": 39.6414, "lng": 141.9571},
{"id": "fukushima_iwaki", "label": "福島県 いわき付近", "prefecture": "福島県", "lat": 37.0505, "lng": 140.8877},
```

## 関東

```python
{"id": "tokyo_tama", "label": "東京都 多摩付近", "prefecture": "東京都", "lat": 35.6664, "lng": 139.3160},
{"id": "tokyo_islands", "label": "東京都 伊豆諸島付近", "prefecture": "東京都", "lat": 34.7500, "lng": 139.3550},
{"id": "kanagawa_odawara", "label": "神奈川県 小田原付近", "prefecture": "神奈川県", "lat": 35.2556, "lng": 139.1597},
{"id": "chiba_tateyama", "label": "千葉県 館山付近", "prefecture": "千葉県", "lat": 34.9965, "lng": 139.8700},
{"id": "ibaraki_tsukuba", "label": "茨城県 つくば付近", "prefecture": "茨城県", "lat": 36.0835, "lng": 140.0764},
```

## 中部

```python
{"id": "niigata_nagaoka", "label": "新潟県 長岡付近", "prefecture": "新潟県", "lat": 37.4462, "lng": 138.8513},
{"id": "nagano_matsumoto", "label": "長野県 松本付近", "prefecture": "長野県", "lat": 36.2380, "lng": 137.9720},
{"id": "shizuoka_hamamatsu", "label": "静岡県 浜松付近", "prefecture": "静岡県", "lat": 34.7108, "lng": 137.7261},
{"id": "aichi_toyohashi", "label": "愛知県 豊橋付近", "prefecture": "愛知県", "lat": 34.7692, "lng": 137.3915},
{"id": "ishikawa_noto", "label": "石川県 能登付近", "prefecture": "石川県", "lat": 37.3900, "lng": 136.9000},
```

## 関西

```python
{"id": "kyoto_maizuru", "label": "京都府 舞鶴付近", "prefecture": "京都府", "lat": 35.4748, "lng": 135.3859},
{"id": "hyogo_toyooka", "label": "兵庫県 豊岡付近", "prefecture": "兵庫県", "lat": 35.5445, "lng": 134.8202},
{"id": "wakayama_shingu", "label": "和歌山県 新宮付近", "prefecture": "和歌山県", "lat": 33.7241, "lng": 135.9925},
{"id": "osaka_sakai", "label": "大阪府 堺付近", "prefecture": "大阪府", "lat": 34.5733, "lng": 135.4828},
```

## 中国・四国

```python
{"id": "hiroshima_fukuyama", "label": "広島県 福山付近", "prefecture": "広島県", "lat": 34.4859, "lng": 133.3623},
{"id": "shimane_hamada", "label": "島根県 浜田付近", "prefecture": "島根県", "lat": 34.8993, "lng": 132.0796},
{"id": "ehime_uwajima", "label": "愛媛県 宇和島付近", "prefecture": "愛媛県", "lat": 33.2232, "lng": 132.5600},
{"id": "kochi_shimanto", "label": "高知県 四万十付近", "prefecture": "高知県", "lat": 32.9916, "lng": 132.9339},
```

## 九州・沖縄

```python
{"id": "fukuoka_kitakyushu", "label": "福岡県 北九州付近", "prefecture": "福岡県", "lat": 33.8834, "lng": 130.8751},
{"id": "nagasaki_sasebo", "label": "長崎県 佐世保付近", "prefecture": "長崎県", "lat": 33.1799, "lng": 129.7151},
{"id": "kumamoto_amakusa", "label": "熊本県 天草付近", "prefecture": "熊本県", "lat": 32.4594, "lng": 130.1930},
{"id": "kagoshima_amami", "label": "鹿児島県 奄美付近", "prefecture": "鹿児島県", "lat": 28.3772, "lng": 129.4937},
{"id": "okinawa_ishigaki", "label": "沖縄県 石垣付近", "prefecture": "沖縄県", "lat": 24.3407, "lng": 124.1556}
```

---

# 地点数

上記をすべて入れると 79 地点前後になる想定。

完了条件:

```text
70 <= sample_count <= 80
```

---

# サンプル地点設計

可能であれば、地点に以下の種別を持たせる。

```python
"kind": "prefecture_capital"
```

または:

```python
"kind": "regional"
```

目的:

* 将来、重み付けや表示制御をしやすくするため
* Phase 2-C では UI 表示に使わなくてよい

---

# パフォーマンス制約

## TTL

維持。

```text
TTL 120s
```

---

## 並列数

現状維持でよい。

```text
max_workers = 8
```

増やさないこと。

---

## timeout

80地点弱になるため、全体 timeout を見直す。

現状:

```text
_TOTAL_SAMPLING_TIMEOUT = 24.0
```

Phase 2-C では、実装方式に応じて以下目安。

```text
30〜36秒以内
```

ただし `/api/live/summary` の実応答が重すぎるなら、timeout を短めにする。

重要:

```text
JMA取得が詰まっても /api/live/summary 全体が長時間停止しないこと
```

---

# areas の上限

維持。

```text
_MAX_AREAS = 5
```

UI に出す危険地域は最大5件。

warning/danger 検出件数は summary count に残す。

---

# unknown の扱い

Phase 2-B を維持。

```text
unknown_count / sample_count >= 0.5
かつ warning/danger なし
→ evaluated=false
→ strong_rain_detected=null
```

ただし、

```text
warning/danger が1件でもある
→ evaluated=true
→ strong_rain_detected=true
```

---

# level 判定維持

```text
severe   → danger
strong   → warning
moderate → watch
weak/none → normal相当
unknown → 集計のみ
```

`watch` は dangerous_areas に入れない。

---

# summary 契約

Phase 2-C 以降も契約は変えない。

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_nowcast",
  "summary": {
    "strong_rain_detected": true,
    "warning_area_count": 4,
    "danger_area_count": 1,
    "sample_count": 76,
    "unknown_count": 3
  },
  "areas": []
}
```

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
    "sample_count": 76,
    "unknown_count": 76
  },
  "areas": []
}
```

---

# pytest 更新

`tests/test_live_rain_summary_service.py` を更新する。

追加・修正確認:

* サンプル地点数が 70〜80
* 各地点に id / label / prefecture / lat / lng がある
* 可能なら kind がある
* id が重複しない
* sample_count が地点数と一致
* TTL は 120s
* max_workers は 8
* timeout は 30〜36秒以内、または妥当な値
* severe は danger
* strong は warning
* moderate は watch だが dangerous_areas には入らない
* areas は warning/danger のみ
* areas 最大 5件
* unknown 50%以上で evaluated=false
* warning/danger がある場合は unknown が混じっても detected=true
* source failure で offline
* offline sample_count が地点数と一致

---

# summary API test 更新

`tests/test_live_summary_api.py` も必要に応じて更新。

確認:

* `/api/live/summary.rain.summary.sample_count` が 70〜80 または mock 地点数
* evaluated=false 時 false-safe なし
* rain areas が dangerous_areas に統合される
* rain areas 最大件数制限が守られる

---

# E2E 更新

`e2e/live-basic.spec.js` に必要があれば追加。

既存 Phase 2-B の以下が維持されること。

* rain warning mock で危険地域に雨雲が出る
* 複数 rain areas でもカードが崩れない
* areas 最大5件制限
* rain evaluated=false で `強雨域なし` を表示しない
* rain offline で `雨雲情報: 取得失敗`
* page error なし

Phase 2-C で UI を大きく変えないなら E2E 追加は最小でよい。

---

# UI

UI は大きく変更しない。

目的は sampling precision 改善であり、画面表示の作り直しではない。

---

# 完了条件

以下を満たすこと。

* サンプリング地点が 70〜80地点になる
* 47都道府県代表点を維持した上で地域代表点が追加される
* TTL 120秒維持
* max_workers=8 維持
* timeout が過剰に長くない
* sample_count が地点数と一致
* unknown / failure で false-safe しない
* warning/danger のみ areas / dangerous_areas に追加
* areas 最大5件維持
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
* 追加代表点の概要
* kind の有無
* TTL / max_workers / timeout
* unknown の扱い
* areas 最大件数
* `/api/live/summary.rain` のレスポンス例
* pytest 結果
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
