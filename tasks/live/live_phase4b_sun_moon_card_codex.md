# Phase 4-B 日月情報カード 検証

## 目的

Phase 4-B 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

- /live
- 日月情報カード
- 日月API
- 表示内容
- 回帰影響

---

## 検証項目

### 1. 構文確認

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

### 2. Docker起動確認

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

### 3. API確認

実施:

```bash
curl -i http://127.0.0.1:8000/api/live/sun-moon
```

確認:

- HTTP 200
- sunrise
- sunset
- moonrise
- moonset
- moon_phase

が返ること。

---

### 4. カード表示確認

URL:

```text
http://127.0.0.1:8080/live.html
```

確認:

- 日月情報カード表示
- レイアウト崩れなし

---

### 5. 表示内容確認

確認項目:

```text
日の出
日の入り
月の出
月の入り
月齢
```

期待:

- 値が表示される
- 空欄でない

---

### 6. API失敗時確認

確認:

- エラー表示
- JS例外なし
- 無限リトライなし

期待:

```text
取得できません
```

表示。

---

### 7. Console確認

確認:

- console error なし
- page error なし

---

### 8. 回帰確認

実施:

```bash
git diff --check
```

実施:

```bash
npx playwright test e2e/live-basic.spec.js
```

実施:

```bash
npx playwright test e2e/live-tide-layer.spec.js
```

確認:

- 成功
- 既存live機能に影響なし

---

### 9. ナビ本体影響確認

URL:

```text
http://127.0.0.1:8080/
```

確認:

- 正常表示
- JSエラーなし
- 日月API自動呼び出しなし

---

## レポート

作成先:

```text
tasks/live/live_phase4b_sun_moon_card_codex_verification.md
```

記載内容:

- 実施日時
- Docker状態
- API結果
- カード表示結果
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