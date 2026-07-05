# /live/stream OBS実配信リハーサル Runbook (Stream Phase 6-A)

## 1. 目的

`/live/stream` を OBS Browser Source / YouTube等での実配信リハーサルに使うための手順書。
新機能追加ではなく、これまで実装した画面を安全に公開前確認するためのものである。

## 2. 使用URL

本番想定URL(公開配信で使うのはこれのみ):

```text
http://127.0.0.1:8080/live/stream?chrome=off
```

本番ドメイン経由でも同じ path / query を使う:

```text
https://<domain>/live/stream?chrome=off
```

検証専用URL(本番配信には絶対に使わない):

```text
http://127.0.0.1:8080/live/stream?state=calm&chrome=off   … 静穏状態確認用
http://127.0.0.1:8080/live/stream?demo=1&chrome=off        … デモ表示確認用
```

`demo=1` / `focusSpeed=test` / `runtimeSpeed=test` は検証用パラメータであり、本番想定URLには
一切含めない。

## 3. OBS Browser Source 推奨設定

```text
URL:        http://127.0.0.1:8080/live/stream?chrome=off (または本番ドメイン)
幅:         1920
高さ:       1080
表示比率:   16:9
音声:       原則なし ("音声をミュートする" にチェック)
カスタムCSS: 追加しない (OBS側でCSS/HTMLを上書きしない)
シャットダウン時にソースを更新: 環境に応じて判断
ページ権限:  ローカルファイルアクセス等の追加権限は不要
```

OBSのバージョンや配置環境によって設定項目名が異なる場合がある。ビットレート等の配信品質
設定はYouTube側の推奨値や回線環境に依存するため、本Runbookでは断定しない。

## 4. リハーサル手順

### 4-1. ローカル準備

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream?chrome=off
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

すべて 200 OK、`backend`/`martin` が healthy、`frontend` が Up であることを確認する。

### 4-2. 通常ブラウザ確認

```text
1. Chrome で http://127.0.0.1:8080/live/stream?chrome=off を開く
2. ウィンドウ/ビューポートを 1920x1080 相当にする
3. スクリーンショットを保存する
4. DevTools の Console / Network タブで pageerror・console error・failed request を確認する
5. window.__LiveStreamDiagnostics.getSnapshot() をConsoleで実行し、内容を確認する
```

### 4-3. OBS Browser Source 確認

```text
1. OBSを起動する
2. ソース一覧から Browser を追加する
3. URL に本番想定URLを指定する
4. 幅 1920 / 高さ 1080 を指定する
5. 音声はミュートにする
6. OBSプレビューで画面が正しく収まって表示されることを確認する
```

### 4-4. 30分以上のリハーサル

```text
1. 開始時 (0分) のスクリーンショットを保存する
2. 15分経過時点のスクリーンショットを保存する
3. 30分経過時点のスクリーンショットを保存する
4. 各時点で window.__LiveStreamDiagnostics.getSnapshot() を保存する
5. OS標準のタスクマネージャ/アクティビティモニタでCPU・メモリを目視確認する
```

自動化する場合は `tools/live_stream_obs_rehearsal_probe.js` を使う。

```bash
node tools/live_stream_obs_rehearsal_probe.js \
  --url "http://127.0.0.1:8080/live/stream?chrome=off" \
  --minutes 30 \
  --interval 300 \
  --output test-results/live-stream-phase6a-obs-rehearsal-diagnostics.json \
  --screenshot-dir test-results
```

このprobeはOBS実機の完全な代替ではない。OBS実機確認ができない場合は、その旨を明記した上で
`PASS with notes` として扱う。

### 4-5. 限定公開/非公開相当の配信テスト

```text
1. 配信プラットフォーム側の公開範囲設定を必ず確認する (限定公開 / 非公開 / テスト配信相当)
2. 通知が飛ばない設定になっているか確認する
3. 数分間だけ配信する
4. 視聴側の画面で文字・ticker・地図が読めることを確認する
5. 配信停止手順を事前に確認してから開始する
```

いきなり公開配信にはしない。公開運用そのものの自動化は Phase 6-A の対象外。

## 5. 監視ポイント

```text
画面が白画面化していないか
文字が読めるか (ticker含む)
地図(中央・小画面)が表示されているか
小画面のレイアウトが崩れていないか
demo/testの表示物が混入していないか
時計が進んでいるか
自動巡回(focus)が詰まっていないか
音声が混入していないか
```

## 6. 異常時の停止・復旧手順

```text
1. OBS側でBrowser Sourceを非表示にする、または配信自体を停止する
2. 配信プラットフォーム側で配信/公開を停止する
3. ブラウザタブ/OBSソースをリロードする (F5相当。Browser Sourceは右クリック→更新)
4. リロードしても改善しない場合は docker compose ps でコンテナ状態を確認する
5. 必要に応じて docker compose restart backend / frontend を検討する
   (安易な再起動は避け、まず原因箇所を切り分けること)
6. 復旧後、本Runbookの 4-2 (通常ブラウザ確認) を再実施してから配信を再開する
```

## 7. 公開前チェックリスト

`tasks/live/live_stream_phase6a_public_preflight_checklist.md` を参照する。

## 8. 判定基準

以下を満たせば配信リハーサル可能と判断する。

```text
本番想定URL(?chrome=off)が表示できる
本番想定URLで dataMode=real である (demo/testが混入していない)
1920x1080に主要UIが収まっている
30分以上の表示で白画面化・pageerror・console errorの急増がない
Leaflet container / ticker node / railway layer が増殖しない
marker が単調増加し続けない
runtimeState が実態(取得成功/失敗)と合っている
```

以下に該当する場合はFAILとし、公開しない。

```text
本番想定URLが表示できない
OBSプレビューで白画面になる
pageerrorが出る
demo/test状態が本番想定URLに混入する
/live 本体に副作用が出ている
```

## 9. 既知のnotes

```text
- protomaps-leaflet (PMTiles描画ライブラリ) 内部由来の "TypeError: Failed to fetch" が
  低頻度で console error として観測されることがある (Phase 5-C で調査済み)。
  ライブラリ内部の console.error 呼び出しのため、アプリ側からの完全な抑制はできない。
  pageerrorにはならず、画面表示・ticker・focus・地図の継続動作には影響しないことを確認済み。
- タイル/PMTiles由来の requestfailed (net::ERR_ABORTED 等) は、ズーム変更時の正常な
  リクエスト中断でも発生し得る。画面破綻を伴わなければ許容する。
- OBS実機/YouTube実配信は環境依存が大きいため、可能な範囲で実施し、未実施の場合はその旨を
  検証レポートに明記した上で PASS with notes として扱う。
```
