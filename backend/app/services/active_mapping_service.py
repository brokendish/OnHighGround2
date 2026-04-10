"""
active_mapping_service.py — アクティブデータセットマッピング管理

あるレイヤータイプ+地域の組み合わせに対して、現在有効なデータセットIDを管理する。
状態は data_lake/admin/active_mappings.json に永続化する。

キー形式: "{layer_type}:{region}"  例: "shelter:kanagawa", "tsunami:tokyo"
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MAPPINGS_PATH = _PROJECT_ROOT / "data_lake" / "admin" / "active_mappings.json"


class ActiveMappingService:
    """
    レイヤータイプ × 地域 → 有効データセットID のマッピングを管理する。

    ファイルは起動時にロードし、更新時にアトミックに書き込む。
    スレッドセーフ（読み書きに lock を使用）。
    """

    def __init__(self, mappings_path: Optional[Path] = None) -> None:
        self._path = (mappings_path or _MAPPINGS_PATH).resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._data: Dict[str, str] = self._load()

    # ── 内部 ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _key(layer_type: str, region: str) -> str:
        return f"{layer_type}:{region}"

    def _load(self) -> Dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning("active_mappings.json has invalid format, resetting.")
                return {}
            return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
        except Exception as exc:
            logger.error("Failed to load active_mappings.json: %s", exc)
            return {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        tmp.replace(self._path)

    # ── 公開 API ──────────────────────────────────────────────────────────────

    def get_active(self, layer_type: str, region: str) -> Optional[str]:
        """指定レイヤータイプ+地域の有効データセットIDを返す。未設定の場合は None。"""
        with self._lock:
            return self._data.get(self._key(layer_type, region))

    def set_active(self, layer_type: str, region: str, dataset_id: str) -> None:
        """有効データセットを設定して永続化する。"""
        with self._lock:
            self._data[self._key(layer_type, region)] = dataset_id
            self._save()
        logger.info("Active mapping set: %s:%s -> %s", layer_type, region, dataset_id)

    def unset_active(self, layer_type: str, region: str) -> bool:
        """有効データセット設定を解除する。解除できた場合 True を返す。"""
        key = self._key(layer_type, region)
        with self._lock:
            if key not in self._data:
                return False
            del self._data[key]
            self._save()
        logger.info("Active mapping unset: %s:%s", layer_type, region)
        return True

    def is_active(self, layer_type: Optional[str], region: str, dataset_id: str) -> bool:
        """指定データセットが layer_type+region の有効データセットかどうかを返す。"""
        if not layer_type:
            return False
        with self._lock:
            return self._data.get(self._key(layer_type, region)) == dataset_id

    def list_all(self) -> List[Dict[str, str]]:
        """全マッピングをリスト形式で返す。"""
        with self._lock:
            return [
                {"layer_type": k.split(":")[0], "region": k.split(":")[1], "dataset_id": v}
                for k in self._data
                for v in [self._data[k]]
                if ":" in k
            ]

    def reload(self) -> None:
        """ファイルを再読み込みする（テスト・デバッグ用）。"""
        with self._lock:
            self._data = self._load()


# シングルトン
_instance: Optional[ActiveMappingService] = None


def get_active_mapping_service() -> ActiveMappingService:
    global _instance
    if _instance is None:
        _instance = ActiveMappingService()
    return _instance
