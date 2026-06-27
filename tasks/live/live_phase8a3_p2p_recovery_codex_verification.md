# Phase 8-A.3 P2P地震情報 limit 上限対応・市区町村震度マーカー復旧 — 検証レポート

## 判定

PASS。

P2P `limit=300` を `limit=100` に修正することで、P2P取得が復旧した。
`/api/live/earthquakes/history?days=3` が `source: "p2p"` を返すようになり、
66件中56件に `points` が含まれる。JMA fallback 機能は維持されている。

---

## 変更内容

### backend/app/services/earthquake_source_p2p.py

1. `_P2P_URL` の `limit=300` を `limit=100` に変更（定数化）

   ```python
   # 変更前
   _P2P_URL = "https://api.p2pquake.net/v2/history?codes=551&limit=300"

   # 変更後
   _P2P_HISTORY_LIMIT = 100
   _P2P_URL = f"https://api.p2pquake.net/v2/history?codes=551&limit={_P2P_HISTORY_LIMIT}"
   ```

2. `urllib.error` を import 追加

3. `_fetch_raw_sync()` — HTTPError を個別 catch し status/limit/reason をログ出力

   ```python
   except urllib.error.HTTPError as exc:
       logger.warning(
           "P2P 地震情報取得失敗: status=%d limit=%d reason=%s → fallbackへ",
           exc.code, _P2P_HISTORY_LIMIT, exc.reason,
       )
   ```

4. `fetch_earthquakes()` docstring を「最新 100 件」に更新

---

## P2P疎通結果

backend 再起動後のログ:

```text
P2P earthquake cache miss — fetched 100 entries
live/earthquakes/history: days=3 count=66 source=p2p
```

- `limit=400` は HTTP 400 なし（改修前の `limit=300` と同様の問題は回避）
- `limit=100` で HTTP 200、100件取得成功

---

## LIVE APIレスポンス確認

`GET /api/live/earthquakes/history?days=3`:

```json
{
  "source": "p2p",
  "fallback": false,
  "municipalityIntensityAvailable": true,
  "count": 66,
  "first": {
    "source": "p2pquake",
    "points": 4,
    "max_intensity": "1",
    "epicenter": "兵庫県南西部"
  }
}
```

- `source: "p2p"` ← 復旧
- `fallback: false` ← JMA fallbackなし
- `municipalityIntensityAvailable: true` ← 市区町村震度あり
- 66件中56件に `points` 有り

---

## /api/earthquakes?days=3 レスポンス

```json
{
  "count": 66,
  "first": {
    "source": "p2pquake",
    "points": 4,
    "max_intensity": "1"
  }
}
```

修正前は `count: 0` だったが、復旧後は `count: 66` になった。

---

## E2E テスト結果

```
npx playwright test e2e/live-eq-important.spec.js --project=chromium
26 passed (14.1s)
```

含むテスト:
- `getFallback() が false を返す（P2P成功時）` — PASS
- `getMuniAvailable() が true を返す（P2P成功時）` — PASS
- `P2P成功時にJMA fallbackノートが表示されない` — PASS
- JMA fallback 時の表示テスト — 全 PASS
- モバイル表示テスト — PASS

---

## 市区町村震度マーカー表示確認

- API上: 66件中56件に `points` あり
- `municipalityIntensityAvailable: true` が返っている
- フロント: `live-earthquake-layer.js` が最新地震1件の `points` を使って市区町村震度マーカーを描画する経路は変更なし
- 現在取得されている地震は震度1〜2程度のため `points` の数が少なく（例: 4〜19件）、地図全体ビューでは小マーカーが見えにくい可能性あり
- 表示経路自体（描画コード）は変更していないため、P2P復旧前と同じ描画ロジックが復活している

---

## PC/モバイルスクリーンショット

- Desktop (1440×900): `tasks/live/live_phase8a3_p2p_recovery_desktop.png`
- Mobile (390×844): `tasks/live/live_phase8a3_p2p_recovery_mobile.png`

地震マーカー複数表示確認。JMA fallback 注意文なし。表示崩れなし。

---

## 実行コマンド

```bash
python3 -m compileall backend/app/services/earthquake_source_p2p.py backend/app/api/live_earthquakes.py backend/app/services/earthquake_service.py
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-earthquake-layer.js
node --check frontend/js/live/live-alert-panel.js
docker compose restart backend
docker compose ps
docker compose logs backend --tail=20 | grep -E 'P2P|earthquake|p2p|fallback|cache'
curl -sS "http://127.0.0.1:8000/api/live/earthquakes/history?days=3" | jq '{source,fallback,municipalityIntensityAvailable,count,...}'
curl -sS "http://127.0.0.1:8000/api/earthquakes?days=3" | jq '{count,...}'
npx playwright test e2e/live-eq-important.spec.js --project=chromium
npx playwright screenshot ... desktop.png
npx playwright screenshot ... mobile.png
```

---

## 残課題

以下は今回解決しない。

- `limit=100` で3日分が不足する可能性（現状66件で3日分は概ね充足）
- P2P API の公式な limit 上限仕様の確認
- ページング対応
- 最新地震1件だけでなく、重要地震クリック・履歴選択時にその地震の市区町村震度マーカーへ切り替える機能
  → **Phase 8-A.4** として切り出し予定
- 市区町村震度マーカーが多数表示される大地震時のクラスタリング・ズーム制御

---

## 完了条件チェック

| 条件 | 結果 |
|------|------|
| `limit=300` を使わなくなっている | PASS |
| P2P取得がHTTP 200になる | PASS |
| `/api/live/earthquakes/history` が P2P を返す | PASS (`source: "p2p"`) |
| `points` 付き地震データが取得できる | PASS (56/66件) |
| 市区町村震度マーカーの経路が復活 | PASS (描画コード変更なし、データ供給復旧) |
| JMA fallback 機能が維持されている | PASS (E2E確認済み) |
| 既存の重要地震固定表示が壊れていない | PASS (26 E2E PASS) |
| `JMA fallback / 市区町村震度なし` 表示が必要時のみ出る | PASS |
| backend 再起動後の HTTP レスポンスで確認済み | PASS |
| PC/モバイルで表示崩れがない | PASS |
