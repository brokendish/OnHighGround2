"""app.properties 設定fileの読み込み・解決ロジック（単一情報源）。

CODEX P2B5-CX-003（第18ラウンド）対応: `backend/app_public.py`（consumer、
実際にhazard.tsunami.targets等を読んでruntimeへ反映するprocess）と
`backend/app/services/runtime_dataset_validate.py`（publisher側のstaging
検証、consumerが実際に要求するtargetを事前に知る必要がある）が、それぞれ
独立に類似の設定解決ロジックを実装していた。独立実装は、片方だけが
「設定file不在／読取不能／key不在／空」時に異なるfallback（特に緩い側の
fail-open）を選んでしまうdrift余地を生む。本moduleへ集約し、両者が
同一のeffective config解決規則を共有できるようにする。

Phase 2-C: `cors.allow_origins` の exact-origin allowlist parser/validator
（`parse_cors_origins`）もこのmoduleへ集約する。CORS設定のconsumerは
現状 `app_public.py` のみだが、単一情報源の方針（P2B5-CX-003と同一）を
先取りして踏襲し、将来2つ目のconsumerが現れても実装がdriftしないようにする。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional


class CorsConfigError(ValueError):
    """`cors.allow_origins` 等のCORS設定が不正な場合に送出する。

    呼び出し側（app_public.py）はこれをcatchして緩いfallbackへ倒さず、
    起動そのものをfail-closedで停止させること（他の起動時設定検証
    ——OPERATOR_AUTH_SECRET、tsunami target等——と同一方針）。
    """


# scheme(http/https) + host(ドメインラベル列 / IPv4 / [IPv6]) + optional port のみを
# 許可するexact-origin構文。path・query・fragment・userinfo・wildcardは
# 構造的にmatchしない（末尾にそれらの文字が付くと正規表現全体が不一致になる）。
_CORS_ORIGIN_RE = re.compile(
    r"^(?P<scheme>https?)://"
    r"(?P<host>"
    r"\[[0-9a-fA-F:]+\]"
    r"|\d{1,3}(?:\.\d{1,3}){3}"
    r"|[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
    r")"
    r"(?::(?P<port>[0-9]{1,5}))?$",
    re.IGNORECASE,
)


def _validate_cors_origin(raw_item: str) -> str:
    """1件のCORS origin文字列を検証し、正規化済み(scheme://host[:port])を返す。

    不正な場合は`CorsConfigError`を送出する（黙って読み飛ばさない）。
    """
    if raw_item == "" or raw_item != raw_item.strip():
        raise CorsConfigError(
            f"cors.allow_origins: 空要素または前後に空白を含む値は許可しない: {raw_item!r}"
        )
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in raw_item):
        raise CorsConfigError(
            f"cors.allow_origins: 制御文字を含む値は許可しない: {raw_item!r}"
        )
    if raw_item.lower() == "null":
        raise CorsConfigError("cors.allow_origins: 'null' origin は許可しない")
    if "*" in raw_item:
        raise CorsConfigError(
            f"cors.allow_origins: ワイルドカードを含む値は許可しない: {raw_item!r}"
        )
    if "@" in raw_item:
        raise CorsConfigError(
            f"cors.allow_origins: userinfo を含む値は許可しない: {raw_item!r}"
        )
    match = _CORS_ORIGIN_RE.match(raw_item)
    if not match:
        raise CorsConfigError(
            "cors.allow_origins: scheme(http/https)://host[:port] の exact origin "
            f"ではない（path/query/fragment付き、schemeなし、host不正等）: {raw_item!r}"
        )
    scheme = match.group("scheme").lower()
    host = match.group("host").lower()
    port = match.group("port")
    return f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"


def load_properties(config_path: Path) -> dict:
    """Java .properties 形式の設定ファイルを読み込む。fileが存在しない場合は
    空dictを返す（呼び出し側の `APP_CONFIG.get(key, default)` によるdefault
    解決に委ねる——これは意図的なfallbackであり、fail-openではない。
    file存在下でのOSError（読取不能）は呼び出し側へそのまま伝播させる）。"""
    properties: dict = {}
    if not config_path.exists():
        return properties

    with config_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()

    return properties


def load_raw_property_value(config_path: Path, key: str) -> Optional[str]:
    """指定keyの値を`load_properties()`のような`value.strip()`を適用せず、
    行末の改行文字（`\\n`・`\\r`）だけを除いた生の文字列で返す
    （CODEX第1ラウンドP2C-CX-002対応）。

    `load_properties()`は全keyへ一律`.strip()`するため、`cors.allow_origins`
    のように「前後空白そのものをfail-closed対象とする」設定（第6.1節）が
    production配線では`load_properties()`の時点で暗黙に補正されてしまい、
    `parse_cors_origins()`の空白拒否ロジックへ到達しないという構造的bypass
    があった（`_validate_cors_origin()`単体testでは検出できるが、実際の
    config読み込み経路では発現しない）。この関数はCORS originのように
    「値そのものの前後空白を検証したい」設定専用に、file全体を再走査して
    対象keyの生の値だけを返す。fileが存在しない・keyが存在しない場合は
    Noneを返す（`load_properties()`の`.get(key)`がNoneを返す場合と同じ
    契約——空allowlistへのfallbackは呼び出し側`parse_cors_origins(None)`が
    引き続き担う）。

    同一keyが複数行に出現する場合は`load_properties()`と同じく「最後の
    出現が勝つ」（dict代入と同じ上書きセマンティクス）。最初の一致で
    即returnすると、両関数間でkey解決結果がずれる余地が生まれるため、
    ファイル全体を走査し最後に見つかった値を保持する。
    """
    if not config_path.exists():
        return None

    last_match: Optional[str] = None
    with config_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")
            stripped_for_skip_check = line.strip()
            if not stripped_for_skip_check or stripped_for_skip_check.startswith("#"):
                continue
            if "=" not in line:
                continue
            raw_key, raw_value = line.split("=", 1)
            if raw_key.strip() == key:
                last_match = raw_value  # 意図的に.strip()しない

    return last_match


def parse_bool(value: Optional[str], default: bool) -> bool:
    """文字列設定値をboolへ変換"""
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    return default


def parse_csv(value: Optional[str], default: List[str]) -> List[str]:
    """カンマ区切り設定値を配列へ変換。keyが存在しても値が空／空白のみの
    場合はdefaultへfallbackする（`app_public.py`の既存契約と同一）。"""
    if value is None:
        return default

    items = [item.strip() for item in value.split(",") if item.strip()]
    return items if items else default


def parse_cors_origins(value: Optional[str]) -> List[str]:
    """`cors.allow_origins` をexact-origin allowlistへ変換する（第6.1節）。

    - key未設定・値が空／空白のみ → 空allowlist（same-origin機能は維持、
      `*` へfallbackしない）。これは唯一の許容されるfallbackであり、
      「値は存在するが一部不正」な場合には適用しない。
    - 値が存在する場合、カンマ区切りの各要素は scheme(http/https)://host[:port]
      のexact originでなければならない。1件でも不正な場合は該当要素だけを
      読み飛ばさず、`CorsConfigError` を送出して呼び出し側の起動をfail-closed
      にする（曖昧な黙示補正はしない）。
    - 正規化後（scheme/hostを小文字化、portはそのまま）で重複するoriginは
      設定ミスとして拒否する。
    """
    if value is None:
        return []
    if value.strip() == "":
        return []

    normalized: List[str] = []
    seen = set()
    for raw_item in value.split(","):
        canonical = _validate_cors_origin(raw_item)
        if canonical in seen:
            raise CorsConfigError(
                f"cors.allow_origins: origin が重複している: {canonical!r}"
            )
        seen.add(canonical)
        normalized.append(canonical)
    return normalized


def resolve_config_path(base_dir: Path) -> Path:
    """`APP_PROPERTIES_FILE`環境変数（相対pathの場合は`base_dir`基準）、
    または `base_dir/app.properties` を、consumer（app_public.py）と
    同一の規則で絶対pathへ解決する。"""
    default_config_path = base_dir / "app.properties"
    raw_config_path = Path(os.getenv("APP_PROPERTIES_FILE", str(default_config_path)))
    if not raw_config_path.is_absolute():
        raw_config_path = base_dir / raw_config_path
    return raw_config_path.resolve()
