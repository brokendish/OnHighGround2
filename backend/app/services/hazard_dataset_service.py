import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.active_mapping_service import get_active_mapping_service
from app.services.dataset_definition_service import get_definition_service
from app.services.dataset_state_service import get_state_service

logger = logging.getLogger(__name__)


class HazardDatasetService:
    """Provide active hazard datasets resolved from the admin dataset foundation."""

    HAZARD_LAYER_TYPES = {
        "tsunami",
        "flood",
        "storm_surge",
        "inland_flood",
        "landslide",
        "pseudo_inland_flood",
        # tileset_id_alignment修復: registry（active_mappings.json）には
        # lowland_poor_drainage:tokyo / :kanagawa が登録済みだったが、この
        # 集合に含まれていなかったため /api/hazards/lowland_poor_drainage/*
        # と /meta が常に KeyError(Unsupported hazard_type) になっていた。
        "lowland_poor_drainage",
    }

    def _load_json(self, path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid GeoJSON in {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"GeoJSON root must be an object: {path}")
        return data

    def _resolve_active_dataset(self, hazard_type: str, region_code: str):
        if hazard_type not in self.HAZARD_LAYER_TYPES:
            raise KeyError(f"Unsupported hazard_type: {hazard_type}")

        dataset_id = get_active_mapping_service().get_active(hazard_type, region_code)
        if not dataset_id:
            raise KeyError(f"Active dataset is not registered: {hazard_type}:{region_code}")

        defn = get_definition_service().get(dataset_id)
        if defn is None:
            raise KeyError(f"Dataset definition not found: {dataset_id}")

        state = get_state_service().init_from_definition(defn)
        active_path = (
            state.current_runtime_path
            or state.current_validated_path
            or state.current_normalized_path
        )
        if not active_path:
            raise FileNotFoundError(f"Active dataset has no resolved artifact: {dataset_id}")

        return dataset_id, defn, state, Path(active_path)

    def _resolve_current_hazard_file(self, version_root: Path, hazard_type: str, region_code: str) -> Optional[Path]:
        """`version_root`（current/versioned tree、呼び出し元がlease保護下で
        解決済み）配下から対象hazard type/regionのGeoJSONを1件選ぶ。

        Dual Storage Remediation Phase C1で確立されたlayoutは
        `backend/hazard/{type}/{region}/{file}`（region配下directory）だが、
        tsunamiだけは既存のconsumer契約（`_runtime_stream_or_none`／
        app_public.pyのtsunami loader）に合わせて`backend/hazard/tsunami/
        tsunami_{region}.geojson`という region直下フラット命名を使うため、
        region配下directoryが無い場合はflat側と同じprefix glob
        （`{region}_*.geojson` / `{region}-*.geojson`）にfallbackする。
        いずれの場合もbasenameのhardcodeはしない。
        """
        hazard_type_dir = version_root / "backend" / "hazard" / hazard_type
        region_subdir = hazard_type_dir / region_code
        if region_subdir.is_dir():
            candidates = sorted(region_subdir.glob("*.geojson"))
        elif hazard_type_dir.is_dir():
            candidates = sorted(
                list(hazard_type_dir.glob(f"{region_code}_*.geojson"))
                + list(hazard_type_dir.glob(f"{region_code}-*.geojson"))
            )
        else:
            candidates = []
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_size)

    def _try_load_geojson_from_current(self, hazard_type: str, region_code: str) -> Optional[Dict[str, Any]]:
        """current/versioned atomic-publish treeから対象datasetの解決を試みる。

        戻り値:
          - dict: currentから正常に読み込めた（呼び出し元はflatを見ない）
          - None: current側に対象dataset自体が存在しない、または atomic
            publish機構自体が未導入（真の未配備）——呼び出し元はflatへ
            fallbackしてよい。

        例外はそのまま呼び出し元へ伝播させる（catchしない）:
          - lease/current自体の破損（RuntimeAtomicError系）: is_available()
            （coordination.lock存在）が真の場合、currentが読めないのは
            「導入済みだが壊れている」ことを意味し、flatへ静かに逃げると
            versioned corruptionを隠蔽してしまう（ShelterRegistryの
            `_try_load_from_atomic_publish`と同じ方針）。
          - JSONDecodeError/ValueError: current側fileの内容が壊れている
            場合も同様にflatへ逃げず、既存の500 handler契約
            （hazards.pyの`except (ValueError, json.JSONDecodeError,
            OSError)`）にそのまま委ねる。
        """
        from app.services import runtime_version_access as rva
        from app.services.runtime_lease import leased_version_root

        if not rva.is_available():
            return None

        current_link = rva.DATA_RUNTIME_ROOT / "current"
        if not current_link.exists() and not current_link.is_symlink():
            # runtime-init直後、まだ一度もpublishされていない正常系。
            return None

        coordinator = rva.get_coordinator()
        with leased_version_root(coordinator, rva.DATA_RUNTIME_ROOT, f"http-hazard-{hazard_type}") as version_root:
            chosen = self._resolve_current_hazard_file(version_root, hazard_type, region_code)
            if chosen is None:
                return None
            data = self._load_json(chosen)
            logger.debug("hazard dataset source=current hazard_type=%s region=%s", hazard_type, region_code)
            return data

    def get_active_hazard_geojson(self, hazard_type: str, region_code: str) -> Dict[str, Any]:
        if hazard_type not in self.HAZARD_LAYER_TYPES:
            raise KeyError(f"Unsupported hazard_type: {hazard_type}")

        current_geojson = self._try_load_geojson_from_current(hazard_type, region_code)
        if current_geojson is not None:
            return current_geojson

        logger.debug("hazard dataset source=flat_fallback hazard_type=%s region=%s", hazard_type, region_code)
        _, _, _, geojson_path = self._resolve_active_dataset(hazard_type, region_code)
        return self._load_json(geojson_path)

    def get_active_hazard_meta(self, hazard_type: str, region_code: str) -> Dict[str, Any]:
        dataset_id, defn, state, geojson_path = self._resolve_active_dataset(hazard_type, region_code)
        return {
            "dataset_id": dataset_id,
            "layer_type": defn.layer_type,
            "region": defn.region,
            "display_name": defn.display_name,
            "deploy_status": state.deploy_status,
            "artifact_path": str(geojson_path),
            "is_active": True,
        }

    def list_active_hazard_datasets(self) -> List[Dict[str, Any]]:
        active_datasets: List[Dict[str, Any]] = []
        ds = get_definition_service()
        ss = get_state_service()
        for mapping in get_active_mapping_service().list_all():
            if mapping["layer_type"] not in self.HAZARD_LAYER_TYPES:
                continue
            dataset_id = mapping["dataset_id"]
            defn = ds.get(dataset_id)
            if defn is None:
                continue
            state = ss.init_from_definition(defn)
            active_datasets.append(
                {
                    "registry_key": f"{mapping['layer_type']}:{mapping['region']}",
                    "dataset_id": dataset_id,
                    "dataset_type": "hazard",
                    "hazard_type": defn.layer_type,
                    "region_code": defn.region,
                    "region_name": defn.region,
                    "title": defn.display_name,
                    "status": state.deploy_status,
                    "is_active": True,
                    "path": state.current_runtime_path or state.current_validated_path or state.current_normalized_path,
                }
            )

        return active_datasets
