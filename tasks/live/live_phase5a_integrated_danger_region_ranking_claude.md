# Phase 5-A 危険地域統合ランキング MVP

## 目的

/live の危険地域表示を、イベント単位ランキングから地域単位の統合ランキングへ改善する。

現状では、同じ地域に複数の危険要素がある場合でも、

- 高知県付近 キキクル（洪水）
- 高知県付近 雨雲

のように別項目として表示される。

Phase 5-A では、同一地域の複数イベントを統合し、

- 高知県付近
  - キキクル（洪水）
  - 雨雲

のように表示する。

---

## 対象

統合対象:

- rain
- kikikuru
- tsunami
- storm_surge
- earthquake

対象外:

- tide
- sun_moon
- 避難判定
- AI危険度判定
- 機械学習
- 100点スコア化

---

## 基本方針

このフェーズでは「危険判定」ではなく「表示統合」を行う。

危険度ロジックを大きく変更しないこと。

既存 dangerous_areas の各イベントを、地域単位にまとめる。

---

## 統合仕様

### 入力

既存 dangerous_areas を使用する。

例:

```json
[
  {
    "label": "高知県付近",
    "type": "kikikuru",
    "level": "danger",
    "detail": "洪水"
  },
  {
    "label": "高知県付近",
    "type": "rain",
    "level": "danger"
  }
]
```

---

### 出力

地域単位へ統合する。

例:

```json
[
  {
    "label": "高知県付近",
    "level": "danger",
    "types": ["kikikuru", "rain"],
    "events": [
      {
        "type": "kikikuru",
        "label": "キキクル（洪水）",
        "level": "danger"
      },
      {
        "type": "rain",
        "label": "雨雲",
        "level": "danger"
      }
    ]
  }
]
```

---

## 統合キー

基本は以下で統合する。

```text
label
```

例:

- 高知県付近
- 沖縄県付近
- 鹿児島県付近

将来的な市区町村・地方名統合を妨げない構造にすること。

---

## 優先順位

統合地域の並び順は、含まれるイベント種別の優先度で決める。

優先度:

```text
tsunami
storm_surge
earthquake
kikikuru
rain
```

同一地域に複数イベントがある場合は、最も優先度の高いイベントを代表優先度とする。

---

## 表示仕様

### 危険地域カード

現在の危険地域リストを、統合表示に変更する。

表示例:

```text
1 高知県付近
  キキクル（洪水）
  雨雲

2 沖縄県付近
  雨雲
```

---

## 件数

地域単位で最大表示件数を制限する。

初期値:

```text
10件
```

---

## false-safe

以下を維持する。

- unknown を danger 扱いしない
- unavailable を danger 扱いしない
- threshold未満の雨雲を表示しない
- 危険判定のない tide / sun_moon を dangerous_areas に入れない

---

## API契約

既存 dangerous_areas を破壊しないこと。

可能であれば、新フィールドを追加する。

推奨:

```json
{
  "dangerous_areas": [],
  "integrated_dangerous_regions": []
}
```

UIは `integrated_dangerous_regions` が存在する場合に優先利用する。

存在しない場合は既存 `dangerous_areas` 表示へフォールバックする。

---

## ログ

```text
live integrated danger regions:
input_areas=X
regions=Y
```

地域統合時:

```text
live integrated region:
label=高知県付近
types=kikikuru,rain
```

---

## 禁止事項

- AI危険判定追加
- 機械学習追加
- 避難推奨追加
- 100点スコア化
- ナビ本体変更
- navigation.js変更
- tide / sun_moon の危険判定化

---

## 完了条件

- 同一地域の rain / kikikuru が統合表示される
- 津波・高潮・地震も統合対象になる
- 地域単位で最大10件表示される
- 既存 dangerous_areas 契約を壊さない
- false-safe を維持する
- Docker正常起動
- /live正常表示
- ナビ本体へ影響なし