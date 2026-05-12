# 気象庁潮位表 JMA runtime化 検証結果

判定: PASS

## 結果

- JMA 2026 潮位表DL: 50地点成功
- raw: `data_lake/raw/japan/tide/jma/2026/` に `h*.txt` 50件
- normalize: `tide_hourly_2026.jsonl`, `tide_extremes_2026.jsonl` 生成
- validate: pass
- 件数: `50 * 365 * 24 = 438000`
- runtime: `data_runtime/backend/tide/jma/2026/` に `manifest.json` 含め配置
- Docker: backend / frontend / martin / osrm-walking 起動確認
- 潮汐API: HTTP 200
- API source: `jma`
- station/current/high/low 取得OK
- backendログ: `tide runtime loaded year=2026 stations=50`
- backendログ: `nearest tide station resolved station=TK`
- 再起動後ログの `tide736`: 0件
- Playwright: `#lip-tide-section` 存在
- JS error: なし

## 補足

JMA 2026 の実ファイル確認で `HC` と `DS` は 404。
そのため、2026用 `station_master.json` は実取得可能な50地点に揃えた。
再DL時も `failed=0` となることを確認。

## 最終判断

tide736 API依存を廃止し、気象庁潮位表の年次runtime参照へ移行完了。
