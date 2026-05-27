# /live Phase 1-B 危険地域カード強化 実装指示書（Claude Code向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md

既存ナビ本体には触らないこと。

---

# 目的

`/live` MVP の「現在の状況」カードを強化し、全国監視ビューアとして

```text
今どこが危ないのか
````

を一目で分かるようにする。

Phase 1-B では、詳細分析よりも「危険地域の要約・ランキング・フォーカス導線」を優先する。

---

# 対象ページ

```text
/frontend/live.html
```

---

# 変更対象

原則として以下のみ。

```text
frontend/js/live/live-alert-panel.js
frontend/js/live/live-layers.js
frontend/js/live/live-ui.js
frontend/js/live/live-main.js
frontend/css/live/live.css
e2e/live-basic.spec.js
```

必要な場合のみ新規追加可。

```text
frontend/js/live/live-danger-summary.js
```

---

# 禁止事項

以下は禁止。

```text
frontend/index.html
frontend/js/navigation.js
frontend/js/state.js
frontend/js/nav-*.js
frontend/js/hazard-layers.js
frontend/js/location-info-panel.js
既存 reroute 関連
既存 bottom panel 関連
OSRM 依存追加
```

---

# 実装方針

## 1. 危険地域カードを追加・強化する

現在の左上カードを拡張し、以下を表示する。

### 表示項目

最低限:

* 津波警報・注意報の有無
* 地震発生件数 24h
* 強雨域の有無
* キキクル危険度あり / なし
* API 取得状態

例:

```text
現在の状況

津波警報なし
地震 1件（24h）
強雨域なし
キキクル危険地域なし

更新 22:40
```

---

## 2. 危険地域ランキングを追加する

可能であれば、カード内または下部に「危険地域」リストを出す。

例:

```text
危険地域

1. 東京都 伊豆諸島
   地震 / 雨雲

2. 沖縄県 先島諸島
   雨雲

3. 宮城県沿岸
   津波注意報
```

初期実装では厳密なランキングでなくてよい。

優先順位:

```text
津波警報 > 津波注意報 > 地震 > キキクル > 強雨
```

---

# データ仕様

## 初期は既存APIを利用する

既存の `/live` MVP で利用している API / layer refresh 結果を利用する。

新規 backend API は原則不要。

ただし frontend 側で集計しにくい場合は、live 専用 API として以下を追加してよい。

```text
backend/app/api/live_summary.py
backend/app/services/live_summary_service.py
```

追加する場合も既存ナビ API を壊さないこと。

---

# 推奨データ構造

frontend 内では以下のような形式にまとめる。

```js
{
  updatedAt: Date,
  statuses: {
    rain: 'ok' | 'offline' | 'unknown',
    kikikuru: 'ok' | 'offline' | 'unknown',
    earthquake: 'ok' | 'offline' | 'unknown',
    tsunami: 'ok' | 'offline' | 'unknown'
  },
  summary: {
    tsunamiActive: false,
    earthquakeCount24h: 1,
    strongRainDetected: false,
    kikikuruDangerDetected: false
  },
  dangerousAreas: [
    {
      id: 'area-1',
      label: '東京都 伊豆諸島',
      level: 'warning',
      types: ['earthquake', 'rain'],
      lat: 34.7,
      lng: 139.4
    }
  ]
}
```

---

# UI 要件

## 危険度表示

危険度は以下の3段階でよい。

```text
danger   緊急・警報級
warning  注意・注視
normal   現時点で大きな警戒なし
```

## 色の意味

既存 `/live` のダークテーマに合わせる。

* danger: 赤系
* warning: 黄・橙系
* normal: 緑または抑制色
* offline: グレーまたは赤ドット

---

# フォーカス機能

危険地域リストの項目をクリックしたら、その地点へ map focus する。

最低限:

```js
map.setView([lat, lng], 7)
```

でよい。

ただし lat/lng がない項目はクリック不可でよい。

---

# 空状態

危険情報がない場合は、安心できる表示にする。

例:

```text
現在、大きな警戒情報はありません
```

ただし API が offline の場合は「安全」と断定しないこと。

例:

```text
一部情報を取得できません
```

---

# API 失敗時の扱い

重要:

```text
情報なし
```

と

```text
取得失敗
```

を混同しないこと。

API 失敗時は以下を守る。

* 画面を壊さない
* map 操作を継続
* status dot を offline
* 「安全」と断定しない
* console.error を出さない
* console.warn は許容

---

# E2E 追加

`e2e/live-basic.spec.js` に以下を追加する。

## 追加確認

* 危険地域カードが表示される
* 地震1件 mock 時にカードへ件数が出る
* 危険地域リストが表示される
* 危険地域クリックで map center / zoom が変わる
* 全API正常・危険なしの場合に「大きな警戒情報なし」表示
* API offline 時に「安全」と断定しない
* console.error / page error がない

---

# CSS

`frontend/css/live/live.css` に追記する。

既存ナビ CSS には触らない。

カードはスマホでも見切れないこと。

---

# 完了条件

以下を満たすこと。

* 危険地域カードが表示される
* 津波 / 地震 / 雨雲 / キキクルの状態が要約される
* 危険地域リストが表示できる
* クリックで地図フォーカスできる
* 情報なしと取得失敗を区別できる
* `/live` E2E が PASS
* 既存ナビ代表 E2E が PASS
* 禁止ファイル未変更
* OSRM 依存なし

---

# 検証コマンド

```bash
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-main.js
test -f frontend/js/live/live-danger-summary.js && node --check frontend/js/live/live-danger-summary.js || true

npx playwright test e2e/live-basic.spec.js

npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

---

# 報告内容

完了後、以下を報告すること。

* 変更ファイル
* 実装内容
* 危険地域カードの表示仕様
* 危険地域ランキング仕様
* API 失敗時の表示仕様
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 禁止ファイル差分有無

```
```
