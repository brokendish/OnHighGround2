# Phase 4-A / 4-B CODEX向け検証指示書

## Phase 4-A 検証

確認:

* ナビ中に前方危険警告が表示される
* 前方距離表示がある
* 固定ハザード + キキクル重複説明がある
* 取得不可を danger 扱いしない
* 取得不可を safe 扱いしない
* 自動 reroute が発火しない
* mobile で読める
* Simulation Mode で再現できる

E2E 推奨:

* 前方 250m 洪水危険
* 土砂危険
* 強雨 + 低地
* route-risk danger
* unavailable
* unknown
* clear

---

## Phase 4-B 検証

確認:

* 状況理解カードが表示される
* 現在地/目的地/時間変化を説明できる
* 「待機検討」
* 「早めの移動検討」
  を表示できる
* 理由説明がある
* ブラックボックス表現がない
* 命令口調になっていない
* mobile で読める

Simulation 推奨:

* 現在地危険 + 目的地注意
* 現在地注意 + 目的地危険
* 20分後改善
* 強雨継続
* 取得不可

禁止確認:

* 自動 reroute
* 強制避難命令
* 「安全です」断定
* 「危険です」断定
* mock 漏洩

回帰:

```bash
npx playwright test
python3 -m compileall backend/app backend/main.py
node --check frontend/js/*.js
git diff --check
```

PASS 条件:

* 状況理解UIが自然
* 警告が過剰でない
* 説明可能
* mobile readable
* Simulation 再現可能
* console error / pageerror なし
