# Magnitude Phase2-1 実装指示書（Claude Code）
## Magnitudeモード中の避難所レイヤー一時非表示対応

## 目的

OnHighGround2 の Magnitudeモード表示時に、日本広域地図が避難所ピンで埋まらないようにする。

Magnitudeモード中は地震情報の視認性を最優先とし、避難所レイヤーを一時的に非表示にする。  
Magnitudeモード解除時には、通常モードでの避難所表示状態を可能な限り元に戻す。

---

## 背景

現在、Magnitudeモードでは日本広域表示に切り替わるが、東京・神奈川などの避難所ピンが大量に表示され、地震ピンや震源情報が見づらくなる。

Magnitudeモードの主役は地震情報であり、避難所はこの段階では補助情報ではない。  
そのため、Magnitudeモード中だけ避難所を一時退避する。

---

## 実装方針

### 基本方針

```text
通常モード:
  避難所レイヤーはユーザーの表示状態どおり

MagnitudeモードON:
  現在の避難所表示状態を保存
  避難所レイヤーを一時非表示
  地震ピン・地震リストを優先表示

MagnitudeモードOFF:
  Magnitudeモード突入前の避難所表示状態に戻す
```

---

## 重要要件

### 1. 避難所表示状態を破壊しない

Magnitudeモード中に避難所を非表示にしても、ユーザー設定そのものを恒久的にOFFにしないこと。

```text
NG:
  Magnitude ON → 避難所OFF → Magnitude OFF後も避難所OFFのまま

OK:
  Magnitude ON前に避難所ONなら、Magnitude OFF後にONへ戻る
```

---

### 2. 一時非表示であることを明示する

Magnitudeパネル内、または地震情報リスト上部に小さく説明を表示する。

表示例:

```text
Magnitudeモード中は、地図を見やすくするため避難所レイヤーを一時非表示にしています。
```

---

### 3. 既存の避難所機能を壊さない

以下の既存機能に影響を与えないこと。

- 通常モードでの避難所表示
- 避難所クラスタ表示
- 避難所個別ピン表示
- サイドパネルや右側ボタンによる避難所ON/OFF
- 現在地表示
- ナビ機能

---

## 実装対象の想定ファイル

既存構成に合わせて最小変更とする。

主な変更候補:

```text
frontend/js/magnitude.js
frontend/js/magnitude-ui.js
frontend/js/shelters.js
frontend/js/map.js
frontend/index.html
```

ただし、既存の避難所制御関数が別ファイルにある場合は、既存構造を優先すること。

---

## 推奨実装

### 1. Magnitude側に退避状態を持つ

`frontend/js/magnitude.js` など Magnitudeモード制御側に状態を追加する。

例:

```js
let previousShelterVisibility = null;
let magnitudeTemporarilyHidShelters = false;
```

---

### 2. Magnitude ON時の処理

Magnitudeモードに入る直前に、避難所レイヤーの現在状態を取得する。

疑似コード:

```js
function enterMagnitudeMode() {
  previousShelterVisibility = getShelterLayerVisibility();

  if (previousShelterVisibility === true) {
    hideShelterLayerForMagnitude();
    magnitudeTemporarilyHidShelters = true;
  } else {
    magnitudeTemporarilyHidShelters = false;
  }

  // 既存のMagnitude表示処理
  showMagnitudeMode();
}
```

---

### 3. Magnitude OFF時の処理

Magnitudeモード解除時に、退避した状態を戻す。

疑似コード:

```js
function exitMagnitudeMode() {
  // 既存のMagnitude解除処理
  hideMagnitudeMode();

  if (magnitudeTemporarilyHidShelters && previousShelterVisibility === true) {
    restoreShelterLayerAfterMagnitude();
  }

  previousShelterVisibility = null;
  magnitudeTemporarilyHidShelters = false;
}
```

---

### 4. 避難所制御関数を明確化する

既存の避難所表示制御に合わせて、必要なら薄いラッパー関数を作る。

例:

```js
function getShelterLayerVisibility() {
  // 既存の状態変数、チェックボックス、LayerGroup状態などから判定する
}

function hideShelterLayerForMagnitude() {
  // UIの恒久設定を壊さず、地図上の避難所レイヤーだけ一時的に隠す
}

function restoreShelterLayerAfterMagnitude() {
  // Magnitude突入前に表示されていた場合のみ戻す
}
```

注意:

```text
チェックボックス状態を不用意に変更しない。
変更が必要な場合は、一時非表示であることが分かるように状態同期する。
```

---

## UI追加

Magnitudeパネルまたはリスト上部に説明文を追加する。

例:

```html
<div class="magnitude-layer-note">
  Magnitudeモード中は、地図を見やすくするため避難所レイヤーを一時非表示にしています。
</div>
```

CSS例:

```css
.magnitude-layer-note {
  font-size: 12px;
  opacity: 0.75;
  margin: 6px 0 10px;
  line-height: 1.4;
}
```

既存デザインに合わせて調整すること。

---

## エッジケース

### 1. Magnitude ON前に避難所OFF

```text
期待動作:
  Magnitude OFF後も避難所OFFのまま
```

### 2. Magnitude ON前に避難所ON

```text
期待動作:
  Magnitude中は避難所非表示
  Magnitude OFF後に避難所ONへ戻る
```

### 3. Magnitudeモード中に連続ON/OFF

```text
期待動作:
  状態が壊れない
  避難所レイヤーが増殖しない
  イベントが多重登録されない
```

### 4. 避難所レイヤー未初期化

```text
期待動作:
  Magnitudeモードは正常に動作
  console error を出さない
```

---

## 実装順序

1. 既存の避難所表示制御の状態管理を確認する
2. Magnitude ON前の避難所表示状態を取得できるようにする
3. Magnitude ON時に避難所を一時非表示にする
4. Magnitude OFF時に元の表示状態へ戻す
5. Magnitudeパネルに一時非表示の説明文を追加する
6. 連続ON/OFFで状態が崩れないようにする
7. 既存機能の回帰を確認する

---

## 完了条件

以下を満たすこと。

```text
・MagnitudeモードON時に避難所ピンが非表示になる
・MagnitudeモードOFF時に元の避難所表示状態へ戻る
・Magnitude ON前に避難所OFFだった場合、OFFのまま維持される
・地震ピン、地震リスト、ポップアップ表示に影響しない
・通常モードの避難所表示・クラスタ表示が壊れない
・連続ON/OFFでレイヤーやDOMが増殖しない
・console error が発生しない
```

---

## 注意事項

この対応は Phase2-1 とし、今回は以下を実装しない。

```text
・新着地震の差分ハイライト
・距離順ソート
・震度フィルタ
・リアルタイム更新
```

今回の目的は、Magnitudeモードの視認性改善と既存避難所レイヤーとの干渉解消に限定する。
