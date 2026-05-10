# 潮汐情報機能の凍結メモ

OnHighGround2 では、現時点で潮汐情報を画面表示に採用しない。

理由は OnHighGround2 側のパース不具合ではなく、tide736 の Web 表示と API raw response の整合性に疑義があるため。防災系アプリとして、整合性を確認できない時刻情報は表示しない。

## 確認済み事項

- tide736 API raw response を保存済み
- backend の request URL / response URL をログ出力済み
- `pc/hc`, `edd/flood`, JST 時刻処理、today/tomorrow 結合、イベントソート、現在時刻以降の high/low 抽出を確認済み
- `pc=13,hc=3` は API raw response 上では羽田
- backend は raw response と一致する時刻を返している

例:

- tide736 API raw: `flood=['00:57', '12:22']`, `edd=['07:17', '19:06']`
- 確認対象の Web 表示: `満潮 06:38`, `干潮 11:31`

raw response には `00:57` / `07:17` が存在し、`06:38` は存在しない。

## 現在の扱い

- frontend から `/api/tide/current` は自動呼び出ししない
- 潮汐セクションは表示しない
- backend の `/api/tide/current`, tide736 adapter, station metadata, raw 調査 artifact は将来再検討用に残す

将来、信頼可能な公式 API、気象庁 JSON、海保公式 API などが利用可能になった場合に再検討する。
