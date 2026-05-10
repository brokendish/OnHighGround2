"""
潮汐情報サービス。
tide736.net の潮汐APIを参考情報として取得する。

外部サービスの停止・仕様変更・アクセス制限時は available=false を返し、
アプリ本体や防災判断には影響させない。

以下の自前調和推算コードは再検証用に残しているが、ユーザー向け表示には使わない。
調和定数（振幅・位相遅れ）から外部APIなしで潮位を計算する。

正式公式:
  h(t) = Z0 + Σ fᵢ · Aᵢ · cos(ωᵢ · t + V0ᵢ + uᵢ − Gᵢ)

各記号:
  t    = J2000 (2000-01-01 12:00 UTC) からの経過時間 [時間]
  ωᵢ   = 分潮角速度 [度/時間]
  V0ᵢ  = J2000 時点での平衡引数 [度]  (天文引数)
  uᵢ   = 節角補正 [度]  (月軌道昇交点 N' の 18.6 年周期変動による位相補正)
  fᵢ   = 振幅補正係数  (同じく N' による振幅変動)
  Gᵢ   = 各地点のグリニッジ位相遅れ [度]  (調和定数表の G 値)

調和推算値のため実潮位と差が発生する場合がある。
データ出典: 海上保安庁 潮汐推算 (参考値)
"""
import json
import math
import logging
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# J2000 基準エポック (2000-01-01 12:00:00 UTC)
# V0 はすべてこのエポックで評価した天文引数
_J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# ── 天文定数 (J2000 時点) ─────────────────────────────────────────────────────
# h₀ = 280.4665° (太陽平均黄経)
# s₀ = 218.3167° (月平均黄経)
# p₀ =  83.3532° (月近地点平均黄経)
# T₀ = 180°      (平均太陽時角 at 正午)
# 各分潮の V0 = これらの線形結合 (Schureman 1958 / IHO SP-80 準拠)
# ─────────────────────────────────────────────────────────────────────────────

_CONSTITUENTS: dict = {
    # 主要半日周潮
    "M2":  {"speed": 28.9841042, "v0": 124.3},   # 2T − 2s + 2h
    "S2":  {"speed": 30.0000000, "v0":   0.0},   # 2T
    "N2":  {"speed": 28.4397295, "v0": 349.3},   # 2T − 3s + 2h + p
    "K2":  {"speed": 30.0821373, "v0": 201.0},   # 2T + 2h  (= 2h₀ mod 360)
    # 主要日周潮
    "K1":  {"speed": 15.0410686, "v0": 190.5},   # T + h + 90°
    "O1":  {"speed": 13.9430356, "v0": 293.8},   # T − 2s + h − 90°
    "P1":  {"speed": 14.9589314, "v0": 349.5},   # T − h + 90°
    "Q1":  {"speed": 13.3986609, "v0": 159.0},   # T − 3s + h + p − 90°
    # 浅海分潮
    "M4":  {"speed": 57.9682084, "v0": 248.6},   # 2 × M2
    "MS4": {"speed": 58.9841042, "v0": 124.3},   # M2 + S2
    "MN4": {"speed": 57.4238337, "v0": 113.6},   # M2 + N2
    # 長周期潮
    "SA":  {"speed":  0.0410686, "v0": 280.5},   # h
    "SSA": {"speed":  0.0821373, "v0": 201.0},   # 2h
}

_STATIONS: list = []
_CACHE: dict = {}   # { station_id: { "events": [...], "expires_at": datetime } }
_TIDE736_CACHE: dict = {}  # { (station_id, YYYY-MM-DD): { "data": dict, "expires_at": datetime } }
_CACHE_TTL = timedelta(minutes=60)
_TIDE736_CACHE_TTL = timedelta(hours=3)
_TIDE736_URL = "https://api.tide736.net/get_tide.php"
_TIDE736_TIMEOUT_SECONDS = 4

_EXTREMA_STEP_MIN      = 10    # サンプリング間隔 [分]（浅海分潮の短周期変動を均す）
_EXTREMA_MIN_GAP_HOURS = 2.5   # 隣接極値の最小間隔 [時間]（M4 誘発偽ピーク抑制）
_EXTREMA_HORIZON_HOURS = 72    # 推算範囲 [時間]（現在 ±36h をカバー）


def _load_stations() -> None:
    global _STATIONS
    path = Path(__file__).resolve().parent.parent / "data" / "tide_stations.json"
    try:
        with path.open(encoding="utf-8") as f:
            _STATIONS = json.load(f)
        logger.info("tide: loaded %d stations from %s", len(_STATIONS), path)
    except Exception as e:
        logger.error("tide: failed to load stations: %s", e)
        _STATIONS = []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_station(lat: float, lon: float) -> Optional[dict]:
    if not _STATIONS:
        return None
    return min(_STATIONS, key=lambda s: _haversine_km(lat, lon, s["lat"], s["lon"]))


def _node_angle_deg(t_hours: float) -> float:
    """J2000 からの経過時間 [h] から月軌道昇交点黄経 N' [度] を返す。"""
    # N'₀ = 125.04453°, 変化率 = −0.0529539°/h (18.6 年周期)
    return (125.04453 - 0.0529539 * t_hours) % 360


def _nodal_params(t_hours: float) -> dict:
    """
    J2000 からの経過時間 [h] に対する各分潮の節角補正を返す。

    f  : 振幅補正係数 (無次元)
    u  : 位相補正 [度]  h(t) 式中の (V0 + u) に加算する

    出典: Schureman (1958) Tables 2 & 4, IHO SP-80 (2006) Annex B
    """
    N_deg = _node_angle_deg(t_hours)
    N = math.radians(N_deg)
    cosN  = math.cos(N);  sinN  = math.sin(N)
    cos2N = math.cos(2*N); sin2N = math.sin(2*N)

    # ── M2 / N2 系 ─────────────────────────────────────────────────────────
    # sqrt 形式で厳密に計算  (Schureman eq. 73 / 75)
    a_M2 = 1 - 0.03731 * cosN + 0.00052 * cos2N
    b_M2 =     0.03731 * sinN - 0.00052 * sin2N
    f_M2 = math.sqrt(a_M2**2 + b_M2**2)
    u_M2 = math.degrees(math.atan2(-b_M2, a_M2))    # [度]

    # ── K1 系 ───────────────────────────────────────────────────────────────
    # (Schureman Table 2, 定数 142)
    f_K1 = 1.006 + 0.115 * cosN - 0.009 * cos2N
    u_K1 = -8.86 * sinN + 0.68 * sin2N              # [度]

    # ── O1 / Q1 系 ──────────────────────────────────────────────────────────
    # (Schureman Table 2, 定数 75)
    f_O1 = 1.009 + 0.187 * cosN - 0.015 * cos2N
    u_O1 = 10.80 * sinN - 1.34 * sin2N              # [度]

    # ── K2 系 ───────────────────────────────────────────────────────────────
    # (Schureman Table 2, 定数 235)
    f_K2 = 1.024 + 0.286 * cosN - 0.008 * cos2N
    u_K2 = -17.74 * sinN + 0.68 * sin2N             # [度]

    # ── 浅海分潮 ────────────────────────────────────────────────────────────
    f_M4  = f_M2 ** 2;  u_M4  = 2 * u_M2            # M4  = M2²
    f_MN4 = f_M4;       u_MN4 = u_M4                # MN4 = M2 × N2 ≒ M4
    f_MS4 = f_M2;       u_MS4 = u_M2                # MS4 = M2 × S2

    return {
        "M2":  {"f": f_M2,  "u": u_M2},
        "S2":  {"f": 1.0,   "u": 0.0},   # 節角補正なし
        "N2":  {"f": f_M2,  "u": u_M2},  # M2 と同節角グループ
        "K2":  {"f": f_K2,  "u": u_K2},
        "K1":  {"f": f_K1,  "u": u_K1},
        "O1":  {"f": f_O1,  "u": u_O1},
        "P1":  {"f": 1.0,   "u": 0.0},   # 節角補正なし
        "Q1":  {"f": f_O1,  "u": u_O1},  # O1 と同節角グループ
        "M4":  {"f": f_M4,  "u": u_M4},
        "MS4": {"f": f_MS4, "u": u_MS4},
        "MN4": {"f": f_MN4, "u": u_MN4},
        "SA":  {"f": 1.0,   "u": 0.0},   # 節角補正なし
        "SSA": {"f": 1.0,   "u": 0.0},
    }


def _calc_tide_height(t: datetime, constituents: list, z0: float, nodal: dict) -> float:
    """
    時刻 t における潮位 [m] を計算する。

    公式: h = Z0 + Σ f·A·cos(ω·t + V0 + u − G)
    nodal は _nodal_params() の結果（計算コスト削減のため呼び出し元で一括取得）。
    """
    t_utc = t.astimezone(timezone.utc)
    t_hours = (t_utc - _J2000).total_seconds() / 3600.0
    h = z0
    for c in constituents:
        name = c["name"]
        info = _CONSTITUENTS.get(name)
        if info is None:
            continue
        nd = nodal.get(name, {"f": 1.0, "u": 0.0})
        phi = (info["speed"] * t_hours + info["v0"] + nd["u"] - c["phase_G"]) % 360
        h += nd["f"] * c["amplitude"] * math.cos(math.radians(phi))
    return h


def _find_extrema(station: dict, t_start: datetime, hours: float = _EXTREMA_HORIZON_HOURS) -> list:
    """
    t_start から hours 時間先までの満潮・干潮候補リストを返す。

    節角補正 (f, u) は推算窓中央で一括計算する。
    18.6 年周期の変化率は約 0.053°/h であり、72h 窓全体での変動は 3.8° 未満
    → 中央値での代表計算で十分な精度が得られる。

    ノイズ対策:
    - _EXTREMA_STEP_MIN 分刻みサンプリング（浅海分潮の細かい変動を均す）
    - 隣接極値フィルタ: _EXTREMA_MIN_GAP_HOURS 未満の連続ピークを整理
    """
    constituents = station["constituents"]
    z0 = station.get("z0", 0.0)
    step = timedelta(minutes=_EXTREMA_STEP_MIN)
    min_gap = timedelta(hours=_EXTREMA_MIN_GAP_HOURS)

    # 窓中央の節角補正を一括計算
    t_mid = t_start + timedelta(hours=hours / 2)
    t_mid_utc = t_mid.astimezone(timezone.utc)
    t_mid_hours = (t_mid_utc - _J2000).total_seconds() / 3600.0
    nodal = _nodal_params(t_mid_hours)

    # サンプリング
    samples = []
    t = t_start
    t_end = t_start + timedelta(hours=hours)
    while t <= t_end:
        samples.append((t, _calc_tide_height(t, constituents, z0, nodal)))
        t += step

    # 3点比較による局所極値検出
    raw = []
    for i in range(1, len(samples) - 1):
        t_c, h_c = samples[i]
        h_p = samples[i - 1][1]
        h_n = samples[i + 1][1]
        if h_p < h_c and h_c >= h_n:
            raw.append({"type": "high", "time": t_c, "height": round(h_c, 2)})
        elif h_p > h_c and h_c <= h_n:
            raw.append({"type": "low",  "time": t_c, "height": round(h_c, 2)})

    # 隣接ピーク抑制
    filtered = []
    for ev in raw:
        if not filtered:
            filtered.append(ev)
            continue
        prev = filtered[-1]
        if ev["time"] - prev["time"] < min_gap:
            if ev["type"] == prev["type"]:
                # 同タイプ: より極端な方を残す
                if (ev["type"] == "high" and ev["height"] > prev["height"]) or \
                   (ev["type"] == "low"  and ev["height"] < prev["height"]):
                    filtered[-1] = ev
            # 異タイプ近接: 先着優先、後者を破棄
        else:
            filtered.append(ev)

    return filtered


def _build_tide_events(station: dict, t_from: datetime) -> list:
    """t_from 以降 _EXTREMA_HORIZON_HOURS 時間の潮汐イベントリストを返す。"""
    return _find_extrema(station, t_from, hours=float(_EXTREMA_HORIZON_HOURS))


def _format_jst(dt: datetime) -> str:
    return dt.astimezone(JST).isoformat()


def _unavailable() -> dict:
    return {"available": False, "source": "tide736", "is_reference": True}


def _request_tide736(params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{_TIDE736_URL}?{query}",
        headers={"User-Agent": "OnHighGround2/1.0"},
    )
    logger.info("tide736: request url=%s", req.full_url)
    with urllib.request.urlopen(req, timeout=_TIDE736_TIMEOUT_SECONDS) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read().decode(charset)
        logger.info("tide736: response url=%s bytes=%d", resp.geturl(), len(raw))
        return json.loads(raw)


def _fetch_tide736_day(station: dict, day: date) -> Optional[dict]:
    tide736 = station.get("tide736") or {}
    pc = tide736.get("pc")
    hc = tide736.get("hc")
    if not pc or not hc:
        return None

    now = datetime.now(JST)
    date_key = day.isoformat()
    cache_key = (station["id"], date_key)
    cached = _TIDE736_CACHE.get(cache_key)
    if cached and cached["expires_at"] > now:
        return cached["data"]

    try:
        data = _request_tide736({
            "pc": pc,
            "hc": hc,
            "yr": day.year,
            "mn": day.month,
            "dy": day.day,
            "rg": "day",
        })
    except Exception as e:
        logger.info("tide736: request failed station=%s date=%s: %s", station.get("id"), date_key, e)
        return None

    if data.get("status") != 1:
        logger.info("tide736: non-success station=%s date=%s message=%s", station.get("id"), date_key, data.get("message"))
        return None

    port = (data.get("tide") or {}).get("port") or {}
    chart = ((data.get("tide") or {}).get("chart") or {})
    day_chart = chart.get(date_key) or {}
    logger.info(
        "tide736: parsed station=%s date=%s pc=%s hc=%s port=%s/%s edd=%s flood=%s chart_keys=%s",
        station.get("id"),
        date_key,
        pc,
        hc,
        port.get("prefecture_code"),
        port.get("harbor_code"),
        [item.get("time") for item in (day_chart.get("edd") or [])],
        [item.get("time") for item in (day_chart.get("flood") or [])],
        list(chart.keys()),
    )

    _TIDE736_CACHE[cache_key] = {"data": data, "expires_at": now + _TIDE736_CACHE_TTL}
    return data


def _event_from_tide736_item(item: dict, event_type: str) -> Optional[dict]:
    unix_ms = item.get("unix")
    if unix_ms is None:
        return None
    try:
        when = datetime.fromtimestamp(float(unix_ms) / 1000.0, JST)
    except (TypeError, ValueError, OSError):
        return None
    event = {"type": event_type, "time": when}
    if item.get("cm") is not None:
        try:
            event["height_cm"] = round(float(item["cm"]), 1)
        except (TypeError, ValueError):
            pass
    return event


def _build_tide736_events(station: dict, now: datetime) -> list:
    events = []
    for offset in (0, 1):
        day = (now + timedelta(days=offset)).date()
        data = _fetch_tide736_day(station, day)
        if not data:
            continue
        chart = ((data.get("tide") or {}).get("chart") or {})
        day_chart = chart.get(day.isoformat()) or {}
        for item in day_chart.get("flood") or []:
            event = _event_from_tide736_item(item, "high")
            if event:
                events.append(event)
        for item in day_chart.get("edd") or []:
            event = _event_from_tide736_item(item, "low")
            if event:
                events.append(event)
    return sorted(events, key=lambda e: e["time"])


def _format_tide736_event(event: Optional[dict], now: datetime, include_remaining: bool = False) -> Optional[dict]:
    if not event:
        return None
    out = {"time": _format_jst(event["time"])}
    if "height_cm" in event:
        out["height_cm"] = event["height_cm"]
    if include_remaining:
        out["remaining_minutes"] = max(0, int((event["time"] - now).total_seconds() / 60))
    return out


def _select_next_tide736_event(events: list, now: datetime, event_type: Optional[str] = None) -> Optional[dict]:
    return next(
        (
            event
            for event in sorted(events, key=lambda e: e["time"])
            if event["time"] > now and (event_type is None or event["type"] == event_type)
        ),
        None,
    )


def get_tide_info(lat: float, lon: float) -> Optional[dict]:
    """
    現在地から最寄り地点の参考潮汐情報を返す。
    tide736 取得失敗・コード未設定・次イベントなしの場合は available=false。
    """
    if not _STATIONS:
        _load_stations()

    station = _nearest_station(lat, lon)
    if not station:
        return None

    now = datetime.now(JST)
    dist_km = round(_haversine_km(lat, lon, station["lat"], station["lon"]), 1)

    events = _build_tide736_events(station, now)
    next_high = _select_next_tide736_event(events, now, "high")
    next_low = _select_next_tide736_event(events, now, "low")
    if not next_high and not next_low:
        return _unavailable()

    return {
        "available": True,
        "station": {
            "id":          station["id"],
            "name":        station["name"],
            "distance_km": dist_km,
        },
        "next_high_tide": _format_tide736_event(next_high, now, include_remaining=True),
        "next_low_tide": _format_tide736_event(next_low, now),
        "source": "tide736",
        "is_reference": True,
    }
