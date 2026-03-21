# Hazard Layer Regression Checklist

ハザードレイヤー変更後の動作確認チェックリスト。

## 基本動作

- [ ] `docker compose up` が正常起動する
- [ ] `curl http://localhost:8080/tiles/catalog` が 200 を返す
- [ ] flood / storm_surge / tsunami のトグルが表示される（非活性化でない）
- [ ] inland_flood / landslide のトグルが表示される

## Vector Tile 配信

- [ ] `/tiles/tokyo_flood_max/{z}/{x}/{y}` がタイルを返す（例: z10）
- [ ] `/tiles/tokyo_storm_surge/{z}/{x}/{y}` がタイルを返す
- [ ] `/tiles/tokyo_tsunami_A40-23_13/{z}/{x}/{y}` がタイルを返す
- [ ] z8 / z10 / z12 / z13 でそれぞれ表示確認

## API fallback（タイル不在時）

- [ ] `data_runtime/frontend/tiles/` を空にした状態でトグルが有効のまま
- [ ] タイル失敗時に `console.warn` に `apiUrl フォールバック` が出る
- [ ] API fallback でレイヤーが表示される

## Severity 表示

- [ ] flood: 浸水深ランクで色分け表示（黄〜赤系）
- [ ] storm_surge: 浸水深ランクで色分け表示（水色〜紺系）
- [ ] inland_flood: zone_type で色分け表示
- [ ] landslide: zone_type で色分け表示

## エラー確認

- [ ] ブラウザ console にエラーがない（`[hazard-layers]` 行を確認）
- [ ] `[hazard-layers] モジュール評価完了。全定数 OK。` が console.debug に出る
- [ ] TDZ エラー (`Cannot access '...' before initialization`) が出ない
