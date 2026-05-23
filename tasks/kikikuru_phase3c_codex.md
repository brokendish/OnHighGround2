# キキクル Phase 3-C CODEX向け検証指示書

## 目的

Phase 3-C で導入された、

* 開発者用語 → ユーザー用語翻訳層
* キキクル補正表示改善
* 凡例・説明文改善
* モバイル表示改善

が安全に動作しているか検証する。

---

# 最重要確認

## 1. 内部 ID 漏れ禁止

一般 UI 上で以下が表示されないこと:

```text
lowland_poor_drainage
flood_mesh
inund
land
danger
caution
safe
unknown
unavailable
```

許可:

* debug console
* admin
* network payload
* internal logs

禁止:

* 情報タブ
* route-risk summary
* badge
* tooltip
* alert
* legend
* mobile collapsed UI

---

## 2. モバイル省略確認

確認:

* `lowland_poor_dra...` が消えている
* badge が潰れない
* overflow-x が増えていない
* 390px 前後で読める
* 2行表示が崩れない

---

## 3. route-risk 表示改善

確認:

旧:

```text
補正: -16pt 洪水キキクル危険
```

改善後:

```text
リアルタイム補正
洪水リスク上昇
```

のように自然文になっている。

開発者向け数値は:

* debug
* detail
* expanded

などに限定されていること。

---

## 4. 凡例確認

確認:

* 固定ハザード説明
* キキクル説明
* リアルタイム補正説明
* 取得不可説明

が存在する。

また、

* 土砂キキクル
* 浸水キキクル
* 洪水キキクル

が気象庁公式表記と一致していること。 ([気象庁][1])

---

## 5. 情報タブ説明文

確認:

* 長すぎない
* モバイルで崩れない
* 「キキクルのみで危険判定を確定しない」が伝わる

---

## 6. 色確認

確認:

* unavailable が danger 色になっていない
* 補正なしが強調されすぎない
* 赤乱用なし
* fixed hazard + kikikuru overlap が適度に強調される

---

## 7. 回帰

最低限:

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/navigation.js
node --check frontend/js/map-overlay-ui.js

npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js
npx playwright test e2e/info-tab-card-ui.spec.js
npx playwright test e2e/hazard-state-consistency.spec.js
```

---

## 8. Docker 実ブラウザ確認

確認:

* desktop
* mobile
* unavailable
* overlap
* route preview

スクリーンショット保存:

* `tasks/screenshots/kikikuru_phase3c_desktop.png`
* `tasks/screenshots/kikikuru_phase3c_mobile.png`
* `tasks/screenshots/kikikuru_phase3c_legend.png`

---

## 判定基準

### PASS

* 内部 ID が UI に漏れない
* lowland_poor_dra... が消える
* route-risk 表示が自然
* モバイル readable
* official terminology 使用
* 既存回帰 PASS
* console error / pageerror なし

### PASS with notes

許容:

* 一部 wording 微調整余地
* badge 幅の軽微な調整余地
* 実災害データ不足で danger 色確認が限定的

### FAIL

* 内部 id 表示
* unknown/safe 等の内部状態漏れ
* モバイル overflow
* UI 崩壊
* 気象庁用語不一致
* console error

[1]: https://www.jma.go.jp/jma/kishou/info/event/kikendobunpu2021.html?utm_source=chatgpt.com "「危険度分布」の愛称を「キキクル」に決定しました！"
