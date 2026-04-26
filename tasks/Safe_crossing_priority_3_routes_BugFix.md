Safe_crossing_priority_3_routes.md の対応によるバグフィックスです。

これは明確にスコアリング/ラベル付けのバグです。
画面を見る限り、候補1を「推奨」にしてはいけないです。候補2が推奨です。

原因候補はほぼこのどれかです。

1. 危険横断検出はできているが、最終順位に反映されていない
2. スコアの大小判定が逆
    * 高いほど良いのに低い方を推奨している
    * またはその逆
3. UIラベルだけがOSRM返却順のまま
    * 候補1 = OSRM 1本目 = 推奨扱い、になっている
4. 選択中ルートとランキング済み候補配列がズレている
5. 横断リスク判定が候補1に付いていない
    * 実際は危険なのに unsafeMajorRoadCrossings=0 になっている可能性

今回のスクショだと、特に怪しいのは 「UIラベルがOSRM順のまま」 です。
候補1がオレンジで「推奨」、候補2が青で「注意」になっていますが、実際の安全性とは逆です。

CODEXに投げる修正指示

そのまま貼れる形で置きます。

⸻

OnHighGround2 ルート候補推奨順位逆転バグ修正指示

目的

安全横断優先の3経路候補生成において、危険なルートが「推奨」になり、安全な迂回ルートが「注意」になる不具合を修正する。

現象:

* 候補1: 横断歩道なしで幹線道路を横断する危険ルート
* 候補2: 幹線道路の横断を避ける、または安全な横断を使うべきルート
* しかし画面上では候補1が「推奨」、候補2が「注意」になっている

これは防災ナビとして重大な優先順位バグ。

⸻

確認対象

以下を重点確認すること。

* frontend/js/routing.js
* frontend/js/navigation.js
* frontend/js/location-info-panel.js
* route candidate の生成箇所
* candidate sort / ranking 箇所
* UIラベル付与箇所
* 選択中ルートの決定箇所

⸻

調査ポイント

1. スコアの大小判定

以下を確認する。

* __safetyScore は高いほど安全なのか
* 低いほど安全なのか
* sort がそれと一致しているか

例:

candidates.sort((a, b) => b.__safetyScore - a.__safetyScore)

高いほど良いならこの形。

逆にしている場合、危険ルートが上位になる。

⸻

2. OSRM返却順をそのまま「推奨」にしていないか

以下のような実装がないか確認する。

candidate.index === 0 ? "推奨ルート" : ...

これは禁止。

「推奨」はOSRM返却順ではなく、安全評価後のランキング1位 に付けること。

⸻

3. UIラベルの付与タイミング

ラベルは sort 前ではなく、rank後に付与すること。

正しい流れ:

OSRM routes取得
→ crossing risk評価
→ safety score算出
→ candidatesをrank
→ rank後の順位に応じて label を付ける
→ UI表示

禁止:

OSRM routes取得
→ index 0 に推奨ラベル
→ safety score算出
→ sort

または

sortしたのにUIは元配列を表示

⸻

4. 危険横断数が正しく入っているか

今回の地点で候補1に以下が付いているか確認する。

__crossingRisk.unsafeMajorRoadCrossings >= 1
__crossingRisk.hasUnsafeCrossing === true

もし候補1が unsafeMajorRoadCrossings=0 なら、検出ロジックが効いていない。

⸻

5. 候補2が誤って注意扱いされる理由

候補2について以下を確認する。

* unsafeMajorRoadCrossings
* majorRoadCrossings
* markedCrossings
* signalizedCrossings
* hasUnsafeCrossing
* worstSeverity
* __safetyScore

安全な迂回ルートなら、候補1より高スコアになるべき。

⸻

修正要件

1. 推奨順位は safetyScore で決める

候補順位は必ず以下を優先する。

1. 危険横断なし
2. 横断歩道/信号あり
3. 距離・時間
4. OSRM返却順

OSRM返却順は最後のタイブレーク程度にする。

⸻

2. 横断歩道なし幹線道路横断は強く減点

以下のペナルティが確実に効くようにする。

UNSAFE_MAJOR_ROAD_CROSSING_PENALTY = 100

ただし距離/時間スコアとの相対で弱すぎるなら、さらに強めてよい。

推奨値:

UNSAFE_MAJOR_ROAD_CROSSING_PENALTY = 300

または、スコア式に関係なく、まず危険横断あり候補を下げる。

推奨ソート:

candidates.sort((a, b) => {
  const au = a.__crossingRisk?.unsafeMajorRoadCrossings ?? 0;
  const bu = b.__crossingRisk?.unsafeMajorRoadCrossings ?? 0;
  if (au !== bu) return au - bu;
  return (b.__safetyScore ?? 0) - (a.__safetyScore ?? 0);
});

これなら、危険横断数が少ない候補が必ず上に来る。

⸻

3. ラベルはrank後に付け直す

rank後に以下のようにラベル付与する。

rankedCandidates.forEach((candidate, rank) => {
  if (rank === 0 && !candidate.__crossingRisk?.hasUnsafeCrossing) {
    candidate.__displayLabel = "推奨ルート";
  } else if (!candidate.__crossingRisk?.hasUnsafeCrossing) {
    candidate.__displayLabel = "安全優先";
  } else {
    candidate.__displayLabel = "注意ルート";
  }
});

注意:

* rank 0 でも危険横断ありなら、無条件で「推奨」にしない
* 全候補が危険なら「注意ルート」の中で最もマシな候補を選ぶ

⸻

4. UI表示はrankedCandidatesを使う

UIには必ず安全評価後の並びを渡すこと。

禁止:

renderRouteCandidates(originalRoutes)

正:

renderRouteCandidates(rankedCandidates)

⸻

5. 選択中ルートもrank 1位にする

初期選択ルートは OSRM routes[0] ではなく、rank後の先頭にする。

const selectedRoute = rankedCandidates[0];

⸻

追加ログ要件

以下を必ず出すこと。

[route-candidates] raw_index=0 rank=1 distance=343 unsafe=1 score=xxx label=注意ルート
[route-candidates] raw_index=1 rank=0 distance=401 unsafe=0 score=yyy label=推奨ルート
[route-candidates] selected_raw_index=1 selected_rank=0 reason=safe_crossing_priority

これにより、OSRM順と安全評価順のズレを追えるようにする。

⸻

受け入れ条件

今回のスクショの地点で以下になること。

* 候補1、343m、横断歩道なし幹線道路横断あり
    * 「注意ルート」になる
    * 推奨にならない
* 候補2、401m、安全な迂回ルート
    * 「推奨ルート」または「安全優先」になる
    * 初期選択される
* 地図上の強調表示も候補2になる
* ログで selected_raw_index=1 相当が確認できる

⸻

テスト観点

単体

* 危険横断あり短距離候補 vs 安全迂回候補
* 安全迂回候補が上位になる
* OSRM raw index 0 が危険なら推奨にならない
* raw index 1/2 が安全なら推奨になる

UI

* ラベルが安全評価順と一致する
* 選択中表示がrank 1位と一致する
* 色・ボタン順・理由文が一致する

回帰

* 危険横断なしの最短ルートは通常通り推奨
* 1候補しかない場合でも壊れない
* 全候補危険の場合は警告表示

⸻

最重要注意

候補1 = 推奨 ではない。
OSRMが最初に返したルート = 推奨 でもない。

OnHighGround2では、

安全評価後に最も安全・妥当な候補 = 推奨

とすること。

⸻

この修正はかなり大事です。
今のままだと「危険横断を検出したのに、画面では危険ルートを推す」という一番まずい状態です。
検出器はあるのに司令塔が逆向き、みたいな状態ですね。ここは直せば一気に良くなります。