# キキクル Phase 3-C Claude Code向け実装指示書

## 目的

Phase 3-C では、キキクル補正表示・凡例・説明文を磨き込み、
OnHighGround2 内部の開発者用語を、一般ユーザー向け表現へ翻訳する層を導入する。

目的:

* 「固定ハザードも見ている」
* 「キキクルも見ている」
* 「リアルタイム補正をしている」

ことを、ユーザーへ自然に伝える。

また、

* dataset id
* source layer 名
* internal key
* tileset 名

などの内部用語が UI に漏れないようにする。

---

# 方針

## 最重要

禁止:

* `lowland_poor_drainage`
* `flood_mesh`
* `land`
* `inund`
* `danger`
* `caution`
* `safe`
* `unknown`
* `unavailable`

などをそのまま一般 UI に表示すること。

admin/debug/log を除き、
ユーザー向け UI は翻訳済み名称のみ使用する。

---

# 実装内容

## 1. Hazard 表示名辞書

共通 display name layer を追加する。

推奨:

```js
const HAZARD_DISPLAY_NAMES = {
  lowland_poor_drainage: '低地・排水困難エリア',
  inland_flood: '内水浸水',
  flood: '洪水浸水',
  tsunami: '津波',
  landslide: '土砂災害',
  storm_surge: '高潮',

  inund: '浸水キキクル',
  flood_mesh: '洪水キキクル',
  land: '土砂キキクル',
};
```

状態系:

```js
const STATUS_DISPLAY_NAMES = {
  safe: '安全寄り',
  caution: '注意',
  danger: '危険',
  unavailable: '取得不可',
  unknown: '判定不可',
  loading: '確認中',
};
```

---

## 2. 共通変換関数

推奨:

```js
getHazardDisplayName(id)
getStatusDisplayName(status)
```

UI が内部 key を直接参照しない構造にする。

---

## 3. route-risk 表示改善

現状例:

```text
補正: -16pt 洪水キキクル危険（固定ハザード重複）
```

改善後:

```text
リアルタイム補正:
洪水リスク上昇
固定ハザードとキキクルが重なっています
```

詳細表示または debug 時のみ:

```text
洪水キキクル 危険 / 補正 -16pt
```

通常 UI は「意味」を優先。

数値は補助扱い。

---

## 4. 凡例改善

凡例へ説明追加。

例:

```text
固定ハザード:
地形・浸水想定区域などの基本リスク

キキクル:
気象庁のリアルタイム危険度分布

リアルタイム補正:
固定ハザードとキキクルを組み合わせた現在の危険度

取得不可:
判定できない状態。安全を意味しません
```

気象庁の用語:

* 土砂キキクル
* 浸水キキクル
* 洪水キキクル

は公式表記に合わせる。 ([気象庁][1])

---

## 5. 情報タブ説明文

短い説明を追加。

例:

```text
固定ハザードと気象庁キキクルを組み合わせて、
現在の危険度を補正しています。

キキクルのみで危険判定を確定するものではありません。
```

長文化しすぎない。

---

## 6. モバイル省略改善

現状:

```text
lowland_poor_dra...
```

改善:

* 省略前提を避ける
* badge 化
* 2行許可
* フォント微調整
* priority 制御

などで読みやすくする。

重要:

内部 id が途中で切れて見える状態をなくす。

---

## 7. 色・強調

推奨:

* 補正なし → 控えめ gray
* 補正あり → amber
* 固定ハザード重複 → orange
* danger 強調 → red
* unavailable → neutral gray

赤乱用禁止。

「全部危険」に見せない。

---

## 8. キキクル説明

必要に応じて tooltip / help を追加。

例:

```text
キキクル:
気象庁の「危険度分布」情報です。
大雨による浸水・洪水・土砂災害の危険度を
リアルタイム表示します。
```

気象庁の公式説明に沿うこと。 ([気象庁][2])

---

## 9. 非対象

今回はやらない:

* reroute 強化
* push 通知
* 音声警告
* 自動避難提案
* AI判断文生成

---

## 実装候補

* `frontend/js/kikikuru-layer.js`
* `frontend/js/navigation.js`
* `frontend/js/map-overlay-ui.js`
* `frontend/js/hazard-*`
* `frontend/index.html`
* `frontend/css/*`
* `e2e/kikikuru-layer.spec.js`

最小変更で統一レイヤを導入する。

---

## 完了条件

* 内部 id が一般 UI に出ない
* lowland_poor_dra... のような表示が消える
* route-risk 表示が自然文になる
* 凡例説明が追加される
* モバイルで読みやすい
* debug/admin は既存維持
* console error なし
* 既存回帰 PASS
* E2E PASS

[1]: https://www.jma.go.jp/jma/kishou/info/event/kikendobunpu2021.html?utm_source=chatgpt.com "「危険度分布」の愛称を「キキクル」に決定しました！"
[2]: https://www.jma.go.jp/bosai/risk/?utm_source=chatgpt.com "キキクル（危険度分布）"
