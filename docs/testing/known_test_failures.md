# 既知のテスト失敗（known test failures）

full regression（`venv/bin/python -m pytest -q -p no:cacheprovider tests backend/tests`）で失敗するが、
原因が分かっていて今は直さないテストの台帳。ここに載せることは「失敗を受け入れた」記録であり、
解決ではない。各項目は期限と、何をもって閉じるかを持つ。期限を過ぎた項目は再判定する。

新しい失敗をここへ足すときは、原因・分類・公開への影響・期限・閉じる条件を書く。
skip / xfail・assertion の緩和で失敗を消さない。

分類: A 製品の不具合 / B 公開 blocker / C 古い期待値 / D 古い fixture / E platform 依存 /
F テスト基盤の不具合 / G 意図した挙動 / H 公開対象外（operator 等）/ I 原因未確定

## 未解消（2026-10-13 時点）

なし。

## 解消済み

### KTF-003（CLOSED）`tests/test_public_release_dem_fixture.py::test_12_historical_release_record_is_preserved`（再設計後 `test_12_formal_evidence_is_append_only`）

| 項目 | 内容 |
|---|---|
| 状態 | **CLOSED**（2026-10-13、修正 commit 39f4fd5） |
| 失敗 | `tasks/public-release/evidence/phase2d/phase2d_round5c_release_delta_manifest.json` に demo DEM の entry が無い（StopIteration） |
| 原因 | Round 5C の release delta manifest（2026-08-22、baseline d3eeb99、674 entry）を、2026-10-12 の Phase 2-D formal 再実行で AT-17 tool が同じ固定 file 名へ上書きした（0 entry の当時の manifest）。同時に `phase2d_round5c_at17_snapshot_result.json` と `phase2d_at14_results.json` も上書きされた |
| 失われた記録の扱い | 原本は失われ、写し（approval package・Time Machine・Spotlight）は無く、正確な復元はできない。OWNER 決定（2026-10-12）により、再生成・推測による復元・test を通すための偽 evidence の作成・過去記録の書き換えはしない。残っている事実（baseline d3eeb99・674 entry・うち 213 entry が 2026-10-12 時点で現在と異なること・demo DEM の entry が旧 sha 0641f39c… だったこと）は commit ee944e9 のメッセージと test の docstring にだけある |
| 分類 | F（tool が過去の evidence を上書きする設計）。製品・公開物への影響なし |
| OWNER 決定 | formal evidence は immutable / append-only を正式な契約とする。回復できない「過去の記録が残っている」前提の test は捨て、上書きが再発しないことを検査する |
| 新しい契約 | `tools/public_release/formal_evidence.py`。run ごとに `evidence/<phase>/runs/<UTC>-<HEAD12>-<tool>-<round>-a<attempt>-<run_id>/` を作り、既存 directory・同じ identity（phase・tool・round・HEAD・attempt）の既存 attempt があれば止まる。file は一時 file → fsync → 読み戻し検証（JSON は parse）→ `os.link`（既存名を置き換えない）で作る。finalize で `provenance.json`（schema・HEAD・tool・round・attempt・実行結果・generated_at・各 file の sha256 / size）を書き read-only にする。AT-14・AT-17 はこの方式、固定 directory へ上書きしていた 2b1・2b2・2c official runner は run ごとの directory と終了時の provenance |
| closure test | `test_12_formal_evidence_is_append_only`（AT-17 の evidence A → 別 run B で A が byte 単位で同一・B は別 identity / path・同じ attempt の明示は拒否・旧固定名 file に触れない）。`tools/public_release/test_formal_evidence_immutability_selfcheck.py` 22 件（identity・同一 path / link 段階の上書きの negative control・中断 / 不正 JSON / 読み戻し不一致で何も残らない・旧形式の上書きを provenance と snapshot が検出・tool の配線）。変異（`os.link`→`os.replace`、directory の再利用、attempt 重複の許可、JSON 検証の除去）はいずれも検出される |
| closure evidence | full regression 2338 passed・0 failed・16 skipped。public-release selfcheck 372 passed。実 tool で AT-14 30/30 PASS・AT-17 PASS（判定は従来どおり）、evidence は新しい run directory だけに作られ verify_run 一致。既存 evidence 52 file は変更・削除 0 |
| 残り | `phase2b6_scoped_assertions` は固定 directory（`evidence/phase2b6/`）へ書き、自分の過去の出力を読み戻す設計で、その path が tracked fixture（version binding）に埋め込まれているため今回は変更していない（Phase 2-E で扱う） |
| first_seen / closed_at | 2026-10-12 / 2026-10-13 |

### KTF-001（CLOSED）`backend/tests/test_phase2b6_rollback.py::test_rollback_isolated_setup_and_reader_observation`

| 項目 | 内容 |
|---|---|
| 状態 | **CLOSED**（2026-10-12、修正 commit 68a08e5） |
| 失敗 | macOS で `RuntimeAtomicError: renameat2はこのplatformで利用不能（platform=darwin）` |
| 原因 | atomic publish / rollback は Linux の `renameat2(RENAME_NOREPLACE)` を使う（`runtime_atomic.py`）。macOS には無い。同種のテスト（`test_tile_retirement.py` 等）は Linux 専用の marker を持つが、このテストには無い |
| 分類 | E（platform 依存）。F（Linux 専用 marker の欠落） |
| 判定 | NON_BLOCKER・P3 |
| 公開への影響 | なし。Linux（backend-public image、arm64）では PASS。本番 VPS（amd64）は publish のたびにこの経路を使っている |
| first_seen | Phase 2-B.6（2026-08-15、「既知の Linux 専用 rollback test」として deselect されていた） |
| platform 契約 | atomic publish は Linux kernel の renameat2(RENAME_NOREPLACE) で既存 version を上書きしない（確認と rename の間の TOCTOU なし、fallback 禁止）。current の切替は一時 symlink の rename(2)。macOS 用の代替実装は作らない |
| 修正 | ROLLBACK-PORTABILITY-LINUX-CONTRACT phase。`scripts/test/run_linux_contract.sh` が Linux container（backend-public image + 固定版 pytest、Docker named volume 上、uid 10002・supplemental gid 20001、network none）でテストを実行する。`tests/linux_contract.py` はその場で renameat2 を実際に呼んで判定し、使えなければ同じテストを container へ委譲する（container 内の失敗・skip は委譲元の失敗。`OHG2_LINUX_CONTRACT_INNER=1` で再委譲しない。Docker が無ければ失敗）。skip / xfail は追加していない |
| closure evidence | Linux 7.0.12-linuxkit aarch64、named volume ext4（/dev/vda1 rw,relatime,discard）、renameat2 NOREPLACE の実動作を qualification で確認。Linux 契約一式（rollback・atomic publish・preflight / required tile guard・mirror 整合・退役・tile path 移行）127 passed・skip 0。Mac の full regression では委譲で PASS（既知の失敗として残らない） |
| closed_at | 2026-10-12 |

### KTF-002（CLOSED）`tests/test_runtime_mbtiles_group_contract.py::test_C_permission_matrix_flat_mirror_backend_public_can_read_all_mbtiles`

| 項目 | 内容 |
|---|---|
| 状態 | **CLOSED**（2026-10-12、修正 commit d99a2a4） |
| 失敗 | 権限 matrix 74 項目中 1 項目:「flat mirror sync失敗: operatorが書き込めないdirectory（root:root 0700）では exit 2」が exit 1 |
| 原因 | `scripts/publish/sync_frontend_tiles_mirror.sh` の cp 失敗時の後始末 `rm -f -- "${tmp}"` が、operator が traverse できない directory では Permission denied で失敗し、`set -euo pipefail` によりその場で exit 1 になる（`exit 2` と `log_warn` に届かない）。rename 失敗時の後始末も同じ形 |
| first-bad | 660cf34（2026-10-06、mirror 同期を file 単位の atomic rename に変更） |
| 分類 | A（製品の不具合）・H（operator の publish script、公開 runtime ではない） |
| 判定 | NON_BLOCKER・P3（重大度 低） |
| 公開への影響 | なし。呼び出し側 `deploy_to_runtime_atomic.sh` は 0 と 4 以外の終了コードをすべて warning として扱うため、exit 1 でも publish の結果・表示は exit 2 と同じ。契約違反の exit 4（fail-loud）は正しく動く。失われるのは script 側の「cp 同期に失敗」の warning 行だけ |
| 再現 | uid 10002 で、root:root 0700 の directory へ `set -e` 下で cp → `rm -f` すると exit 1。`rm -f ... 2>/dev/null \|\| true` にすると exit 2 |
| 受け入れていた理由 | 公開 runtime・避難判断に影響しない operator script の終了コードの不一致で、製品の挙動の変更は triage の範囲外だった |
| 修正 | MIRROR-SYNC-EXIT-CODE phase。同期の結果（primary）と後始末（cleanup）を分けた。後始末は EXIT trap が行い、失敗は path と rc を warning に残すが終了コードは同期の結果のまま（同期が成功して後始末だけ失敗した場合は成功扱いにせず 2）。後始末は自分の一時名（dst 配下の `.<name>.syncing-<pid>`）以外・`..` を含む path・symlink を消さない。終了コードの契約（0 / 2 / 4）と呼び出し側の解釈は不変 |
| closure test | 権限 matrix 74/74 PASS（本テスト FAIL → PASS）、`tests/test_mirror_sync_exit_code.py`（A〜E・path 拒否）。macOS の一般ユーザーで traverse できない directory を使った再現も exit 1 → 2 |
| closed_at | 2026-10-12 |

## triage 記録（2026-10-12、HEAD ee944e9）

開始時の full regression: 2312 passed / 11 failed / 16 skipped。11 件はすべて単独実行でも再現した。
Linux（backend-public image、arm64）では #2 だけが PASS し、残りは同じく失敗した（#9 は container 内に Docker が無く skip）。

| # | テスト | 原因 | first-bad | 分類 | 判定 | 優先度 | 結果 |
|---|---|---|---|---|---|---|---|
| 1 | `test_phase2b1_entrypoint_boundary.py::test_all_public_routes_match_exact_allowlist` | storm_surge / tsunami の GeoJSON を catch-all から専用 streaming route へ移した（URL の範囲は同じ）のに allowlist が未更新 | 765f4f7・564ea02（2026-09-12） | C | NON_BLOCKER | P1 | 修正（45 → 47 件、完全一致の検査は維持） |
| 2 | `test_phase2b6_rollback.py::test_rollback_isolated_setup_and_reader_observation` | renameat2 は Linux 専用 | — | E・F | NON_BLOCKER | P3 | KTF-001 として記録 → 同日 CLOSED（Linux container 委譲） |
| 3 | `navigation/test_interaction.py::test_interaction_matrix` | sweep から閾値 100 を外したのに、テストが rt=100 を探して StopIteration。後続の assertion は実行されていなかった | b0a044f（2026-04-23） | F・C | NON_BLOCKER | P2 | 修正（sweep の最大値を使い、全 cell の存在も検査。後続の assertion も PASS） |
| 4 | `test_hazard_layers_source_guards.py::test_hazard_layer_source_routing` | storm_surge は vector tile へ移行（preferApi 削除）、旧 tile `tokyo_storm_surge` は退役、tileset ID は /meta から解決 | b9b43c0（2026-04-12）・4e4af1e・88ce04d（2026-09-05） | C | NON_BLOCKER | P2 | 修正（現行の契約を検査し、旧 tile ID・旧解決方式が戻らないことも検査） |
| 5 | `test_hazard_layers_source_guards.py::test_set_visibility_has_simple_on_off_branches` | 表示 ON の追加処理が zoom 帯の `_applyZoomBandToLayer` へ移った（二重追加の guard は維持） | 5d78030（2026-05-01） | C | NON_BLOCKER | P2 | 修正 |
| 6 | `test_live_kikikuru_summary_service.py::test_no_danger_detected_false` | watch（注意）も areas に含める仕様へ変更。danger_detected は warning / danger のみ | ce40b18（2026-06-03） | C | NON_BLOCKER | P2 | 修正 |
| 7 | `test_live_kikikuru_summary_service.py::test_watch_does_not_enter_areas` | 同上 | ce40b18 | C | NON_BLOCKER | P2 | 修正（並び順 danger > warning > watch のテストを追加） |
| 8 | `test_live_train_service.py::test_fetch_all_disruptions_filters_challenge_items` | ODPT operator allowlist（TokyoMetro / Toei）導入後、JR-West は fail closed で表示されない。テストは環境変数を直接書き換えていた | 265dd12（2026-08-30） | C・F | NON_BLOCKER | P2 | 修正（allowlist の operator を使い、allowlist 外の拒否も検査。monkeypatch へ変更） |
| 9 | `test_runtime_mbtiles_group_contract.py::test_C_permission_matrix_...` | (a) 素の python:3.11-slim に ijson が無く stream 系 2 項目が import 失敗、(b) mirror script の exit コード | (a) 6b61b6d（2026-10-11）、(b) 660cf34（2026-10-06） | (a) F、(b) A・H | NON_BLOCKER | P3 | (a) 修正（backend-public image で実行）、(b) KTF-002 として記録 → 同日 CLOSED |
| 10 | `test_safety_critical.py::test_unknown_hazard_text_constant_is_defined` | 公開準備で肯定的な安全表現をやめ、`UNKNOWN_HAZARD_TEXT` を `SOURCE_UNAVAILABLE_TEXT` へ置き換えた（unknown を安全と表示しない分岐は維持） | 265dd12（2026-08-30） | C | NON_BLOCKER | P2 | 修正（新しい定数・unknown 分岐での使用・文言に「安全」を含まないことを検査） |
| 11 | `test_safety_critical.py::test_assess_candidate_tsunami_outside_when_full_coverage` | flood / tsunami の読み込み判定が numpy bbox 配列へ移ったのに、テストが `_polygons` を直接書き換えていたため未読み込み扱い（unknown）になった。製品は安全側 | 8588221（2026-04-18） | F | NON_BLOCKER | P2 | 修正（本番と同じ `load_geojson_streaming(bbox_only=True)` で読み込む） |

関連して見つけて直したもの:

- `test_assess_candidate_injects_unknown_when_coverage_incomplete` は #11 と同じ理由で、coverage の guard を通らずに
  unknown になり PASS していた。正規の読み込み経路に揃え、guard を無効にすると失敗することを確認した。
- `tests/navigation/conftest.py` は、一部のテストだけを実行しても、追跡対象の `reports/parameter_sweep/*.md` を
  部分的な結果で上書きしていた。3 種類の sweep がすべて実行されたときだけ書くようにした。
