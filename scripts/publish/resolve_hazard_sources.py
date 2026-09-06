#!/usr/bin/env python3
"""
resolve_hazard_sources.py — hazard系 active dataset の validated artifact path を
registry（active_mappings.json + dataset_definitions.json + DatasetState）から
解決する。

Dual Storage Remediation Phase C1（ATOMIC-PUBLISH-COVERAGE-GAP）:
deploy_to_runtime.sh はstorm_surge/floodについて旧underscore命名
（${REGION}_storm_surge.geojson、${REGION}_flood_check.geojsonl）をハード
コードして探しているが、admin dataset pipelineが実際に生成するvalidated
artifactはhyphen/registry命名（例: tokyo-surge-001.geojson、
tokyo-river-001.geojson）であるため、命名不一致によりsourceが常に
見つからずsilent skipしていた（実機調査で確認済み）。pseudo_inland_flood
に至ってはこのscriptにbackend deploy用の対応が一度も追加されていなかった。

本scriptは、resolve_shelter_sources.py（shelter_atomic_publish修復、
tasks/public-release/shelter_count_difference_investigation_claude.md）と
同じ設計思想——「directory名/filenameのハードコード一致」という脆い判定を
やめ、registryを正本としてactive datasetを動的に解決する——を、対象
hazard type（--layer-typeで明示指定、複数指定可）についてのみ適用する。

shelter resolverとの違い:
  - destination contractがdataset_id別subdirectoryではなく
    backend/hazard/{layer_type}/{region}/{file} という既存versioned
    hazard構造（tsunami/inland_flood/landslide/lowland_poor_drainageが
    既に使っている構造）に合わせる必要があるため、出力にlayer_typeを含む。
  - 「登録上activeなのにsourceが解決できない」場合はWARNで継続せず、
    fail-closedで即座に失敗する（今回のremediationの根本原因が
    「サイレントスキップ」であるため、再発させない）。

出力（全件解決に成功した場合のみ、成功前に部分出力しない）:
    <layer_type>\t<dataset_id>\t<resolved_path>

使い方（backend-operator container内、activate_version.py等と同じ
`backend/` が `/app` へmountされる前提）:
    python3 resolve_hazard_sources.py --region tokyo \
        --layer-type storm_surge --layer-type flood --layer-type pseudo_inland_flood
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


def _resolve_validated_path(defn, state) -> "Path | None":
    """dataset定義とstateから、実際にdiskへ存在するvalidated artifactを1つ返す。

    優先順位: state.current_validated_path（stateが自己修復で無効化されて
    いなければ最新の実体を指す）→ defn.validated_storage_path（registry定義
    の既定path、state未確定時のfallback）。どちらも存在しない/diskに無い
    場合は None（resolve_shelter_sources.pyと同一方針）。
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
    parser.add_argument(
        "--layer-type", action="append", required=True, dest="layer_types",
        help="対象hazard layer_type（複数指定可）。指定しないtypeのactive mappingは無視する。",
    )
    args = parser.parse_args()
    target_layer_types = set(args.layer_types)

    ams = get_active_mapping_service()
    ds_svc = get_definition_service()
    ss_svc = get_state_service()

    resolved: list[tuple[str, str, Path]] = []
    failures: list[str] = []

    for mapping in ams.list_all():
        if mapping["layer_type"] not in target_layer_types:
            continue
        if mapping["region"] != args.region:
            continue

        layer_type = mapping["layer_type"]
        dataset_id = mapping["dataset_id"]
        defn = ds_svc.get(dataset_id)
        if defn is None:
            failures.append(
                f"active mapping先のdataset定義がregistryに見つかりません: "
                f"layer_type={layer_type} region={args.region} dataset_id={dataset_id}"
            )
            continue

        state = ss_svc.init_from_definition(defn)
        candidate = _resolve_validated_path(defn, state)
        if candidate is None:
            # Dual Storage Remediation Phase C1: 「activeなのにsourceが
            # 見つからない」を黙って進めない（今回のremediation対象の
            # 根本原因そのもの）。fail-closedで即座に失敗させる。
            failures.append(
                f"{dataset_id} ({layer_type}:{args.region}) は active mapping "
                f"だが validated artifactが解決できません "
                f"（state.current_validated_path={state.current_validated_path!r}、"
                f"defn.validated_storage_path={defn.validated_storage_path!r}）"
            )
            continue

        resolved.append((layer_type, dataset_id, candidate))

    if failures:
        for msg in failures:
            print(f"[resolve_hazard_sources] FAIL: {msg}", file=sys.stderr)
        print(
            f"[resolve_hazard_sources] region={args.region} layer_types={sorted(target_layer_types)}: "
            f"{len(failures)}件のactive datasetが未解決のため中断（部分出力なし）",
            file=sys.stderr,
        )
        return 1

    # 全件解決できた場合のみ出力する（呼び出し元へ部分結果を渡さない）。
    for layer_type, dataset_id, candidate in resolved:
        print(f"{layer_type}\t{dataset_id}\t{candidate}")

    print(
        f"[resolve_hazard_sources] region={args.region} layer_types={sorted(target_layer_types)}: "
        f"{len(resolved)}件のactive hazard datasetを解決",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
