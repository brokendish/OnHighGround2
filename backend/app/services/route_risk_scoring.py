"""ルート危険度スコアリング

ルート座標列に対するハザード通過率 (exposure_ratio) から
安全度スコアとリスクサマリーを算出する。

スコアリングポリシー:
  - 強い危険要因 (flood/tsunami/storm_surge/landslide) は単独で大幅減点
  - 中程度 (inland_flood/pseudo_inland_flood) は中程度減点
  - 補助要因 (lowland_poor_drainage) は単独では小さなペナルティのみ。
    他の浸水系ハザードと重なった場合にオーバーラップボーナスを加算する。
  - キキクル補正 (Phase 3-B): リアルタイム気象危険度を控えめなペナルティとして反映する。
    キキクル単独では danger にしない。固定ハザードと重なった場合のみ強めの補正を適用する。
"""
from typing import Dict, List, Optional

# ハザード別ペナルティ定義
# base: exposure_ratio=1.0 のときのペナルティ上限
# min:  1点でも通過した場合の最小ペナルティ
HAZARD_PENALTIES: Dict[str, dict] = {
    "tsunami":               {"base": 45, "min": 20, "role": "primary",       "label": "津波"},
    "flood":                 {"base": 40, "min": 18, "role": "primary",       "label": "洪水"},
    "storm_surge":           {"base": 35, "min": 16, "role": "primary",       "label": "高潮"},
    "landslide":             {"base": 30, "min": 14, "role": "primary",       "label": "土砂災害"},
    "inland_flood":          {"base": 20, "min":  8, "role": "primary",       "label": "内水氾濫"},
    "pseudo_inland_flood":   {"base": 15, "min":  6, "role": "primary",       "label": "推定内水"},
    "lowland_poor_drainage": {"base":  8, "min":  3, "role": "supplementary", "label": "低地・排水困難エリア"},
}

# 低地エリアと他の浸水系ハザードが重なる場合のオーバーラップボーナス
LOWLAND_OVERLAP_BONUS: Dict[str, int] = {
    "flood":               6,
    "inland_flood":        5,
    "storm_surge":         4,
    "pseudo_inland_flood": 4,
}


# ── キキクル補正 (Phase 3-B) ──────────────────────────────────────────────────

# キキクル kind と対応する固定ハザード
_KKK_HAZARD_MAP: Dict[str, set] = {
    "inund": {"inland_flood", "pseudo_inland_flood"},
    "flood": {"flood", "lowland_poor_drainage"},
    "land":  {"landslide"},
}

# キキクルペナルティ（単体 / 固定ハザード重複時）
_KKK_PENALTY: Dict[str, Dict[str, Dict[str, float]]] = {
    "standalone": {
        "inund": {"caution": 3.0, "danger": 6.0},
        "flood": {"caution": 4.0, "danger": 8.0},
        "land":  {"caution": 4.0, "danger": 8.0},
    },
    "overlap": {
        "inund": {"caution": 6.0,  "danger": 12.0},
        "flood": {"caution": 8.0,  "danger": 16.0},
        "land":  {"caution": 8.0,  "danger": 16.0},
    },
}
_KKK_CAP_STANDALONE = 20.0
_KKK_CAP_OVERLAP    = 30.0
_KKK_KIND_LABEL     = {"inund": "浸水", "flood": "洪水", "land": "土砂"}


def calc_kikikuru_adjustment(
    kikikuru: Optional[Dict],
    exposure_by_hazard: Dict[str, float],
) -> dict:
    """キキクルリアルタイム補正を計算する。

    Args:
        kikikuru: {status, inund, flood, land} (フロントエンドの _kkkRouteRisk から)
        exposure_by_hazard: {hazard_type: exposure_ratio} (固定ハザード通過率)

    Returns:
        {enabled, status, penalty, max_level, matched_hazards, summary}
    """
    if not isinstance(kikikuru, dict):
        return {
            "enabled": False, "status": "off", "penalty": 0.0,
            "max_level": None, "matched_hazards": [], "summary": [],
        }

    status = kikikuru.get("status")
    if not status or status in ("off", "loading"):
        return {
            "enabled": False, "status": status or "off", "penalty": 0.0,
            "max_level": None, "matched_hazards": [], "summary": [],
        }

    if status == "unavailable":
        return {
            "enabled": True, "status": "unavailable", "penalty": 0.0,
            "max_level": None, "matched_hazards": [], "summary": ["キキクル取得不可（補正なし）"],
        }
    if status != "ok":
        return {
            "enabled": True, "status": "unknown", "penalty": 0.0,
            "max_level": None, "matched_hazards": [], "summary": ["キキクル判定不可（補正なし）"],
        }

    # status == "ok" → ペナルティ計算
    active_hazards = {h for h, r in exposure_by_hazard.items() if r > 0.0}
    total_penalty  = 0.0
    matched:  List[str] = []
    summary:  List[str] = []
    has_overlap = False

    for kind in ("inund", "flood", "land"):
        level = kikikuru.get(kind)
        if not level or level not in ("caution", "danger"):
            if level == "unavailable":
                summary.append(f"{_KKK_KIND_LABEL[kind]}キキクル取得不可")
            elif level == "unknown":
                summary.append(f"{_KKK_KIND_LABEL[kind]}キキクル判定不可")
            continue

        overlap = _KKK_HAZARD_MAP[kind] & active_hazards
        lv_label = "危険" if level == "danger" else "注意"
        if overlap:
            has_overlap = True
            p = _KKK_PENALTY["overlap"][kind].get(level, 0.0)
            matched.extend(overlap)
            summary.append(f"{_KKK_KIND_LABEL[kind]}キキクル{lv_label}（固定ハザード重複）")
        else:
            p = _KKK_PENALTY["standalone"][kind].get(level, 0.0)
            summary.append(f"{_KKK_KIND_LABEL[kind]}キキクル{lv_label}")
        total_penalty += p

    cap = _KKK_CAP_OVERLAP if has_overlap else _KKK_CAP_STANDALONE
    total_penalty = min(total_penalty, cap)

    return {
        "enabled":         True,
        "status":          "normal",
        "penalty":         round(total_penalty, 1),
        # 固定ハザード重複なし → max caution、重複あり → danger まで許可
        "max_level":       "danger" if has_overlap else "caution",
        "matched_hazards": list(set(matched)),
        "summary":         summary,
    }


def _risk_level(score: float) -> str:
    if score >= 75:
        return "safe"
    if score >= 50:
        return "caution"
    return "danger"


def calc_route_risk_score(exposure_by_hazard: Dict[str, float]) -> dict:
    """
    ハザード通過率からルート安全度スコアを計算する。

    Args:
        exposure_by_hazard: {hazard_type: exposure_ratio} (0.0–1.0)
            例: {"flood": 0.3, "lowland_poor_drainage": 0.5}

    Returns:
        {
            "safety_score": float,          # 0–100
            "risk_level": str,              # "safe" | "caution" | "danger"
            "risk_summary": {
                "total_penalty": float,
                "hazards": [
                    {
                        "type": str,
                        "label": str,
                        "exposure_ratio": float,
                        "penalty": float,
                        "role": str,        # "primary" | "supplementary"
                    }
                ],
                "notes": [str],
            }
        }
    """
    has_lowland = exposure_by_hazard.get("lowland_poor_drainage", 0.0) > 0.0

    hazard_entries: List[dict] = []
    total_penalty = 0.0

    for hazard_type, exposure_ratio in exposure_by_hazard.items():
        if exposure_ratio <= 0.0:
            continue
        config = HAZARD_PENALTIES.get(hazard_type)
        if config is None:
            continue

        penalty = max(config["base"] * exposure_ratio, float(config["min"]))

        # 低地エリアと重複している場合にオーバーラップボーナスを加算
        if hazard_type != "lowland_poor_drainage" and has_lowland:
            penalty += LOWLAND_OVERLAP_BONUS.get(hazard_type, 0)

        total_penalty += penalty
        hazard_entries.append({
            "type": hazard_type,
            "label": config["label"],
            "exposure_ratio": round(exposure_ratio, 3),
            "penalty": round(penalty, 1),
            "role": config["role"],
        })

    safety_score = max(0.0, min(100.0, 100.0 - total_penalty))

    notes: List[str] = []
    for e in hazard_entries:
        pct = round(e["exposure_ratio"] * 100)
        if e["role"] == "supplementary":
            notes.append(f"{e['label']}を一部通過します（{pct}%）")
        else:
            notes.append(f"{e['label']}エリアを通過します（{pct}%）")

    return {
        "safety_score": round(safety_score, 1),
        "risk_level": _risk_level(safety_score),
        "risk_summary": {
            "total_penalty": round(total_penalty, 1),
            "hazards": hazard_entries,
            "notes": notes,
        },
    }
