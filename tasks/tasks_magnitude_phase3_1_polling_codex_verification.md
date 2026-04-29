# Magnitude Phase3-1 検証指示書（CODEX）
## 定期更新ポーリング対応

## 目的

Magnitudeモードで定期更新ポーリングが正しく動作することを検証する。

特に、Magnitude ON中のみ更新されること、OFF後にタイマーが残らないこと、手動更新・新着差分・震度フィルタ・距離ソート・地震タブUIと競合しないことを確認する。

---

## 検証対象

```text
Magnitude Phase3-1: 定期更新ポーリング
```

対象外:

```text
・WebSocket接続
・SSE接続
・プッシュ通知
・音声通知
・避難誘導連動
```

---

# 1. 事前確認

## 1.1 サーバ状態

```bash
docker compose ps
```

確認:

```text
・backend healthy
・frontend/nginx 起動
```

---

## 1.2 API確認

```bash
curl -s "http://localhost:8080/api/earthquakes?days=1" | python3 -m json.tool
```

確認:

```text
・HTTP 200
・items が配列
・event_id が存在
```

---

# 2. 初期表示確認

手順:

```text
1. ページをリロード
2. MagnitudeモードON
```

確認:

```text
・地震タブが表示される
・地震リストが表示される
・地震ピンが表示される
・最終更新時刻が表示される
・自動更新間隔が表示される、または自動更新中であることが分かる
・console error がない
```

---

# 3. 自動更新確認

検証では更新間隔を短縮できる場合、短縮して確認する。

手順:

```text
1. MagnitudeモードON
2. /api/earthquakes の呼び出し回数を監視
3. 更新間隔経過後に再取得されることを確認
```

確認:

```text
・一定間隔で /api/earthquakes が呼ばれる
・取得中表示が出る、または更新状態が分かる
・成功後に最終更新時刻が更新される
・地震ピン/リストが増殖しない
```

---

# 4. Magnitude OFF時の停止確認

手順:

```text
1. MagnitudeモードON
2. 自動更新が開始されたことを確認
3. MagnitudeモードOFF
4. 更新間隔以上待つ
```

確認:

```text
・OFF後に /api/earthquakes が呼ばれない
・OFF後に地震ピンが残らない
・タイマー由来のconsole errorがない
```

---

# 5. ON/OFF連続操作

手順:

```text
1. Magnitude ON/OFF を10回連続実行
2. その後Magnitude ONで一定時間待つ
```

確認:

```text
・API呼び出しが多重化しない
・タイマーが増殖しない
・MagnitudeパネルDOMが増殖しない
・地震ピンが増殖しない
・console error がない
```

---

# 6. 手動更新との競合確認

手順:

```text
1. MagnitudeモードON
2. 自動更新タイミング付近で手動更新を実行
```

確認:

```text
・同時に複数リクエストが走り続けない
・古いレスポンスで新しい表示が上書きされない
・新着判定が壊れない
・UIが二重更新状態にならない
```

---

# 7. 新着差分ハイライト連携

Playwright route などで2回目以降のレスポンスに新規 event_id を追加する。

確認:

```text
・ポーリング取得で新規event_idのみNEW表示される
・初回表示では全件NEWにならない
・新着件数が正しい
・新着ピンのみ強調される
・同じevent_idが繰り返しNEWにならない
```

---

# 8. 震度フィルタ連携

手順:

```text
1. MagnitudeモードON
2. 震度4以上を選択
3. 自動更新を発生させる
```

確認:

```text
・更新後も震度4以上フィルタが維持される
・フィルタ対象外の地震が表示されない
・新着件数はフィルタ後件数と一致する
```

---

# 9. ソート連携

手順:

```text
1. MagnitudeモードON
2. 近い順を選択
3. 自動更新を発生させる
```

確認:

```text
・更新後も近い順が維持される
・距離表示と並び順が矛盾しない
```

---

# 10. API失敗時確認

手順:

```text
1. 自動更新時に /api/earthquakes を503などで失敗させる
2. 次回更新では正常レスポンスを返す
```

確認:

```text
・失敗メッセージが表示される
・既存表示が壊れない
・タイマーが止まりっぱなしにならない
・次回正常取得で復帰する
・失敗によってタイマーが増殖しない
```

意図的な失敗時のconsole errorは許容してよい。  
通常系でconsole errorが出ないこと。

---

# 11. API遅延・非同期競合確認

可能であればAPIレスポンスを遅延させる。

確認:

```text
・取得中に次のポーリングが重ならない
・遅い古いレスポンスで最新表示が上書きされない
・OFF後に遅延レスポンスが返っても描画されない
```

---

# 12. ページ非表示/再表示確認

可能であれば `document.visibilityState` をモックする。

確認:

```text
・hidden中は不要な取得を抑制する、または仕様どおり停止する
・visible復帰時に更新される
・console error がない
```

---

# 13. 地震タブUI回帰確認

確認:

```text
・地震タブ内でリストが内部スクロールする
・スクロールしても地図が動かない
・スマホ表示で地図が見える
・リストクリックで地図が該当ピンへ移動する
```

---

# 14. Phase2回帰確認

確認:

```text
・避難所一時非表示/復元 OK
・新着差分ハイライト OK
・距離順ソート OK
・震度フィルタ OK
・XSS対策 OK
```

---

# 15. 既存機能回帰確認

通常モードで確認。

```text
・ハザードレイヤー表示
・避難所レイヤー表示
・避難所クラスタ表示
・現在地表示
・ナビ開始
・サイドパネル開閉
・右側ボタン群
```

---

# 16. 合格条件

```text
・Magnitude ON中だけ自動更新される
・Magnitude OFFで自動更新が止まる
・タイマー/DOM/ピン/イベントが増殖しない
・手動更新と競合しない
・API失敗後に次回更新で復帰する
・新着差分ハイライトがポーリングでも動く
・震度フィルタ/ソート状態が維持される
・地震タブUIが壊れない
・Phase2機能に回帰がない
・通常系でconsole errorがない
```

---

# 17. NG条件

```text
・OFF後もAPI取得が続く
・ポーリングが多重化する
・ピンやリストが増殖する
・古いレスポンスで最新表示が上書きされる
・API失敗後に復帰できない
・フィルタ/ソート状態が勝手に戻る
・地震タブのスクロール干渉が再発する
・避難所一時非表示が壊れる
```

---

# 18. 検証結果報告フォーマット

```md
# Magnitude Phase3-1 検証結果

## 結果
PASS / FAIL

## 確認内容
- 初期表示:
- 自動更新:
- OFF時停止:
- ON/OFF連続:
- 手動更新競合:
- 新着差分:
- 震度フィルタ連携:
- ソート連携:
- API失敗時:
- API遅延/非同期競合:
- visibilitychange:
- 地震タブUI回帰:
- Phase2回帰:
- 既存機能回帰:

## 発見した問題
- なし / あり

## 修正が必要な点
- なし / あり
```

---

# Magnitude Phase3-1 検証結果

## 結果
PASS

## 確認内容
- 初期表示: PASS（地震タブ、地震リスト、地震ピン、最終更新/自動更新ステータス表示）
- 自動更新: PASS（Magnitude ON中のみ `/api/earthquakes` を定期再取得）
- OFF時停止: PASS（OFF後に追加取得なし、リスト/ピン消去）
- ON/OFF連続: PASS（連続操作後もポーリング多重化なし、DOM増殖なし）
- 手動更新競合: PASS（全取得共通のin-flightガードで同時リクエスト増殖なし）
- 新着差分: PASS（ポーリングで新規event_idのみNEW、初回全件NEWなし）
- 震度フィルタ連携: PASS（更新後も震度4以上を維持、フィルタ後NEW件数に同期）
- ソート連携: PASS（更新後も近い順を維持、距離順表示）
- API失敗時: PASS（既存表示維持、エラー表示、次回正常取得で復帰）
- API遅延/非同期競合: PASS（遅延中に次取得を重ねない、OFF後描画ガード維持）
- visibilitychange: PASS（hidden中は取得抑制、visible復帰で即時更新）
- 地震タブUI回帰: PASS（内部スクロール、地図干渉なし、スマホ表示、クリック連動）
- Phase2回帰: PASS（避難所一時非表示、新着、距離順、震度フィルタ、XSS）
- 既存機能回帰: PASS（smoke/geolocation e2e 通過）

## 発見した問題
- あり: 検証時にポーリング間隔を短縮できる入口がなく、自動更新を安定してe2e検証しづらかった。
- あり: 手動更新とポーリングが近接した場合、全取得共通のin-flightガードがなく、重複リクエストの余地があった。

## 修正が必要な点
- 対応済み: `window.__MAGNITUDE_POLL_INTERVAL_MS` による検証用間隔上書きに対応。
- 対応済み: `_loadInFlight` を追加し、手動更新/ポーリング/visibility更新の取得重複を抑制。
- 対応済み: Phase3-1 の e2e 回帰テストを追加。

## 実行コマンド
- `docker compose ps`: backend healthy、frontend/nginx 起動を確認
- `curl -s "http://127.0.0.1:8080/api/earthquakes?days=1"`: HTTP 200、`items` 配列、`event_id` 存在を確認
- `npx playwright test e2e/magnitude-polling.spec.js`: 7 passed
- `npx playwright test e2e/magnitude-tab-ui.spec.js e2e/magnitude-sort.spec.js e2e/magnitude-intensity-filter.spec.js e2e/smoke.spec.js e2e/geolocation.spec.js`: 28 passed
