# Phase 3-C 観察・調整 検証指示書

## 目的

Phase 3-C により、`/live` の雨雲・キキクル・危険地域ランキングを観察できる状態になっているか検証する。

実装修正は禁止。

検証・調査・レポート作成のみ実施すること。

---

## 検証対象

- `/live`
- `/api/live/summary`
- 雨雲危険地域
- キキクル危険地域
- dangerous_areas
- 観察ログ
- 既存回帰テスト

---

## 検証項目

### 1. 構文確認

実施:

```bash
python -m compileall backend/app
node --check frontend/js/live/*.js
```

期待:

- SyntaxErrorなし
- ImportErrorなし
- JS構文エラーなし

---

### 2. Docker起動確認

実施:

```bash
docker compose build backend frontend
docker compose up -d
```

確認:

- backend healthy
- frontend healthy
- `/health` が HTTP 200
- `/live.html` が HTTP 200

---

### 3. `/api/live/summary` 確認

実施:

```bash
curl -s http://127.0.0.1:8000/api/live/summary
```

確認:

- HTTP 200
- JSONとして妥当
- `rain`
- `kikikuru`
- `dangerous_areas`

が存在すること。

---

### 4. 観察ログ確認

backend logs で以下が確認できること。

```text
live summary observation
```

雨雲:

```text
live rain observation
```

キキクル:

```text
live kikikuru observation
```

同一地域重複がある場合:

```text
live duplicate area observation
```

---

### 5. 件数確認

確認項目:

- rain area count
- kikikuru area count
- dangerous area count
- areas上限

期待:

- `dangerous_areas` は5件以内
- `rain.areas` は5件以内
- `kikikuru.areas` は既存仕様内
- 件数がログとAPIで矛盾しない

---

### 6. false-safe確認

確認:

- unknown が danger になっていない
- データ取得失敗が danger 扱いされていない
- threshold未満の雨雲が dangerous_areas に出ていない
- キキクル unknown / unavailable が危険断定されていない

---

### 7. UI確認

Playwright またはブラウザで `/live` を確認。

期待:

- 危険地域カードが表示される
- 雨雲エリアが表示される
- キキクルエリアが表示される
- 表示崩れなし
- JS console errorなし

---

### 8. 回帰確認

実施:

```bash
pytest
npx playwright test e2e/live-basic.spec.js
git diff --check
```

期待:

- pytest 成功
- live E2E 成功
- whitespace errorなし

---

### 9. ナビ本体影響確認

最低限以下を確認する。

- `/` が表示できる
- 既存ナビ画面で JS error が出ていない
- `/live` 用変更が `frontend/index.html` 側へ不要に混入していない

---

## レポート作成

以下へ検証レポートを作成する。

```text
tasks/live/live_phase3c_observation_tuning_codex_verification.md
```

記載内容:

- 実施日時
- 検証環境
- API確認結果
- 観察ログ確認結果
- rain area 件数
- kikikuru area 件数
- dangerous_areas 件数
- false-safe確認結果
- UI確認結果
- 回帰テスト結果
- ナビ本体影響確認
- 最終判定

判定は以下のいずれか。

- PASS
- PASS with notes
- FAIL