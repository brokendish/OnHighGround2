#!/usr/bin/env python3
"""
resolve_shelter_sources.py — 避難所系 active dataset の validated artifact path を
registry（active_mappings.json + dataset_definitions.json + DatasetState）から
解決する。

shelter_atomic_publish修復（tasks/public-release/shelter_count_difference_
investigation_claude.md）: 従来 deploy_to_runtime.sh は
`${VALIDATED}/shelter` というハードコードされた単一directory名だけを
publishしており、registryに登録されたactive datasetのうち3/4が
path名不一致のため常にatomic publishから欠落していた
（TOKYO-EVAC-001, KANAGAWA-EVAC-001、および正式pathの
TOKYO-SHELTER-001）。本scriptはこの「directory名の一致」という脆い判定を
やめ、`app.services.shelter_service.SHELTER_LAYER_TYPES`
（読み取り側 `ShelterRegistry._resolve_paths()` と共有する単一の定数）に
一致するlayer_typeのactive mappingを列挙し、指定regionの分だけ
`<dataset_id>\t<resolved_path>` をTSVで標準出力へ書く。

解決できないdatasetはSTDERRへ警告するだけで、呼び出し元（deploy_to_runtime.sh）の
publish全体は失敗させない（既存の「個々のsourceが無ければskipして継続する」
方針——deploy_file/deploy_dirのSource not found警告——と一致させる）。

使い方（backend-operator container内、activate_version.py等と同じ
`backend/` が `/app` へmountされる前提）:
    python3 resolve_shelter_sources.py --region tokyo
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/app")  # backend/ が /app へmountされるcontainer前提（activate_version.pyと同一規約）

from app.services.active_mapping_service import get_active_mapping_service  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402
from app.services.dataset_state_service import (  # noqa: E402
    _PROJECT_ROOT as BACKEND_PROJECT_ROOT,
    get_state_service,
)
from app.services.shelter_service import SHELTER_LAYER_TYPES  # noqa: E402


def _resolve_validated_path(defn, state) -> "Path | None":
    """dataset定義とstateから、実際にdiskへ存在するvalidated artifactを1つ返す。

    優先順位: state.current_validated_path（stateが自己修復で無効化されていなければ
    最新の実体を指す）→ defn.validated_storage_path（registry定義の既定path、
    state未確定時のfallback）。どちらも存在しない/diskに無い場合は None。
    """
    if state.current_validated_path:
        p = Path(state.current_validated_path)
        if p.exists():
            return p
    if defn.validated_storage_path:
        p = (BACKEND_PROJECT_ROOT / defn.validated_storage_path).resolve()
        if p.exists():
            return p
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", required=True)
    args = parser.parse_args()

    ams = get_active_mapping_service()
    ds_svc = get_definition_service()
    ss_svc = get_state_service()

    resolved_count = 0
    for mapping in ams.list_all():
        if mapping["layer_type"] not in SHELTER_LAYER_TYPES:
            continue
        if mapping["region"] != args.region:
            continue

        dataset_id = mapping["dataset_id"]
        defn = ds_svc.get(dataset_id)
        if defn is None:
            print(
                f"[resolve_shelter_sources] WARN: active mapping先のdataset定義が"
                f"registryに見つかりません: {dataset_id}",
                file=sys.stderr,
            )
            continue

        state = ss_svc.init_from_definition(defn)
        candidate = _resolve_validated_path(defn, state)
        if candidate is None:
            print(
                f"[resolve_shelter_sources] WARN: {dataset_id} は active だが "
                f"validated artifactが解決できません（登録済みだが未配備の可能性）",
                file=sys.stderr,
            )
            continue

        print(f"{dataset_id}\t{candidate}")
        resolved_count += 1

    print(
        f"[resolve_shelter_sources] region={args.region}: {resolved_count}件のactive shelter datasetを解決",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
