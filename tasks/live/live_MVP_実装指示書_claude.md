# /live MVP 実装指示書（Claude Code向け）

## 最重要

実装開始前に必ず以下を読むこと。

* docs/live/DEVELOPMENT_GUARDRAILS.md
* AGENTS.md
* CLAUDE.md
* frontend/js/live/README.md

既存ナビ本体への影響は禁止。

live は OnHighGround2 内に存在するが、設計上は半独立アプリとして扱うこと。

---

# 目的

全国のリアルタイム災害情報を俯瞰するための `/live` MVP を実装する。

これは避難ナビではない。

目的は:

```text
全国で今どこに何が起きているかを把握すること
```

---

# 実装対象

## 新規ページ

```text
/frontend/live.html
```

既存 `index.html` に live UI を混ぜないこと。

---

# ディレクトリ構成

作成対象:

```text
frontend/
├─ live.html
├─ css/
│  └─ live/
│     └─ live.css
├─ js/
│  ├─ live/
│  │  ├─ live-main.js
│  │  ├─ live-map.js
│  │  ├─ live-layers.js
│  │  ├─ live-alert-panel.js
│  │  └─ live-ui.js
│  └─ shared/
│     └─ （必要最小限のみ）
```

backend 側:

```text
backend/app/api/live_*.py
backend/app/services/live_*.py
```

---

# 絶対禁止

以下を live 実装のために改変しないこと。

```text
frontend/index.html
frontend/js/navigation.js
frontend/js/nav-*.js
frontend/js/location-info-panel.js
frontend/js/hazard-layers.js
既存 reroute 処理
既存 bottom panel
```

---

# MVP 実装範囲

## 1. 全国地図表示

初期表示:

```text
日本全体が見えるズーム
```

地図ライブラリは既存構成に合わせる。

既存 map utility の利用は OK。

---

## 2. 雨雲レイヤー

既存 nowcast / rain tile 資産を利用してよい。

ただし:

* navigation 用 state を利用しない
* nav UI に依存しない

live 専用 layer controller を作ること。

---

## 3. キキクル系レイヤー

既存 backend / tile / ingest 資産を利用してよい。

ただし:

* live 用 layer toggle に分離
* nav hazard toggle と state を共有しない

---

## 4. 地震簡易表示

最低限:

* recent earthquake marker
* magnitude
* intensity
* 発生時刻

を表示。

既存地震 API 利用は OK。

ただし live 専用 UI とする。

---

## 5. 津波簡易表示

最低限:

* 津波警報
* 津波注意報
* 対象エリア

を表示。

既存津波 API / adapter 利用は OK。

---

## 6. レイヤー切替 UI

最低限:

* rain
* kikikuru
* earthquake
* tsunami

の ON/OFF を実装。

UI は simple でよい。

---

## 7. アクティブ警戒カード

画面上に active alert card を表示。

最低限:

* 津波警報中件数
* 地震件数
* 強雨域有無

程度でよい。

初期は簡易集計でよい。

---

# UI 方針

重要:

```text
全国俯瞰を最優先
```

避難ナビ UI を流用しない。

---

## MVP UI 優先順位

優先:

* 地図の見やすさ
* 全国状況の把握
* 軽さ
* レイヤー切替

不要:

* ルート探索
* bottom panel
* reroute
* 避難誘導 UI
* 詳細フォーム

---

# 技術方針

## OSRM

/live は OSRM に依存しない。

ルート探索機能を実装しない。

---

## Vector Tile 優先

大量データは GeoJSON 直読みを避ける。

可能な限り Martin vector tile を使う。

---

## state 分離

live 用 state を navigation.js に持たせない。

live 内で閉じること。

---

## shared ルール

shared は:

```text
nav と live の両方で使うことが確定したもののみ
```

を置く。

live 専用 utility は live/ に置くこと。

---

# 実装品質

## 必須

* JS syntax error 無し
* backend import error 無し
* Docker build 成功
* backend health OK
* frontend health OK

---

# E2E

以下を追加:

```text
e2e/live-basic.spec.js
```

最低確認:

* /live 表示成功
* map 初期化成功
* layer toggle 動作
* JS console error 無し

---

# 回帰防止

既存ナビ E2E を必ず実行すること。

live 実装によって既存避難ナビが壊れていないことを確認すること。

---

# MVP 完了条件

以下を満たすこと。

* /live が単独ページとして動作
* 全国地図表示
* rain layer 表示
* kikikuru layer 表示
* earthquake 表示
* tsunami 表示
* active alert card 表示
* 既存ナビ無改変
* 既存ナビ回帰無し

---

# 実装姿勢

重要なのは:

```text
最初から完璧を作ることではなく、
全国監視ビューアの独立構造を成立させること
```

まずは:

```text
軽量
分離
壊さない
```

を優先すること。
