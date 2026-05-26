# OnHighGround2 — AI作業ルール

## 重要
/live 関連の作業を始める前に必ず docs/live/DEVELOPMENT_GUARDRAILS.md を読むこと。

## 絶対に守る境界（詳細は上記ガードレール参照）
- 既存ナビ本体（index.html, navigation.js, nav-*.js, hazard-layers.js,
  location-info-panel.js, 既存ルート探索/reroute）は改変禁止
- live のコードは frontend/js/live/, backend/app/*/live_*.py 等、
  指定ディレクトリ内にのみ作成する
- backend / Martin / data_lake / shared 等の既存資源は「利用」はOK、「改変」はNG