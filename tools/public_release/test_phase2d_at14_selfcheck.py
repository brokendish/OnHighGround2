"""
test_phase2d_at14_selfcheck.py — AT-14 checkロジック自体のnegative/positive mutation test。

指示書第11節「tool自身についてpositive/negative mutation testを作る」への対応。
最低10種のmutation（LICENSE一部欠落・inventory ID duplicate・terms URL欠落・
tracked dataのmapping欠落・NOT_CONFIRMED bundled artifact・attribution文言欠落・
README broken link・secret canary混入・`/Users/...`path混入・`.env.operator`追跡）
それぞれについて、mutationが検出される（FAIL）ことと、正常な入力ではPASSすることの
両方を確認する。

実行方法:
    venv/bin/python -m pytest tools/public_release/test_phase2d_at14_selfcheck.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase2d_at14_check as at14  # noqa: E402

GOOD_LICENSE = "\n".join(at14.MIT_CANONICAL_SENTENCES) + f"\n\n{at14.COPYRIGHT_LINE}\n"

GOOD_SECTION8 = """
## 8. 機械可読分類サマリー

説明文中にも`NOT_CONFIRMED`という語（許可status一覧の定義）が出てくるが、これは
prose中の言及でありcheck 10の分母には含めない。

| ID | DistributionClass | ArtifactClass | Status | TermsURL | ReqAttr | UIMapping | CheckedAt | OwnerAction |
|---|---|---|---|---|---|---|---|---|
| GEO-OSM-ROAD | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live | 2026-08-21 | N |
| GEO-OSM-RAIL | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live | 2026-08-21 | N |
| API-JMA-QUAKE | API_ONLY | external_api | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /live | 2026-08-21 | N |
| CDN-LEAFLET | CDN_ONLY | cdn_library | CONFIRMED_RUNTIME_ONLY | Y | Y | N/A | 2026-08-21 | N |
"""

GOOD_INVENTORY = """
| ID | Name | Status |
|---|---|---|
| GEO-OSM-ROAD | road | CONFIRMED_ATTRIBUTION_REQUIRED |
| GEO-OSM-RAIL | rail | CONFIRMED_ATTRIBUTION_REQUIRED |

`frontend/layers/roads/kanto_roads_main.geojson` — checked at 2026-08-21.
Terms: https://www.openstreetmap.org/copyright
出典：© OpenStreetMap contributors
## UI attribution 実地確認（`/`, `/live`, `/live/stream`）
""" + GOOD_SECTION8

GOOD_ATTRIBUTIONS = (
    "OpenStreetMap contributors\n国土交通省\n気象庁\nOpen-Meteo\n加工して作成\n"
)

GOOD_README = (
    "[LICENSE](LICENSE) [ATTRIBUTIONS.md](ATTRIBUTIONS.md) "
    "[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) "
    "[docs/third-party-inventory.md](docs/third-party-inventory.md) "
    "[docs/installation.md](docs/installation.md) "
    "[docs/configuration.md](docs/configuration.md) "
    "[docs/operator-setup.md](docs/operator-setup.md)\n"
)


# ---------------------------------------------------------------------------
# Mutation 1: LICENSE一部欠落
# ---------------------------------------------------------------------------

def test_mutation_license_missing_sentence_detected():
    mutated = GOOD_LICENSE.replace(at14.MIT_CANONICAL_SENTENCES[0] + "\n", "")
    result = at14.check_mit_full_text(mutated)
    assert result.passed is False
    assert result.evidence_count == 1


def test_positive_control_license_full_text_passes():
    result = at14.check_mit_full_text(GOOD_LICENSE)
    assert result.passed is True


def test_mutation_license_missing_copyright_detected():
    mutated = GOOD_LICENSE.replace(at14.COPYRIGHT_LINE, "Copyright (c) 2026 Someone Else")
    result = at14.check_copyright_line(mutated)
    assert result.passed is False


def test_positive_control_copyright_line_passes():
    result = at14.check_copyright_line(GOOD_LICENSE)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Mutation 2: inventory ID duplicate
# ---------------------------------------------------------------------------

def test_mutation_inventory_id_duplicate_detected():
    mutated = GOOD_INVENTORY.replace("| GEO-OSM-RAIL |", "| GEO-OSM-ROAD |")
    result = at14.check_inventory_id_duplicates(mutated)
    assert result.passed is False
    assert "GEO-OSM-ROAD" in result.detail


def test_positive_control_inventory_no_duplicates_passes():
    result = at14.check_inventory_id_duplicates(GOOD_INVENTORY)
    assert result.passed is True
    assert result.evidence_count == 0


# ---------------------------------------------------------------------------
# Mutation 3: terms URL欠落
# ---------------------------------------------------------------------------

def test_mutation_terms_url_missing_detected():
    sparse = "| ID | Name |\n|---|---|\n| X | y |\n"
    result = at14.check_terms_url_present(sparse)
    assert result.passed is False


def test_positive_control_terms_url_present_passes():
    rich = "https://a.example/1 https://b.example/2 https://c.example/3 https://d.example/4 " \
           "https://e.example/5 https://f.example/6 https://g.example/7 https://h.example/8 " \
           "https://i.example/9 https://j.example/10 " + GOOD_INVENTORY
    result = at14.check_terms_url_present(rich)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Mutation 4: tracked dataのmapping欠落（unmapped artifact）
# ---------------------------------------------------------------------------

def test_mutation_tracked_data_mapping_missing_detected():
    tracked = ["frontend/layers/roads/kanto_roads_main.geojson", "frontend/layers/roads/UNMAPPED_FILE.geojson"]
    result = at14.check_tracked_geo_files_mapped(tracked, GOOD_INVENTORY)
    assert result.passed is False
    assert "UNMAPPED_FILE.geojson" in result.detail


def test_positive_control_tracked_data_all_mapped_passes():
    tracked = ["frontend/layers/roads/kanto_roads_main.geojson"]
    result = at14.check_tracked_geo_files_mapped(tracked, GOOD_INVENTORY)
    assert result.passed is True


def test_glob_mapping_is_accepted_per_section_4_3():
    inventory_with_glob = "path token: `frontend/layers/administrative/*.geojson`\n"
    tracked = ["frontend/layers/administrative/municipality_boundaries/chubu.geojson"]
    result = at14.check_tracked_geo_files_mapped(tracked, inventory_with_glob)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Mutation 5: NOT_CONFIRMED bundled artifact
# ---------------------------------------------------------------------------

def test_mutation_not_confirmed_artifact_detected():
    # GEO-OSM-ROADはSection 8でDistributionClass=TRACKEDのため、
    # StatusをNOT_CONFIRMEDへ変異させるとcheck 10はFAILしなければならない。
    mutated = GOOD_INVENTORY.replace(
        "| GEO-OSM-ROAD | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED |",
        "| GEO-OSM-ROAD | TRACKED | geo_data | NOT_CONFIRMED |",
    )
    result = at14.check_not_confirmed_zero(mutated)
    assert result.passed is False
    assert result.evidence_count == 1
    assert "GEO-OSM-ROAD" in result.detail


def test_positive_control_zero_not_confirmed_passes():
    result = at14.check_not_confirmed_zero(GOOD_INVENTORY)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Mutation 6: attribution文言欠落
# ---------------------------------------------------------------------------

def test_mutation_attribution_wording_missing_detected():
    mutated = GOOD_ATTRIBUTIONS.replace("気象庁\n", "")
    result = at14.check_attribution_wording_present(mutated)
    assert result.passed is False
    assert "気象庁" in result.detail


def test_positive_control_attribution_wording_present_passes():
    result = at14.check_attribution_wording_present(GOOD_ATTRIBUTIONS)
    assert result.passed is True


def test_mutation_modification_notice_missing_detected():
    mutated = GOOD_ATTRIBUTIONS.replace("加工して作成\n", "")
    result = at14.check_modification_notice_present(mutated)
    assert result.passed is False


# ---------------------------------------------------------------------------
# Mutation 7: README broken link
# ---------------------------------------------------------------------------

def test_mutation_readme_broken_link_detected(tmp_path):
    (tmp_path / "LICENSE").write_text("x", encoding="utf-8")
    # ATTRIBUTIONS.md をわざと作らない -> broken link
    readme = "[LICENSE](LICENSE) [ATTRIBUTIONS.md](ATTRIBUTIONS.md)\n"
    result = at14.check_no_broken_relative_links({"README.md": readme}, tmp_path)
    assert result.passed is False
    assert "ATTRIBUTIONS.md" in result.detail


def test_positive_control_readme_links_all_resolve(tmp_path):
    (tmp_path / "LICENSE").write_text("x", encoding="utf-8")
    (tmp_path / "ATTRIBUTIONS.md").write_text("x", encoding="utf-8")
    readme = "[LICENSE](LICENSE) [ATTRIBUTIONS.md](ATTRIBUTIONS.md)\n"
    result = at14.check_no_broken_relative_links({"README.md": readme}, tmp_path)
    assert result.passed is True


def test_mutation_required_readme_link_missing_detected():
    mutated = GOOD_README.replace("[docs/operator-setup.md](docs/operator-setup.md)", "")
    result = at14.check_readme_links(mutated)
    assert result.passed is False
    assert "docs/operator-setup.md" in result.detail


def test_positive_control_readme_links_complete_passes():
    result = at14.check_readme_links(GOOD_README)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Mutation 8: secret canary混入
# ---------------------------------------------------------------------------

def test_mutation_secret_canary_detected():
    poisoned = {"backend/.env.example": "ODPT_API_KEY=abcdef0123456789ZZZZ_realsecretvalue\n"}
    result = at14.check_no_secret_values(poisoned)
    assert result.passed is False
    assert "ODPT_API_KEY" in result.detail


def test_mutation_aws_style_secret_detected():
    poisoned = {"some.md": "key = AKIAABCDEFGHIJKLMNOP\n"}
    result = at14.check_no_secret_values(poisoned)
    assert result.passed is False


def test_positive_control_empty_secret_field_passes():
    clean = {"backend/.env.example": "ODPT_API_KEY=\n# JARTIC_API_KEY=your_jartic_key_here\n"}
    result = at14.check_no_secret_values(clean)
    assert result.passed is True


def test_empty_key_followed_by_unrelated_text_does_not_cross_line_false_positive():
    # 回帰テスト: `\s*`がKEY=直後の改行を飛び越えて数行後の無関係な文章を
    # 値として誤って取り込んでいたbugの再発防止（同一行内のみを値とみなす）。
    clean = {
        "backend/.env.example": (
            "ODPT_API_KEY=\n"
            "\n"
            "# ---- non-secret section header text that must not be treated as the value ----\n"
        )
    }
    result = at14.check_no_secret_values(clean)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Mutation 9: `/Users/...` path混入
# ---------------------------------------------------------------------------

def test_mutation_absolute_user_path_detected():
    poisoned = {"docs/installation.md": "cd /Users/hideki/Documents/GitHub/OnHighGround2\n"}
    result = at14.check_no_absolute_local_paths(poisoned)
    assert result.passed is False
    assert "/Users/hideki" in result.detail


def test_mutation_home_path_detected():
    poisoned = {"docs/x.md": "see /home/alice/secret\n"}
    result = at14.check_no_absolute_local_paths(poisoned)
    assert result.passed is False


def test_positive_control_relative_path_only_passes():
    clean = {"docs/installation.md": "cd OnHighGround2 && cp backend/.env.example .env\n"}
    result = at14.check_no_absolute_local_paths(clean)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Mutation 10: `.env.operator`追跡
# ---------------------------------------------------------------------------

def test_mutation_env_operator_tracked_detected():
    tracked = ["README.md", ".env.operator", "backend/main.py"]
    result = at14.check_env_operator_not_tracked(tracked)
    assert result.passed is False
    assert ".env.operator" in result.detail


def test_positive_control_env_operator_absent_passes():
    tracked = ["README.md", ".env.operator.example", "backend/main.py"]
    result = at14.check_env_operator_not_tracked(tracked)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 追加: real VPS IP mutation（第14節該当）
# ---------------------------------------------------------------------------

def test_mutation_real_public_ip_detected():
    poisoned = {"docs/operator-setup.md": "connect to 203.0.113.42 directly\n"}
    result = at14.check_no_real_vps_ip(poisoned)
    assert result.passed is False


def test_positive_control_loopback_ip_passes():
    clean = {"docs/operator-setup.md": "loopback bind 127.0.0.1 only\n"}
    result = at14.check_no_real_vps_ip(clean)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 追加: blanket re-license phrasing mutation（第17 check該当）
# ---------------------------------------------------------------------------

def test_mutation_blanket_relicense_phrasing_detected():
    result = at14.check_no_blanket_relicense("all data is MIT licensed", "")
    assert result.passed is False


def test_positive_control_no_blanket_relicense_passes():
    result = at14.check_no_blanket_relicense(GOOD_LICENSE, GOOD_ATTRIBUTIONS)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 追加: placeholder token mutation（第18 check該当）
# ---------------------------------------------------------------------------

def test_mutation_todo_placeholder_detected():
    result = at14.check_no_placeholder_tokens({"docs/x.md": "TODO: fill this in later\n"})
    assert result.passed is False


def test_mutation_tbd_placeholder_detected():
    result = at14.check_no_placeholder_tokens({"docs/x.md": "source: TBD\n"})
    assert result.passed is False


def test_positive_control_no_placeholder_tokens_passes():
    result = at14.check_no_placeholder_tokens({"docs/x.md": "source: confirmed via official page\n"})
    assert result.passed is True


# ---------------------------------------------------------------------------
# 追加: env example key coverage mutation（第23 check該当）
# ---------------------------------------------------------------------------

def test_mutation_env_example_missing_key_detected():
    result = at14.check_env_example_key_coverage("API_HOST=0.0.0.0\n", {"ODPT_API_KEY"})
    assert result.passed is False
    assert "ODPT_API_KEY" in result.detail


def test_positive_control_env_example_covers_actual_keys_passes():
    result = at14.check_env_example_key_coverage("ODPT_API_KEY=\nOTHER=1\n", {"ODPT_API_KEY"})
    assert result.passed is True


# ---------------------------------------------------------------------------
# 追加: multi-map mutation（第12 check該当）
# ---------------------------------------------------------------------------

def test_mutation_unexpected_multimap_detected():
    inventory = (
        "| AA-1 | x | `frontend/layers/roads/dup.geojson` |\n"
        "| AA-2 | y | `frontend/layers/roads/dup.geojson` |\n"
    )
    result = at14.check_no_unexpected_multimap(inventory)
    assert result.passed is False
    assert "frontend/layers/roads/dup.geojson" in result.detail


def test_positive_control_no_multimap_passes():
    inventory = (
        "| AA-1 | x | `frontend/layers/roads/one.geojson` |\n"
        "| AA-2 | y | `frontend/layers/roads/two.geojson` |\n"
    )
    result = at14.check_no_unexpected_multimap(inventory)
    assert result.passed is True


def test_bare_filename_generic_mention_is_not_multimap_false_positive():
    inventory = (
        "| AA-1 | x | `meta.json` describes dataset A |\n"
        "| AA-2 | y | `meta.json` describes dataset B |\n"
    )
    result = at14.check_no_unexpected_multimap(inventory)
    assert result.passed is True


# ---------------------------------------------------------------------------
# 追加: empty table cell mutation（第9 check該当、行境界の誤検出回帰）
# ---------------------------------------------------------------------------

def test_mutation_empty_table_cell_detected():
    inventory = "| A | B |  | D |\n"
    result = at14.check_no_empty_table_cells(inventory)
    assert result.passed is False


def test_row_boundary_is_not_mistaken_for_empty_cell():
    # 行末の `|` と次行冒頭の `|` の間には改行があるだけで、これは空セルではない
    inventory = "| A | B |\n| C | D |\n"
    result = at14.check_no_empty_table_cells(inventory)
    assert result.passed is True


# ---------------------------------------------------------------------------
# Round 2: 指示書第4.3節が要求する12種のmutation（P2D-AT14-SEMANTIC対応）
# ---------------------------------------------------------------------------

_ROUND2_SECTION8_BASE = (
    "\n## 8. 機械可読分類サマリー\n\n"
    "NOT_CONFIRMEDは許可status一覧の一つである（この一文自体はprose中の言及）。\n\n"
    "| ID | DistributionClass | ArtifactClass | Status | TermsURL | ReqAttr | UIMapping | CheckedAt | OwnerAction |\n"
    "|---|---|---|---|---|---|---|---|---|\n"
    "| RR-TRACKED | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live | 2026-08-21 | N |\n"
    "| RR-RUNTIME | RUNTIME_ONLY | hazard_data | NOT_CONFIRMED | Y | Y | NONE | 2026-08-21 | Y |\n"
    "| RR-CDN | CDN_ONLY | cdn_library | NOT_CONFIRMED | Y | Y | N/A | 2026-08-21 | Y |\n"
)

_DEFINITION_TABLE = (
    "\n許可statusの定義表:\n\n"
    "| status | 意味 |\n"
    "|---|---|\n"
    "| NOT_CONFIRMED | 未確認 |\n"
)


def test_r2_mutation_01_prose_not_confirmed_not_counted():
    text = "説明文中でNOT_CONFIRMEDについて述べる。\n" + _ROUND2_SECTION8_BASE
    result = at14.check_not_confirmed_zero(text)
    # RR-RUNTIME/RR-CDNはNOT_CONFIRMEDだがTRACKED/BUNDLED/REDISTRIBUTEDではないためFAILしない
    assert result.passed is True, result.detail


def test_r2_mutation_02_definition_table_not_counted():
    text = _DEFINITION_TABLE + _ROUND2_SECTION8_BASE.replace("NOT_CONFIRMED", "CONFIRMED_ATTRIBUTION_REQUIRED")
    result = at14.check_not_confirmed_zero(text)
    assert result.passed is True, result.detail


def test_r2_mutation_03_runtime_only_row_not_counted_in_check10():
    text = _ROUND2_SECTION8_BASE  # RR-RUNTIME is NOT_CONFIRMED but RUNTIME_ONLY
    result = at14.check_not_confirmed_zero(text)
    assert result.passed is True, result.detail
    assert "RR-RUNTIME" not in result.detail


def test_r2_mutation_04_cdn_only_row_not_counted_in_check10():
    text = _ROUND2_SECTION8_BASE  # RR-CDN is NOT_CONFIRMED but CDN_ONLY
    result = at14.check_not_confirmed_zero(text)
    assert result.passed is True, result.detail
    assert "RR-CDN" not in result.detail


def test_r2_mutation_05_tracked_row_not_confirmed_fails():
    text = _ROUND2_SECTION8_BASE.replace(
        "| RR-TRACKED | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED |",
        "| RR-TRACKED | TRACKED | geo_data | NOT_CONFIRMED |",
    )
    result = at14.check_not_confirmed_zero(text)
    assert result.passed is False
    assert "RR-TRACKED" in result.detail


def test_r2_mutation_06_bundled_row_not_confirmed_fails():
    text = _ROUND2_SECTION8_BASE + "| RR-BUNDLED | BUNDLED | software_dependency | NOT_CONFIRMED | Y | Y | N/A | 2026-08-21 | Y |\n"
    result = at14.check_not_confirmed_zero(text)
    assert result.passed is False
    assert "RR-BUNDLED" in result.detail


def test_r2_mutation_07_redistributed_row_not_confirmed_fails():
    text = _ROUND2_SECTION8_BASE + "| RR-REDIST | REDISTRIBUTED | geo_data | NOT_CONFIRMED | Y | Y | N/A | 2026-08-21 | Y |\n"
    result = at14.check_not_confirmed_zero(text)
    assert result.passed is False
    assert "RR-REDIST" in result.detail


def test_r2_mutation_08_column_count_mismatch_is_fail_closed_harness_error():
    broken = _ROUND2_SECTION8_BASE.replace(
        "| RR-TRACKED | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live | 2026-08-21 | N |",
        "| RR-TRACKED | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live | 2026-08-21 |",  # 1列欠落
    )
    result = at14.check_not_confirmed_zero(broken)
    assert result.passed is False
    assert "HARNESS_ERROR" in result.detail


def test_r2_mutation_08b_empty_cell_is_fail_closed():
    text = "| A | B |  | D |\n"
    result = at14.check_no_empty_table_cells(text)
    assert result.passed is False


def test_r2_mutation_09_duplicate_source_id_in_section8_fails():
    dup = _ROUND2_SECTION8_BASE + "| RR-TRACKED | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | NONE | 2026-08-21 | N |\n"
    result = at14.check_not_confirmed_zero(dup)
    assert result.passed is False
    assert "HARNESS_ERROR" in result.detail
    assert "duplicate" in result.detail.lower()


def test_r2_mutation_10_unknown_distribution_class_fails():
    bad = _ROUND2_SECTION8_BASE.replace("| RR-TRACKED | TRACKED |", "| RR-TRACKED | SOMETHING_UNKNOWN |")
    result = at14.check_not_confirmed_zero(bad)
    assert result.passed is False
    assert "HARNESS_ERROR" in result.detail


def test_r2_mutation_11_runtime_source_missing_ui_mapping_is_reported():
    text = _ROUND2_SECTION8_BASE.replace(
        "| RR-TRACKED | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | /,/live | 2026-08-21 | N |",
        "| RR-TRACKED | TRACKED | geo_data | CONFIRMED_ATTRIBUTION_REQUIRED | Y | Y | NONE | 2026-08-21 | N |",
    )
    result = at14.check_runtime_attribution_has_ui_mapping(text)
    assert result.passed is False
    assert "RR-TRACKED" in result.detail


def test_r2_mutation_11b_positive_control_ui_mapping_present_passes():
    result = at14.check_runtime_attribution_has_ui_mapping(_ROUND2_SECTION8_BASE)
    assert result.passed is True


def test_r2_mutation_12_odpt_allowlist_missing_license_mapping_fails():
    entries = [{"operator_id": "TokyoMetro", "license": "公共交通オープンデータ基本ライセンス"}, {"operator_id": "Unknown", "license": ""}]
    result = at14.check_odpt_allowlist_mapping(entries)
    assert result.passed is False
    assert "Unknown" in result.detail


def test_r2_mutation_12b_odpt_allowlist_all_mapped_passes():
    entries = [{"operator_id": "TokyoMetro", "license": "公共交通オープンデータ基本ライセンス"}, {"operator_id": "Toei", "license": "CC BY 4.0"}]
    result = at14.check_odpt_allowlist_mapping(entries)
    assert result.passed is True


def test_r2_mutation_12c_odpt_allowlist_none_not_yet_implemented_fails():
    result = at14.check_odpt_allowlist_mapping(None)
    assert result.passed is False


# ---------------------------------------------------------------------------
# check 08 (ID重複) のtable-scope化に対する回帰テスト
# ---------------------------------------------------------------------------

def test_same_id_in_narrative_table_and_section8_is_not_a_false_duplicate():
    text = (
        "| ID | Name |\n|---|---|\n| DUP-1 | narrative row |\n\n"
        + _ROUND2_SECTION8_BASE.replace("RR-TRACKED", "DUP-1")
    )
    result = at14.check_inventory_id_duplicates(text)
    assert result.passed is True, result.detail


def test_true_duplicate_within_same_table_is_detected():
    text = "| ID | Name |\n|---|---|\n| DUP-2 | row1 |\n| DUP-2 | row2 |\n"
    result = at14.check_inventory_id_duplicates(text)
    assert result.passed is False
    assert "DUP-2" in result.detail


# ---------------------------------------------------------------------------
# P2D-README-COMMAND: command_doc_parityの回帰test（旧実装のdead-check bug修正）
# ---------------------------------------------------------------------------

import phase2d_at17_clean_clone as at17  # noqa: E402


def test_command_parity_detects_stale_service_name_regression():
    # 旧実装は「real_servicesに含まれるtokenだけをreferencedへ追加する」filterを
    # 持っていたため、存在しないservice名（例: 単なる`backend`）はreferenced集合へ
    # そもそも入らず、unknown_services_in_docsが常に空になる構造的欠陥があった。
    # この回帰testは、実在しないservice名を含むtextを渡した場合に正しくunknownとして
    # 検出されることを確認する。
    fake_text = "docker compose up -d osrm-driving osrm-walking backend frontend\n"
    referenced = at17._extract_referenced_service_tokens(fake_text)
    assert "backend" in referenced
    assert "backend-public" not in referenced  # 呼んでいないものを誤検出しない


def test_command_parity_exec_only_captures_first_token_as_service():
    text = "docker compose exec backend-public curl -sf http://localhost:8000/health\n"
    referenced = at17._extract_referenced_service_tokens(text)
    assert referenced == {"backend-public"}
    assert "curl" not in referenced
    assert "http" not in referenced


def test_command_parity_real_readme_and_installation_have_no_unknown_services():
    result = at17.command_doc_parity()
    assert result["ok"] is True, result["unknown_services_in_docs"]
