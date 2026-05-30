# Phase 3-D 地震 市区町村震度マーカー表示 検証

## 目的

Phase 3-D 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

- /live
- 地震情報レイヤー
- 市区町村震度マーカー
- 震度数字マーカー
- 代表地点マーカーフォールバック
- 回帰影響

---

## 検証項目

### 1. 構文確認

```bash
python3 -m compileall backend/app
node --check frontend/js/live/*.js
```

確認:

- SyntaxErrorなし
- ImportErrorなし
- JS構文エラーなし

---

### 2. Docker起動確認

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

### 3. 地震API確認

/live が利用する地震APIを確認する。

確認:

- HTTP 200
- 地震イベント取得可能
- 市区町村別震度データ取得可能
- intensity
- municipality
- prefecture
- lat/lng

が確認できること。

---

### 4. 市区町村震度マーカー表示確認

URL:

```text
http://127.0.0.1:8080/live.html
```

確認:

- 地震レイヤーONで市区町村震度マーカーが表示される
- 代表地点1つだけではなく複数マーカーが表示される
- 震度数字が見える
- OnHighGround2 本体と同等の震度数字マーカー表示である

---

### 5. レイヤーON/OFF確認

確認:

- 地震レイヤーONで表示
- OFFで非表示
- 再ONで復帰

---

### 6. ポップアップ確認

市区町村震度マーカーをクリックし、以下を確認する。

- 市区町村名
- 都道府県
- 震度
- 地震発生時刻
- 震源名
- マグニチュード

---

### 7. フォールバック確認

市区町村別震度データがないケースを確認する。

期待:

- JSエラーなし
- 代表地点マーカーが表示される
- 画面が壊れない

---

### 8. Console確認

確認:

- console errorなし
- page errorなし

---

### 9. 回帰確認

実施:

```bash
git diff --check
npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/live-tide-layer.spec.js
npx playwright test e2e/live-sun-moon-card.spec.js
```

可能であれば地震専用E2Eも確認する。

---

### 10. ナビ本体影響確認

URL:

```text
http://127.0.0.1:8080/
```

確認:

- 正常表示
- JSエラーなし
- /live 用地震APIの自動呼び出しなし

---

## レポート

作成先:

```text
tasks/live/live_phase3d_earthquake_municipality_markers_codex_verification.md
```

記載内容:

- 実施日時
- Docker状態
- API確認結果
- 市区町村震度データ確認結果
- マーカー表示確認結果
- レイヤーON/OFF確認結果
- ポップアップ確認結果
- フォールバック確認結果
- Console確認結果
- 回帰確認結果
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