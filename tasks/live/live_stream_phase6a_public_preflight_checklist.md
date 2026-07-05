# /live/stream 公開前チェックリスト (Stream Phase 6-A)

配信/公開の直前に、上から順にすべてチェックする。1つでも✗があれば公開しない。

## 画面

```text
[ ] /live/stream?chrome=off が表示できる
[ ] 1920x1080 に主要UIが収まっている
[ ] 文字が読める(小画面・パネル含む)
[ ] ticker(下部テロップ)が読める
[ ] 地図(中央・小画面)が白画面になっていない
[ ] 小画面(地震/豪雨/鉄道/潮位)のレイアウトが崩れていない
[ ] demo用/検証用の表示物が混入していない (?demo=1 等の表示になっていない)
```

## データ

```text
[ ] window.__LiveStreamDiagnostics.getSnapshot().dataMode が "real" である
[ ] runtimeState が healthy / degraded / error のいずれかとして正しく出ている
[ ] 取得失敗時に「平常」「影響なし」等と誤断定していない (取得確認中の文言になっている)
[ ] API失敗時に demo表示へフォールバックしていない
```

## 安定性

```text
[ ] 30分以上表示を継続しても白画面化しない
[ ] Leaflet container 数が増殖しない (dom.leafletContainerCount / leafletContainerCount)
[ ] ticker のDOMノード数が増殖しない (dom.tickerTextNodes)
[ ] railway layer のインスタンス数が増殖しない (railwayLayer.layerCount)
[ ] 地図マーカー数(markerCount)が単調増加し続けていない
```

## OBS

```text
[ ] Browser Source の URL が本番想定URL (?chrome=off のみ。demo=1/focusSpeed=test等が無い)
[ ] 画面サイズが 1920x1080 に設定されている
[ ] 音声がミュートされている(意図しない音声混入がない)
[ ] 個人情報・開発用URL・APIキーの類が画面に見えていない
[ ] 配信開始/停止の手順を配信担当者が確認済みである
```

## YouTube等の配信プラットフォーム

```text
[ ] 最初は限定公開/非公開/テスト配信相当になっている
[ ] タイトル/説明/サムネイル/公開範囲設定を確認済みである
[ ] 誤って一般公開配信にしていない
[ ] 配信通知が意図せず飛ばない設定になっている
```

## 異常時対応

```text
[ ] 配信/公開停止手順を事前に確認済みである (tasks/live/live_stream_phase6a_obs_rehearsal_runbook.md 6章)
[ ] 異常発生時の連絡・エスカレーション先が決まっている
```

---

すべて✗が無いことを確認したら、限定公開/非公開相当での短時間テスト配信へ進む。
一般公開は、テスト配信で問題がないことを確認してから行う。
