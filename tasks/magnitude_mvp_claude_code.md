📄 tasks/magnitude_mvp_claude_code.md

# Magnitude MVP 実装指示書（Claude Code）
## 目的
OnHighGround2 に地震情報を表示する「Magnitudeモード」を追加する。
---
## 実装スコープ
### やること
- 地震情報ボタン追加
- 日本広域表示へ切替
- 地震情報取得API実装
- ピン表示
- リスト表示
- ポップアップ表示
- 現在地からの距離表示
- Configによる日数制御
### やらないこと
- WebSocket
- 避難誘導連動
- 通知
---
## Backend
### 追加ファイル

backend/app/api/earthquakes.py
backend/app/services/earthquake_service.py
backend/app/services/earthquake_source_p2p.py

### API

GET /api/earthquakes?days=1

---
## データ取得

https://api.p2pquake.net/v2/history?codes=551&limit=100

---
## データモデル
```json
{
  "event_id": "",
  "occurred_at": "",
  "epicenter_name": "",
  "lat": 0,
  "lng": 0,
  "depth_km": 0,
  "magnitude": 0,
  "max_intensity": "",
  "tsunami_info": "",
  "source": "p2pquake"
}

⸻

Config

{
  "key": "earthquake.display_days",
  "default": 1
}

⸻

Frontend

追加ファイル

frontend/js/magnitude.js
frontend/js/magnitude-layer.js
frontend/js/magnitude-ui.js

⸻

地図初期位置

map.setView([36.2048, 138.2529], 5);

⸻

ピン色分け

* 1時間以内: 赤（強調）
* 3時間以内: 橙
* 6時間以内: 黄
* それ以外: 灰

⸻

距離計算

function distanceKm(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a =
    Math.sin(dLat/2)**2 +
    Math.cos(lat1*Math.PI/180) *
    Math.cos(lat2*Math.PI/180) *
    Math.sin(dLng/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

⸻

リスト

表示：

12:34 相模湾 震度4 M4.8
距離: 約32km

⸻

モード切替

* ON: Magnitude表示
* OFF: 通常モード復帰

⸻

実装順序

1. API作成
2. P2P取得
3. 正規化
4. Config追加
5. ボタン追加
6. ピン表示
7. リスト表示
8. 距離表示

⸻

完了条件

* 地震情報表示できる
* ピンが出る
* リスト表示できる
* 距離表示される
* 通常画面に戻れる

---
# 📄 tasks/magnitude_mvp_codex_verification.md
```md
# Magnitude MVP 検証指示書（CODEX）
## 1. API確認

curl http://localhost:8080/api/earthquakes?days=1

確認：
- 200 OK
- items配列あり
- event_id存在
- occurred_at存在
---
## 2. Config確認

/api/admin/config

確認：
- earthquake.display_days 存在
- 値変更でAPI反映
---
## 3. UI確認
- 地震情報ボタン表示
- 押すと日本全体表示
- ピンが表示される
- リストが出る
- 最新が強調される
---
## 4. ピン確認
- 色分けされている
- 直近が目立つ
- クリックで詳細表示
---
## 5. リスト確認
- 新しい順
- クリックで地図連動
---
## 6. 距離確認
現在地ON:
- 約xxkm表示
現在地OFF:
- エラーにならない
---
## 7. エラー確認
API停止時:
- UI崩れない
- エラーメッセージ表示
---
## 8. 回帰確認
以下が壊れていない:
- ハザード表示
- 避難所
- ナビ
- 現在地表示
---
## 合格条件
- 地震情報が取得できる
- ピン・リスト表示OK
- 距離表示OK
- 既存機能問題なし

⸻

