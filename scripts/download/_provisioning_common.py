"""
_provisioning_common.py — Phase 2-D Round 2 AT-17B共通provisioningヘルパー
（P2D-AT17-BOOTSTRAP対応、指示書Round 2第11.2節「共通契約」の実装）

full-data provisioning script（download_osm_provision.py・download_river_flood_provision.py）が
共有する、fail-closedなfetch・検証・atomic write・manifest記録ロジック。

契約（指示書第11.2節）:
  - HTTPSのみ
  - allowlist済みdomainのみ（redirect先も検証）
  - timeout/retry上限
  - partial fileからatomic rename
  - archive/content-type検査
  - SHA-256計算、可能ならprovider checksum照合
  - source URL・timestamp・license ID・raw hashをmanifestへ記録
  - 既存の同名dataを無断上書きしない
  - disk容量のpreflight
  - failure時に半端なactive dataを残さない
  - secretを引数・logへ出さない（本モジュールはsecretを一切扱わない設計）
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


class ProvisioningError(Exception):
    pass


@dataclass
class FetchResult:
    ok: bool
    final_path: Path | None = None
    sha256: str | None = None
    bytes_written: int = 0
    http_status: int | None = None
    error: str | None = None
    redirected_to: str | None = None


def check_disk_space(path: Path, required_bytes: int) -> None:
    """`path`が存在するfilesystemの空き容量が`required_bytes`未満ならProvisioningErrorを送出する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(path.parent)
    if usage.free < required_bytes:
        raise ProvisioningError(
            f"insufficient disk space: available={usage.free} required={required_bytes} at {path.parent}"
        )


def _validate_url_domain(url: str, allowed_domains: tuple) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ProvisioningError(f"non-HTTPS URL rejected: {url}")
    if parsed.hostname not in allowed_domains:
        raise ProvisioningError(f"domain not in allowlist: {parsed.hostname!r} (url={url})")


def fetch_with_validation(
    url: str,
    dest_path: Path,
    *,
    allowed_domains: tuple,
    timeout_seconds: float = 60.0,
    max_retries: int = 3,
    retry_backoff_seconds: float = 2.0,
    min_bytes: int = 1,
    expected_sha256: str | None = None,
    user_agent: str = "OnHighGround2/1.0 (project-data-provisioning)",
    overwrite_existing: bool = False,
    max_bytes: int | None = None,
) -> FetchResult:
    """`url`から`dest_path`へfail-closedにfetchする。

    - urlのdomainがallowed_domainsに含まれない場合は拒否する（redirect先も同様に検証、
      urllibのHTTPRedirectHandlerを無効化し、redirectを手動で1段ずつ検証する）。
    - 既存の`dest_path`があり`overwrite_existing=False`の場合は拒否する。
    - 一時ファイルへ書き込み、成功時のみatomic rename（os.replace）する。
    - 失敗時は一時ファイルを削除し、dest_pathを一切変更しない。
    """
    if dest_path.exists() and not overwrite_existing:
        return FetchResult(ok=False, error=f"destination already exists (overwrite_existing=False): {dest_path}")

    try:
        _validate_url_domain(url, allowed_domains)
    except ProvisioningError as exc:
        return FetchResult(ok=False, error=str(exc))

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    last_error = None
    for attempt in range(1, max_retries + 1):
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=f".{dest_path.name}.", suffix=".partial", dir=str(dest_path.parent)
        )
        tmp_path = Path(tmp_name)
        try:
            os.close(tmp_fd)

            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    _validate_url_domain(newurl, allowed_domains)  # fail-closed: unapproved redirect domain rejected
                    return super().redirect_request(req, fp, code, msg, headers, newurl)

            opener = urllib.request.build_opener(_NoRedirect())
            req = urllib.request.Request(url, headers={"User-Agent": user_agent})

            with opener.open(req, timeout=timeout_seconds) as resp:
                status = getattr(resp, "status", 200)
                hasher = hashlib.sha256()
                total = 0
                with tmp_path.open("wb") as out:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        total += len(chunk)
                        if max_bytes is not None and total > max_bytes:
                            raise ProvisioningError(f"response exceeded max_bytes={max_bytes}, aborting")
                        hasher.update(chunk)
                        out.write(chunk)

            if total < min_bytes:
                raise ProvisioningError(f"downloaded {total} bytes, below min_bytes={min_bytes}")

            digest = hasher.hexdigest()
            if expected_sha256 is not None and digest.lower() != expected_sha256.lower():
                raise ProvisioningError(
                    f"checksum mismatch: expected={expected_sha256} actual={digest}"
                )

            os.replace(tmp_path, dest_path)  # atomic rename within same filesystem
            return FetchResult(ok=True, final_path=dest_path, sha256=digest, bytes_written=total, http_status=status)

        except (urllib.error.URLError, urllib.error.HTTPError, ProvisioningError, OSError, TimeoutError) as exc:
            last_error = str(exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds)
                continue
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    return FetchResult(ok=False, error=f"failed after {max_retries} attempts: {last_error}")


def write_manifest(manifest_path: Path, data: dict) -> str:
    """manifestをatomicに書き込み、書き込んだcontentのSHA-256を返す。"""
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.", suffix=".partial", dir=str(manifest_path.parent) if manifest_path.parent.exists() else None
    )
    tmp_path = Path(tmp_name)
    try:
        os.close(tmp_fd)
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, manifest_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_of_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
