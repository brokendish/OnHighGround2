"""
odpt_allowlist.py — ODPT operator license allowlist（Phase 2-D Round 2、P2D-ODPT-TERMS対応）

指示書Round 2第7節「source-controlledな明示allowlist」の実装。

設計原則（fail-closed）:
  - allowlist（`odpt_allowlist_data.json`）に明示的に登録されたoperatorのデータのみを
    処理・cache・表示する。登録されていないoperator（unknown）は常に拒否する。
  - 「従来どおり表示」へのfallbackは行わない（unknown operatorのpayloadは
    キャッシュに書き込まず、UIへ渡さない）。
  - challenge限定・期間限定・license不明のoperatorは初期allowlistに含めない
    （JR-Eastは「公共交通オープンデータチャレンジ限定ライセンス」のため意図的に
    allowlist対象外——2026-08-21にckan.odpt.orgで確認済み）。
  - allowlistが空、またはJSON parse不能の場合はfail-closed（全operatorを拒否する）。

allowlist拡張手順:
  1. `https://ckan.odpt.org/organization/<operator-slug>` で対象operatorの
     公式license欄を確認する（検索結果・第三者情報は根拠にしない）。
  2. license名がPDL1.0/CC BY系等、再配布・表示が明確に許可されるものであることを確認する。
  3. `odpt_allowlist_data.json` へ1 entry追加する（`confirmed_date`は確認日）。
  4. `tools/public_release/phase2d_at14_check.py` のcheck 29/30を再実行し、
     license mapping欠落がないことを確認する。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parent / "odpt_allowlist_data.json"

_allowlist_cache: Optional[List[Dict[str, Any]]] = None


def _load_allowlist() -> List[Dict[str, Any]]:
    """allowlist JSONを読み込む。parse不能・空・schema不正の場合はfail-closedで
    空listを返す（=全operator拒否）。例外を握りつぶして「従来どおり許可」に
    フォールバックしない。"""
    global _allowlist_cache
    if _allowlist_cache is not None:
        return _allowlist_cache

    try:
        raw = _DATA_PATH.read_text(encoding="utf-8")
        entries = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("odpt_allowlist: failed to load %s: %s (fail-closed: denying all operators)", _DATA_PATH, exc)
        _allowlist_cache = []
        return _allowlist_cache

    if not isinstance(entries, list):
        logger.error("odpt_allowlist: %s did not contain a JSON list (fail-closed: denying all operators)", _DATA_PATH)
        _allowlist_cache = []
        return _allowlist_cache

    valid_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        operator_id = entry.get("operator_id")
        license_name = entry.get("license")
        if not operator_id or not license_name:
            logger.error("odpt_allowlist: entry missing operator_id/license, skipping: %r", entry)
            continue
        valid_entries.append(entry)

    _allowlist_cache = valid_entries
    return _allowlist_cache


def get_allowlist_entries() -> List[Dict[str, Any]]:
    """テスト・AT-14 checker用に、読み込んだallowlist全体を返す。"""
    return list(_load_allowlist())


def get_allowed_operator_ids() -> set:
    return {e["operator_id"] for e in _load_allowlist()}


def is_operator_allowed(operator_id: str) -> bool:
    """operator_idがallowlistに存在すればTrue。存在しない場合は常にFalse
    （fail-closed、unknown operatorへのfallback許可なし）。"""
    if not operator_id:
        return False
    return operator_id in get_allowed_operator_ids()


def get_operator_license_info(operator_id: str) -> Optional[Dict[str, Any]]:
    """UI表示用に、operatorのlicense/terms/confirmed_date等を返す。
    allowlist外の場合はNone（呼び出し側はitem自体を表示しない設計にすること）。"""
    for entry in _load_allowlist():
        if entry.get("operator_id") == operator_id:
            return entry
    return None


def reset_cache_for_testing() -> None:
    """testでallowlist内容を差し替える際に使う（productionコードパスからは呼ばない）。"""
    global _allowlist_cache
    _allowlist_cache = None
