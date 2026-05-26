# 総合災害ビューア全国監視 / live 開発ガードレール

## 最重要方針

/live は OnHighGround2 内に実装するが、既存の避難ナビ本体とは半独立アプリとして扱う。

OnHighGround2 の backend / Martin / data_lake / admin / registry / shared utilities は活用してよい。

ただし、既存ナビ本体の UI・状態管理・ルート探索処理を live 実装のために改変してはならない。

## 触ってよい場所

- frontend/live.html
- frontend/js/live/
- frontend/js/shared/
- frontend/css/live/
- backend/app/api/live_*.py
- backend/app/services/live_*.py
- e2e/live-*.spec.js
- docs/live/
- tasks/live/

## 原則触らない場所

- frontend/index.html
- frontend/js/navigation.js
- frontend/js/nav-*.js
- frontend/js/location-info-panel.js
- frontend/js/hazard-layers.js
- 既存ナビ用 bottom panel 関連
- 既存ルート探索 / reroute 関連

## 例外

既存資産を共通化するために変更が必要な場合は、直接改変せず、まず shared 化する。

変更する場合は必ず以下を満たすこと。

- 既存ナビの挙動を変えない
- 既存 E2E を通す
- live 専用 E2E を追加する
- 変更理由を tasks/live/ に記録する

## 禁止事項

- live 用 UI を index.html に混ぜない
- live 用 state を navigation.js に持たせない
- live のために OSRM 依存を追加しない
- live 実装で既存ナビのレイアウトを変更しない
- 巨大 GeoJSON を全国表示で直接読み込まない

## 実装方針

/live は将来独立サービス化できる境界で作る。

初期は OnHighGround2 の資源を使うが、設計思想としては別アプリとして扱う。