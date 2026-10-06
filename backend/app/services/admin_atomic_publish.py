"""
admin_atomic_publish.py — 管理画面「反映」を正式 atomic publish 経路へ接続する。

正式 publish 契約（scripts/publish/deploy_to_runtime_atomic.sh）:
    data_lake → data_runtime/.staging/<version-id> → runtime validation
    → activate_version.py → versions/<version-id> → current atomic switch

管理画面の反映（pipeline_service.run_deploy）は、対象 layer_type について data_runtime の flat
path へ直接コピーして成功扱いにしてはならない。本モジュールは wrapper の起動引数の組み立てと、
activation 後の事後検証（current が新 version を指し manifest が存在すること）を担う。

atomic publish 対象（ATOMIC_PUBLISH_LAYER_TYPES）は、wrapper が registry
（active_mappings + dataset_definitions + DatasetState）から当該 dataset の artifact を解決する
type に限る（resolve_hazard_sources.py: flood / storm_surge / pseudo_inland_flood）。
tsunami / inland_flood / landslide / lowland_poor_drainage は wrapper が registry ではなく固定
path から publish する（lowland は publish 処理自体が無い）ため、管理画面の dataset を wrapper
に通しても当該 artifact が publish される保証が無く、今回は対象外（後続課題）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional

from app.services.flood_routing_contract import is_routing_artifact_name

ATOMIC_PUBLISH_LAYER_TYPES = frozenset({"flood", "storm_surge", "pseudo_inland_flood"})

# wrapper の終了コード（deploy_to_runtime_atomic.sh 冒頭のコメントと一致）
EXIT_OK = 0
EXIT_DURABILITY_UNKNOWN = 3   # current は切替済みだが耐久性未確認（要 operator 判断）
EXIT_MIRROR_CONTRACT = 4      # current 切替済み・Martin 向け tile mirror の permission 契約違反

_OWNER_APPROVAL_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+()\- ]{2,199}$")


class AtomicPublishError(Exception):
    """管理画面反映の atomic publish が成立しなかった（反映成功として扱わない）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def data_runtime_root() -> Path:
    return Path(os.environ.get("OHG2_DATA_RUNTIME_ROOT", "/data_runtime"))


def current_version_id(root: Optional[Path] = None) -> Optional[str]:
    """current symlink が指す version ID。未 publish / symlink でない場合は None。"""
    link = (root or data_runtime_root()) / "current"
    if not link.is_symlink():
        return None
    return Path(os.readlink(link)).name


def legacy_flood_files_in_current(root: Optional[Path] = None) -> List[str]:
    """current version の backend/hazard/flood 配下にある routing artifact 以外の file（rel path）。
    1 件以上あれば flood routing 初回 migration が必要。"""
    root = root or data_runtime_root()
    version_id = current_version_id(root)
    if version_id is None:
        return []
    version = root / "versions" / version_id
    flood = version / "backend" / "hazard" / "flood"
    if not flood.is_dir():
        return []
    return sorted(
        str(p.relative_to(version)) for p in flood.rglob("*")
        if p.is_file() and not is_routing_artifact_name(p.name)
    )


# deploy_to_runtime.sh が region 単位（data_lake/{validated,normalized}/<region>/<type>）で publish する
# hazard layer_type。publish 対象 region はこれらの active mapping に現れる region に限る
# （tide:japan 等、region の意味が異なる全国 dataset の region を含めると deploy_to_runtime.sh が
#  存在しない data_lake 構成を探して失敗する）。
HAZARD_PUBLISH_LAYER_TYPES = frozenset({
    "flood", "storm_surge", "pseudo_inland_flood", "tsunami", "inland_flood", "landslide",
    "lowland_poor_drainage",
})


def publish_regions() -> List[str]:
    """atomic publish に含める region。staging は current を種にした region 単位の積み上げで、
    flood routing migration は全 region の legacy flood を同時に置き換える必要があるため、
    hazard layer_type の active mapping に登録された全 region を対象にする。"""
    from app.services.active_mapping_service import get_active_mapping_service

    regions = sorted({m["region"] for m in get_active_mapping_service().list_all()
                      if m["layer_type"] in HAZARD_PUBLISH_LAYER_TYPES})
    if not regions:
        raise AtomicPublishError("ATOMIC_PUBLISH_NO_REGION", "active mapping に region が登録されていません")
    return regions


def validate_owner_approval_ref(ref: Optional[str]) -> str:
    value = (ref or "").strip()
    if not _OWNER_APPROVAL_REF_RE.fullmatch(value):
        raise ValueError(
            "OWNER 承認参照は 3〜200 文字の英数字と . _ : @ / + ( ) - 空白で指定してください"
        )
    return value


def build_wrapper_command(wrapper: Path, regions: List[str], migration_ref: Optional[str]) -> List[str]:
    cmd = ["bash", str(wrapper)]
    for region in regions:
        cmd += ["--region", region]
    if migration_ref is not None:
        cmd += ["--allow-flood-routing-migration", migration_ref]
    return cmd


def verify_activation(before_version: Optional[str], migration_ref: Optional[str],
                      root: Optional[Path] = None) -> str:
    """wrapper 成功後、current が新 version を指し manifest があることを確認して version ID を返す。"""
    root = root or data_runtime_root()
    after = current_version_id(root)
    if after is None or after == before_version:
        raise AtomicPublishError(
            "ATOMIC_PUBLISH_NOT_ACTIVATED",
            f"current が新しい version に切り替わっていません（before={before_version} after={after}）",
        )
    manifest_path = root / "versions" / after / "_manifest.json"
    if not manifest_path.is_file():
        raise AtomicPublishError("ATOMIC_PUBLISH_NO_MANIFEST", f"manifest がありません: {manifest_path}")
    if migration_ref is not None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        refs = [m.get("owner_approval_ref") for m in manifest.get("migrations", [])
                if m.get("type") == "flood_routing_migration"]
        if migration_ref not in refs:
            raise AtomicPublishError(
                "ATOMIC_PUBLISH_MIGRATION_NOT_RECORDED",
                "manifest に flood routing migration の記録がありません",
            )
    return after


def dataset_artifact_in_version(version_id: str, layer_type: str, region: str, filename: Optional[str],
                                root: Optional[Path] = None) -> Path:
    """activate された version 内の当該 dataset artifact（backend/hazard/<type>/<region>/<file>）。
    filename=None（source が directory）の場合は region directory に *.geojson が 1 件以上あること。"""
    root = root or data_runtime_root()
    region_dir = root / "versions" / version_id / "backend" / "hazard" / layer_type / region
    if filename is None:
        if region_dir.is_dir() and any(region_dir.glob("*.geojson")):
            return region_dir
        raise AtomicPublishError(
            "ATOMIC_PUBLISH_ARTIFACT_MISSING",
            f"activate された version に反映対象が含まれていません: {region_dir}",
        )
    path = region_dir / filename
    if not path.is_file():
        raise AtomicPublishError(
            "ATOMIC_PUBLISH_ARTIFACT_MISSING",
            f"activate された version に反映対象が含まれていません: {path}",
        )
    return path


def runtime_artifact_name(layer_type: str, validated_name: str) -> str:
    """atomic publish 後に version 内へ置かれる artifact 名（flood は routing artifact）。"""
    if layer_type == "flood" and validated_name.endswith(".geojson") and not is_routing_artifact_name(validated_name):
        return validated_name[: -len(".geojson")] + ".routing.geojson"
    return validated_name


def find_artifact_in_current(layer_type: str, region: str, validated_name: str,
                             root: Optional[Path] = None) -> Optional[Path]:
    """current version に当該 dataset の artifact があれば versions/<id>/... の実 path を返す。"""
    root = root or data_runtime_root()
    version_id = current_version_id(root)
    if version_id is None:
        return None
    path = (root / "versions" / version_id / "backend" / "hazard" / layer_type / region
            / runtime_artifact_name(layer_type, validated_name))
    return path if path.is_file() else None

