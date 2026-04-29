# Magnitude Phase2-3 検証指示書（CODEX）
## 現在地から近い順ソート対応

## 目的

Magnitudeモードの地震リストで「新しい順」と「現在地から近い順」を切り替えられることを検証する。

また、Phase2-1 の避難所一時非表示、Phase2-2 の新着ハイライトに回帰がないことを確認する。

---

## 検証対象

```text
Magnitude Phase2-3: 現在地から近い順ソート
```

対象外:

```text
・震度フィルタ
・WebSocketリアルタイム受信
・自動ポーリング
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
2. MagnitudeモードをON
```

確認:

```text
・地震リストが表示される
・ソート切替UIが表示される
・初期状態は新しい順
・地震ピンが表示される
・console error がない
```

---

# 3. 新しい順ソート確認

モック可能であれば、以下のように発生時刻が異なるデータを用意する。

```json
{
  "items": [
    {
      "event_id": "eq-old",
      "occurred_at": "2026-04-29T09:00:00+09:00",
      "epicenter_name": "古い地震",
      "lat": 35.0,
      "lng": 139.0,
      "magnitude": 3.0,
      "max_intensity": "2",
      "source": "mock"
    },
    {
      "event_id": "eq-new",
      "occurred_at": "2026-04-29T10:00:00+09:00",
      "epicenter_name": "新しい地震",
      "lat": 36.0,
      "lng": 140.0,
      "magnitude": 4.0,
      "max_intensity": "3",
      "source": "mock"
    }
  ]
}
```

確認:

```text
・新しい地震が上に表示される
・古い地震が下に表示される
```

---

# 4. 近い順ソート確認

現在地をモック、またはブラウザの位置情報を固定する。

例:

```text
現在地: 東京駅付近
lat=35.681236
lng=139.767125
```

モックデータ例:

```json
{
  "items": [
    {
      "event_id": "eq-far",
      "occurred_at": "2026-04-29T10:00:00+09:00",
      "epicenter_name": "遠い地震",
      "lat": 40.0,
      "lng": 141.0,
      "magnitude": 4.0,
      "max_intensity": "3",
      "source": "mock"
    },
    {
      "event_id": "eq-near",
      "occurred_at": "2026-04-29T09:00:00+09:00",
      "epicenter_name": "近い地震",
      "lat": 35.7,
      "lng": 139.8,
      "magnitude": 3.0,
      "max_intensity": "2",
      "source": "mock"
    }
  ]
}
```

手順:

```text
1. MagnitudeモードON
2. 近い順を選択
```

確認:

```text
・近い地震が上に表示される
・遠い地震が下に表示される
・距離表示が並び順と矛盾しない
```

---

# 5. 現在地なし確認

位置情報を拒否、または現在地未取得状態で確認する。

確認:

```text
・近い順ボタンがdisabledになる、または説明表示される
・近い順を押してもJSエラーが出ない
・新しい順表示は維持される
・UIが崩れない
```

---

# 6. lat/lngなし地震確認

モックデータに lat/lng が null の地震を含める。

確認:

```text
・新しい順では通常表示される
・近い順では距離不明の地震が末尾に回る
・距離表示が未取得/非表示になる
・JSエラーが出ない
```

---

# 7. リストクリック連動確認

各ソートモードで確認する。

```text
・新しい順でリストクリック → 該当ピンへ移動、ポップアップ表示
・近い順でリストクリック → 該当ピンへ移動、ポップアップ表示
・選択状態が1件だけ付与される
```

---

# 8. Phase2-2 新着ハイライト回帰確認

モックで新規 event_id を追加する。

確認:

```text
・再取得時に新規event_idのみNEWになる
・近い順でもNEWバッジが表示される
・新着件数表示が壊れない
・新着ピン強調が壊れない
・同じevent_idが繰り返しNEWにならない
```

---

# 9. API再取得後のソート維持

手順:

```text
1. MagnitudeモードON
2. 近い順を選択
3. 更新操作を実行
```

確認:

```text
・再取得後も近い順のまま
・新しい順に勝手に戻らない
・NEW判定が壊れない
```

---

# 10. Phase2-1 避難所一時非表示回帰確認

確認:

```text
・避難所ON状態でMagnitude ON → 避難所ピン/広域クラスタ非表示
・Magnitude OFF → 避難所復元
・避難所OFF状態でMagnitude ON/OFF → OFF維持
・非同期の避難所取得戻りでゾンビ復活しない
```

---

# 11. 連続操作・増殖確認

手順:

```text
1. Magnitude ON/OFF を10回連続実行
2. ソート切替を複数回実行
3. 更新操作も複数回実行
```

確認:

```text
・MagnitudeパネルDOMが増殖しない
・地震リストDOMが重複しない
・地震ピンが増殖しない
・クリックイベントが多重登録されない
・選択状態は常に1件
・console error がない
```

---

# 12. XSS回帰確認

モック可能な場合、以下の文字列を epicenter_name に入れる。

```html
<img src=x onerror=alert(1)>
```

確認:

```text
・HTMLとして実行されない
・文字列として安全に表示される
・ソート切替後もXSS対策が維持される
```

---

# 13. 既存機能回帰確認

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

# 14. 合格条件

以下をすべて満たすこと。

```text
・初期表示が新しい順
・新しい順/近い順を切り替えられる
・近い順で距離が近い地震が上に来る
・現在地なしでもUIが破綻しない
・lat/lngなし地震が近い順で末尾に回る
・リストクリックとピン連動が両ソートで動く
・API再取得後もソート状態を維持する
・Phase2-2のNEW表示が壊れていない
・Phase2-1の避難所一時非表示が壊れていない
・DOM/ピン/イベントが増殖しない
・XSS対策が維持されている
```

---

# 15. NG条件

以下が1つでもあれば不合格。

```text
・近い順で距離順にならない
・現在地なしでJSエラーが出る
・lat/lngなし地震でソートが落ちる
・ソート切替でピンが増殖する
・リストクリックが別のピンを開く
・API再取得でソートが勝手に戻る
・NEW表示が壊れる
・避難所一時非表示が壊れる
・XSSが再発する
```

---

# 16. 検証結果報告フォーマット

```md
# Magnitude Phase2-3 検証結果

## 結果
PASS / FAIL

## 確認内容
- 初期表示:
- 新しい順:
- 近い順:
- 現在地なし:
- lat/lngなし:
- リストクリック連動:
- Phase2-2回帰:
- API再取得後のソート維持:
- Phase2-1回帰:
- 連続操作:
- XSS確認:
- 既存機能回帰:

## 発見した問題
- なし / あり

## 修正が必要な点
- なし / あり
```

---

# Magnitude Phase2-3 検証結果

## 結果
PASS

## 確認内容
- 初期表示: PASS（新しい順がactive、発生時刻降順）
- 新しい順: PASS（新しい地震が上、古い地震が下）
- 近い順: PASS（現在地から近い地震が上、距離不明は末尾）
- 現在地なし: PASS（近い順disabled、説明表示、新しい順維持）
- lat/lngなし: PASS（新しい順では表示、近い順では末尾、距離非表示）
- リストクリック連動: PASS（選択状態は1件、該当event_idでfocusEarthquakePin呼び出し）
- Phase2-2回帰: PASS（NEWバッジ、新着件数用newIds、新着リング描画を維持）
- API再取得後のソート維持: PASS（近い順選択後の再描画でも近い順維持）
- Phase2-1回帰: PASS（既存の避難所一時非表示ガードを維持、smoke/geolocation回帰確認）
- 連続操作: PASS（再描画時にリストイベントを付け直し、ピンはclear後に再描画して増殖なし）
- XSS確認: PASS（epicenter_name / max_intensity はescapeHtmlで文字列表示）
- 既存機能回帰: PASS（smoke/geolocation e2e 10件通過）

## 発見した問題
- あり: `lat/lng: null` が `Number(null) === 0` により有効座標扱いされ、距離表示・ピン描画対象になる問題を検出。
- あり: `magnitude` が文字列で返った場合に `toFixed` 前提で落ちる可能性を検出。

## 修正が必要な点
- 対応済み: 現在地・地震座標の有効判定を `null` 除外 + finite number 判定に変更。
- 対応済み: magnitude 表示・ピン半径計算で数値変換してから扱うよう修正。
- 対応済み: Magnitude Phase2-3 の e2e 回帰テストを追加。

## 実行コマンド
- `docker compose ps`: backend healthy、frontend/nginx 起動を確認
- `curl -s "http://127.0.0.1:8080/api/earthquakes?days=1"`: HTTP 200、`items` 配列、`event_id` 存在を確認
- `npx playwright test e2e/magnitude-sort.spec.js`: 6 passed
- `npx playwright test e2e/smoke.spec.js e2e/geolocation.spec.js`: 10 passed
