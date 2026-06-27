# Phase 8-A.2 P2P地震詳細取得失敗・JMA fallback常態化調査

## 判定

PASS。

P2P 地震情報 API 自体は稼働しており、市区町村震度 `points` も返っている。ただし LIVE / 既存 `/api/earthquakes` が使う P2P URL の `limit=300` が現在の P2P API で HTTP 400 になり、`fetch_earthquakes()` が空配列を返すため、LIVE 履歴 API は JMA fallback に常態化している。

## 原因カテゴリ

C. timeout / retry 設計問題に近いが、実態は外部 API パラメータ不整合。

分類としては **A. 外部P2Pサービス仕様変更または仕様上限への未追従** と **D ではない取得前エラー**。`limit=100` は成功し、`limit=300` のみ 400 になるため、timeout・DNS・TLS・パース失敗ではない。

## 再現状況

- 稼働中 backend / frontend は起動済み。
- `/api/live/earthquakes/history?days=3` は `source: "jma"`、`count: 30` を返す。
- `/api/earthquakes?days=3` は `count: 0` を返す。
- backend log には `P2P 地震情報取得失敗: HTTP Error 400: Bad Request` の直後、`P2P empty, falling back to JMA` が出る。

## P2P疎通結果

- ホストから `https://api.p2pquake.net/v2/history?codes=551&limit=300`: HTTP 400、本文なし。
- ホストから `limit=100`: HTTP 200、JSON、100件。
- ホストから `limit=10`: HTTP 200、JSON、市区町村震度 `points` あり。
- backend コンテナ内からも同じ。
  - `limit=300`: HTTPError 400、約 0.05 秒。
  - `limit=100`: 200、約 0.22 秒。

`limit=100` の要約:

```json
{
  "count": 100,
  "first": {
    "code": 551,
    "issue_type": "DetailScale",
    "maxScale": 10,
    "points": 4
  },
  "detailScale_count": 73,
  "with_points": 89
}
```

## LIVE APIレスポンス確認結果

`http://127.0.0.1:8000/api/live/earthquakes/history?days=3`:

- top-level keys: `count`, `days`, `items`, `source`, `updated_at`
- `source`: `jma`
- `count`: 30
- 先頭 item: `source: "jma"`, `points` なし、`intensity_areas` あり

注意: ワークツリー上の `backend/app/api/live_earthquakes.py` は `fallback` と `municipalityIntensityAvailable` を返す実装だが、稼働中 HTTP レスポンスには出ていない。コンテナ内で同関数を直接 import して呼ぶと `fallback=True`, `municipalityIntensityAvailable=False` が返るため、稼働中 uvicorn プロセスが古いロード済みコードを保持している可能性が高い。

`http://127.0.0.1:8080/api/live/earthquakes`:

- 404 Not Found。
- 実ルートは `/api/live/earthquakes/history?days=3`。

## backendログ確認結果

確認できた主要ログ:

```text
P2P 地震情報取得失敗: HTTP Error 400: Bad Request
live/earthquakes/history P2P empty, falling back to JMA
live/earthquakes/history JMA fallback: days=3 count=30
live/earthquakes/history: days=3 count=30 source=jma
earthquakes: days=3 count=0
```

## キャッシュ確認結果

`backend/app/services/earthquake_source_p2p.py`:

- `_CACHE_TTL = 60`
- 成功時のみ `_cache = {"data": data, "ts": now}`。
- 取得失敗時はキャッシュがあれば stale cache を返す。
- 現状は `limit=300` が継続的に 400 のため、プロセス起動後に成功キャッシュがない場合は毎回空配列になり、LIVE は JMA fallback へ落ちる。
- JMA fallback 結果を P2P キャッシュとして保存する経路は見当たらない。

## フロント描画経路確認結果

`frontend/js/live/live-layers.js`:

- `/api/live/earthquakes/history?days=3` を取得。
- 成功時は `data.items` を `_eqData` に入れる。
- 最新地震 1 件だけ `window.liveEarthquakeLayer.render(latest, true)` で市区町村震度マーカー描画を試みる。
- `points` がない、座標辞書未ロード、座標解決不可の場合は代表地点マーカーに fallback。

`frontend/js/live/live-earthquake-layer.js`:

- `event.points` の `pref` / `addr` / `scale` を使う。
- `/data/municipality_coords.json` で座標解決。
- JMA fallback item には `points` がないため、市区町村震度マーカーは出ない。

## OnHighGround2本体との差分

LIVE 履歴 API と既存 `/api/earthquakes` はどちらも `app.services.earthquake_service.get_recent_earthquakes()` を使い、さらに `earthquake_source_p2p.fetch_earthquakes()` に依存する。

したがって「本体は P2P 成功、LIVE だけ失敗」ではない。既存 `/api/earthquakes?days=3` も同じ P2P `limit=300` で失敗し、`count: 0` になっている。

過去 Phase 3-D の検証では、P2P `points` が取得できる場合に LIVE 側の市区町村震度マーカー描画は成立していた。現在の問題は描画より前の P2P 取得 URL にある。

## 推奨対応案

1. `backend/app/services/earthquake_source_p2p.py` の `_P2P_URL` を `limit=100` 以下に変更する。
2. 必要件数が 100 を超える場合は、P2P API の現行仕様に合わせてページング等の正規手段を確認してから実装する。
3. HTTP 400 の場合は timeout と同じ扱いにせず、URL/パラメータ異常としてログに status と URL パラメータを出す。
4. LIVE 履歴 API の `fallback` / `municipalityIntensityAvailable` が稼働中 HTTP に出ていないため、backend 再起動後に再確認する。
5. `municipalityIntensityAvailable` は `source == "p2p"` だけでなく、少なくとも item に有効な `points` があるかも見て判定すると表示実態に近い。

## 追加調査が必要な内容

- P2P v2 history の現在の `limit` 上限の公式確認。
- `limit=100` にした場合、3日履歴として件数が足りるか。
- backend 再起動後に `/api/live/earthquakes/history?days=3` の `fallback` / `municipalityIntensityAvailable` が HTTP レスポンスへ出るか。
- P2P 復旧後、最新地震だけでなく重要地震・選択地震の市区町村震度も描くべきか。

## 実行したコマンド

```bash
git status --short
docker compose ps
docker compose logs backend --tail=300
docker compose logs backend --tail=600 | rg -i 'P2P|earthquakes/history|earthquakes: days|jma fallback|HTTP Error 400|cache miss|stale cache'
python3 -m compileall backend/app/api/live_earthquakes.py
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
curl -sS 'http://127.0.0.1:8000/api/live/earthquakes/history?days=3'
curl -sS 'http://127.0.0.1:8080/api/live/earthquakes/history?days=3'
curl -i 'http://127.0.0.1:8080/api/live/earthquakes'
curl -sS 'http://127.0.0.1:8000/api/earthquakes?days=3' | jq '{count, first:{event_id:.items[0].event_id, source:.items[0].source, points:(.items[0].points|length), max_intensity:.items[0].max_intensity}}'
curl -sS 'http://127.0.0.1:8000/api/earthquakes/recent?limit=3' | jq '{source, count:(.events|length), first:{event_id:.events[0].event_id, source:.events[0].source, intensity_areas:(.events[0].intensity_areas|length)}}'
curl -i 'https://api.p2pquake.net/v2/history?codes=551&limit=300'
curl -i 'https://api.p2pquake.net/v2/history?codes=551&limit=100'
curl -i 'https://api.p2pquake.net/v2/history?codes=551&limit=10'
curl -sS 'https://api.p2pquake.net/v2/history?codes=551&limit=100' | jq '{count:length, first:{id:.[0].id, code:.[0].code, issue_type:.[0].issue.type, maxScale:.[0].earthquake.maxScale, points:(.[0].points|length), sample_point:.[0].points[0]}, detailScale_count:map(select(.issue.type=="DetailScale"))|length, with_points:map(select((.points|length)>0))|length}'
docker compose exec backend python -c "..."
npx playwright test e2e/live-eq-important.spec.js --project=chromium
```

## 変更したファイル

- `tasks/live/live_phase8a2_p2p_earthquake_investigation.md`
  - 調査レポート作成のみ。

本実装、fallback 条件、timeout、UI、E2E 期待値は変更していない。

## 検証

- `python3 -m compileall backend/app/api/live_earthquakes.py`: PASS
- `node --check frontend/js/live/live-layers.js`: PASS
- `node --check frontend/js/live/live-alert-panel.js`: PASS
- `npx playwright test e2e/live-eq-important.spec.js --project=chromium`: 26 passed
