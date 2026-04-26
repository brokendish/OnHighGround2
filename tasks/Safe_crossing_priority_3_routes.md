もちろんです。
今回は 「3経路化」ではなく「危険横断を避けるための3候補生成」 としてCODEXに渡すのが重要です。OSRMは alternatives=n で最大n本の代替経路探索を指定できますが、必ず指定数が返る保証はありません。OSM側では横断歩道は highway=crossing や footway=crossing、信号は crossing=traffic_signals / highway=traffic_signals などで表現されます。 ￼

⸻

OnHighGround2 安全横断優先 3経路候補生成 実装指示書（CODEX向け）

目的

OnHighGround2 のルート検索で、最大3経路を候補表示できるようにする。
ただし目的は単なる3本表示ではなく、横断歩道なしの幹線道路横断を含む危険ルートを避け、より安全な迂回候補を提示すること。

Google Maps でも危険横断を含むルートが上位に出るケースがあるため、OnHighGround2では防災ナビとして、危険横断を検出・減点し、安全横断を含むルートを上位化する。

⸻

背景

現状、最大2経路程度しか表示されない。
しかし実地確認では、Google Maps が3経路目として理想的な安全ルートを提示するケースがあった。

今回の本質は以下。

* 1本目/2本目が横断歩道なし幹線道路横断を含む
* 3本目に安全な迂回ルートが存在する可能性がある
* OSRMの返却順をそのまま信じるのではなく、OnHighGround2側で安全評価して順位付けしたい

⸻

重要方針

やること

1. OSRM alternatives=3 または alternatives=true を使い、最大3経路取得を試みる
2. フロント/バックエンド/UIを3経路候補対応にする
3. 各ルートに危険横断評価を付与する
4. 横断歩道なし幹線道路横断を強く減点する
5. 安全横断優先ルートを上位に出せるようにする
6. OSRMが3本返さない場合でも破綻しない
7. 将来、独自迂回ルート生成へ拡張できる構造にする

やらないこと

* Google Maps API依存
* 完全な交通安全判定
* OSMデータの完全補正
* 最初から高度な経由点探索エンジンを作る
* 既存ナビの大規模破壊

⸻

事前調査

CODEXはまず以下を調査すること。

1. 現在2経路に制限している箇所

以下を検索する。

slice(0, 2)
maxRoutes
MAX_ROUTES
alternatives=true
routes[0]
routes[1]
candidateRoutes
routeOptions

確認対象例:

* frontend/js/navigation.js
* frontend/js/map.js
* frontend/js/state.js
* route API 呼び出し箇所
* OSRM URL生成箇所
* UIカード表示箇所

⸻

2. OSRM呼び出しパラメータ

現在のルート検索で、OSRMに以下が付いているか確認する。

alternatives=true
steps=true
geometries=geojson
overview=full

可能なら以下を試す。

alternatives=3

ただし、OSRMは最大数を指定しても常に3本返すとは限らない。
返却数は1〜3本の可変として扱うこと。

⸻

3. 危険横断検出の既存実装

既存で以下のような機能がないか確認する。

* major road crossing detection
* Overpass crossing detection
* highway=trunk|primary|secondary
* highway=crossing
* footway=crossing
* crossing=traffic_signals
* highway=traffic_signals
* rerouteの危険横断ペナルティ
* 交差点・横断歩道・信号の検出

既存処理がある場合は再利用すること。
重複実装は避ける。

⸻

実装フェーズ1: 最大3経路対応

要件

OSRMから最大3経路を取得できるようにする。

実装

* MAX_ROUTE_CANDIDATES = 3 を定数化
* OSRM呼び出しで alternatives=3 を試す
* 非対応や挙動差がある場合は alternatives=true にフォールバック
* 返却された routes を最大3本まで扱う

注意

OSRMが1〜2本しか返さない場合も正常扱い。

const routes = osrmResponse.routes.slice(0, MAX_ROUTE_CANDIDATES);

ただし slice(0, 3) だけで終わらせないこと。
今回の目的は安全評価まで含む。

⸻

実装フェーズ2: ルート候補の安全評価

各候補ルートに安全評価メタデータを付与する。

追加する評価項目案

各 route candidate に以下を持たせる。

{
  index,
  distance,
  duration,
  geometry,
  crossingRisk: {
    majorRoadCrossings: 0,
    unsafeMajorRoadCrossings: 0,
    signalizedCrossings: 0,
    markedCrossings: 0,
    hasUnsafeCrossing: false,
    worstSeverity: "none"
  },
  safetyScore,
  displayLabel
}

⸻

危険横断の定義

幹線道路候補

以下を幹線道路として扱う。

highway=motorway
highway=trunk
highway=primary
highway=secondary

必要に応じて以下も対象。

*_link
tertiary

ただし初期実装では trunk|primary|secondary を優先。

⸻

安全横断候補

以下が近傍にある場合、安全側に評価する。

highway=crossing
footway=crossing
crossing=traffic_signals
highway=traffic_signals
crossing=marked
crossing=zebra

OSMタグとして highway=crossing や footway=crossing は横断地点表現に使われ、信号付き横断には crossing=traffic_signals や信号機ノードの highway=traffic_signals が使われるため、これらを安全横断の手掛かりとして扱う。 ￼

⸻

危険横断

以下を危険横断として扱う。

* ルート線が幹線道路を横断している
* 近傍に highway=crossing がない
* 近傍に crossing=traffic_signals / highway=traffic_signals がない
* 横断歩道・信号・歩道橋などの安全横断要素が見つからない

初期実装では完全判定でなくてよい。
疑わしい横断を risk として検出し、スコアに反映することを優先する。

⸻

実装フェーズ3: スコアリング

OSRM返却順ではなく、OnHighGround2独自スコアで並び替える。

基本方針

* 距離/時間が短いほど加点
* ハザードが少ないほど加点
* 高台方向なら加点
* 横断歩道なし幹線道路横断は大きく減点
* 信号付き/横断歩道あり横断は軽微な減点または減点なし

スコア例

score =
  baseScore
  - distancePenalty
  - durationPenalty
  - hazardPenalty
  - unsafeMajorCrossingPenalty
  + safeCrossingBonus

推奨ペナルティ

UNSAFE_MAJOR_ROAD_CROSSING_PENALTY = 100
MAJOR_ROAD_CROSSING_WITH_SIGNAL_PENALTY = 10
MAJOR_ROAD_CROSSING_WITH_MARKED_CROSSING_PENALTY = 5

横断歩道なし幹線道路横断は、多少の距離差より強く不利にすること。

⸻

実装フェーズ4: UI表示

3経路候補を表示できるようにする。

表示案

* 推奨
* 安全優先
* 短距離

または

* 候補1
* 候補2
* 候補3

ただし可能なら、候補ごとに理由を表示する。

表示する情報

* 距離
* 所要時間
* 安全評価
* 危険横断の有無
* 横断歩道なし幹線道路横断あり/なし
* 推奨理由

UI文言例

推奨ルート
横断歩道なしの幹線道路横断を避けます
短距離ルート
距離は短いですが、横断歩道なしの幹線道路横断があります
安全優先ルート
+180m / +3分。信号付き横断を利用します

⸻

実装フェーズ5: 3本目が返らない場合

OSRMが3本返さない場合も正常扱いにする。

要件

* 1本のみでもUIが壊れない
* 2本のみでもUIが壊れない
* 3本ある場合は3本表示
* 全候補が危険横断を含む場合は警告表示

警告例

安全な横断を含む代替ルートが見つかりませんでした

⸻

実装フェーズ6: 将来拡張の足場

今回すぐに独自迂回ルート生成までやらなくてよい。
ただし以下の関数境界を作ること。

fetchRouteCandidates(origin, destination, options)
evaluateRouteSafety(route)
rankRouteCandidates(candidates)
renderRouteCandidates(candidates)

将来、以下を追加しやすくする。

* 危険横断地点周辺の安全横断候補検索
* 横断歩道/信号を経由点にした迂回ルート生成
* Overpassから安全横断候補取得
* route via crossing point

⸻

重要: 独自迂回ルート生成は次フェーズ

今回の最低ラインは以下。

1. 最大3候補取得
2. 危険横断評価
3. 安全スコアで順位付け
4. UIに危険/安全理由を表示

ただし、もしOSRMが3本目を返さず、既存の危険横断回避ロジックを流用できる場合は、軽量な追加候補生成を検討してよい。

⸻

設定管理画面との連携

可能なら、以下を Config 管理に追加する。

navigation.max_route_candidates = 3
navigation.unsafe_major_crossing_penalty = 100
navigation.safe_crossing_search_radius_m = 30

ただし今回の主目的はルート候補生成なので、Config連携は無理に広げすぎない。

⸻

ログ追加

デバッグログを追加する。

必須ログ

[route-candidates] requested_alternatives=3 returned=2
[route-candidates] candidate=0 distance=1234 duration=900 unsafe_crossings=1 score=42
[route-candidates] candidate=1 distance=1410 duration=980 unsafe_crossings=0 score=88
[route-candidates] selected=candidate=1 reason=safe_crossing_priority

目的

* OSRMが何本返したか分かる
* なぜその候補が推奨されたか分かる
* 危険横断評価が効いているか確認できる

⸻

テスト観点

単体/回帰

* OSRMが1本返す
* OSRMが2本返す
* OSRMが3本返す
* alternatives=3 が使われる
* 候補が最大3本まで扱われる
* 危険横断あり候補が減点される
* 安全横断あり候補が上位化される
* 全候補危険時に警告が出る
* 既存の1経路案内が壊れない

UI

* 1候補でも表示が崩れない
* 2候補でも表示が崩れない
* 3候補表示できる
* 推奨/安全/短距離の意味が分かる
* 危険横断警告が見える

フィールドテスト向け

* Google Mapsで3本目が理想だった地点を使う
* OnHighGround2で最大3候補を取得
* 危険横断を含む候補が上位から下がるか確認
* 安全横断候補が推奨になるか確認

⸻

受け入れ条件

必須

* ルート候補を最大3本扱える
* OSRM返却数が1〜3本で変動しても壊れない
* 危険横断評価が各候補に付く
* 横断歩道なし幹線道路横断を含む候補が減点される
* 安全な候補が存在する場合、上位に出せる
* UIで候補ごとの違いが分かる
* 既存のナビ開始・案内・再ルートが壊れない

望ましい

* Config管理画面から最大候補数やペナルティを調整できる
* ログで順位付け理由が追える
* 将来の安全横断経由ルート生成に拡張しやすい

⸻

CODEXへの要求アウトプット

以下を提出すること。

1. 変更ファイル一覧
2. 現在2経路に制限していた原因
3. OSRM呼び出し変更内容
4. ルート候補データ構造
5. 危険横断評価ロジック
6. スコアリング内容
7. UI変更内容
8. 追加ログ内容
9. テスト結果
10. 未対応事項・次フェーズ提案

⸻

注意事項

* slice(0, 3) だけで完了扱いにしない
* 3本返らないことを異常扱いしない
* 危険横断評価を必ず入れる
* Google Mapsの挙動を真似るのではなく、防災ナビとして安全優先にする
* 既存の再ルート・到着判定・ナビ状態管理を壊さない

⸻

最終ゴール

OnHighGround2では、単に短いルートではなく、

少し遠回りでも、横断歩道や信号のある安全な横断を選べるルート

を候補として提示し、可能なら推奨上位に出す。

これが今回の実装のゴール。