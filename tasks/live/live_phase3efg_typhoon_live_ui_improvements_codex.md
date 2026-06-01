# Phase 3-EFG 台風時ライブ監視UI改善 検証

## 目的

Phase 3-EFG 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

E:
- キキクル危険地域カード

F:
- 地震一覧
- 地図フォーカス

G:
- 雨雲レイヤー視認性

---

# 1. 構文確認

実施:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/*.js
```

確認:

- SyntaxErrorなし
- ImportErrorなし
- JS構文エラーなし

---

# 2. Docker起動確認

実施:

```bash
docker compose build
docker compose up -d
docker compose ps
```

確認:

- backend healthy
- frontend Up
- martin healthy

---

# 3. E: キキクル危険地域カード確認

実ブラウザ:

```text
/live.html
```

確認:

- 地図上にキキクル表示あり
- 危険地域カードにも反映される

台風時データが存在する場合:

- 沖縄
- 奄美

などを確認する。

---

## API確認

確認対象:

```text
/api/live/summary
```

確認:

- kikikuru areas
- dangerous_areas

が整合していること。

---

## false-safe確認

確認:

- unavailable
- unknown

が danger 扱いされていない。

---

# 4. F: 地震一覧確認

実ブラウザ:

```text
/live.html
```

確認:

- 地震件数表示
- タップ可能

---

## 一覧確認

確認:

- 地震イベント一覧表示
- 発生時刻
- 震源名
- M
- 最大震度

表示されること。

---

## 地図フォーカス確認

一覧項目クリック:

確認:

- 対象地震へ移動
- 適切なズーム
- ポップアップ表示

---

# 5. G: 雨雲レイヤー視認性確認

確認:

- 雨雲表示あり
- 地名確認可能
- 地図視認性改善

比較:

- 修正前
- 修正後

スクリーンショット取得

---

# 6. Console確認

確認:

- console errorなし
- page errorなし

---

# 7. 回帰確認

実施:

```bash
git diff --check
```

実施:

```bash
npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/live-earthquake-layer.spec.js
npx playwright test e2e/live-sun-moon-card.spec.js
npx playwright test e2e/live-tide-layer.spec.js
```

可能なら追加された地震一覧E2Eも確認する。

---

# 8. ナビ本体影響確認

URL:

```text
http://127.0.0.1:8080/
```

確認:

- 正常表示
- console errorなし
- page errorなし

---

# レポート

作成先:

```text
tasks/live/live_phase3efg_typhoon_live_ui_improvements_codex_verification.md
```

記載内容:

- 実施日時
- Docker状態
- キキクル整合性確認
- 地震一覧確認
- 地図フォーカス確認
- 雨雲視認性確認
- Console確認
- 回帰確認
- ナビ本体影響確認
- スクリーンショット
- 最終判定

判定:

```text
PASS
PASS with notes
FAIL
```

のいずれかを明記すること。