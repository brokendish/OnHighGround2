"""
operator_session.py — Phase B operator Web admin session store

tasks/OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase B。

セッションはserver-side in-memory dict（プロセス内、`backend-operator`の
再起動で全件失効する。意図的な挙動——OPERATOR_AUTH_SECRETローテーション後や
再起動後に古いsessionが生き残らない）。

session_idそのものが認証情報であり、JWT等の自己署名tokenは使わない
（署名鍵の追加管理コストを避けるため。owner方針: secret数を増やさない）。
raw OPERATOR_AUTH_SECRETはsession生成後は保持しない（actor_idはfingerprintのみ）。
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

SESSION_COOKIE_NAME = "ohg_admin_session"
SESSION_TTL_SECONDS = 60 * 60  # 60分（owner既定値）
CSRF_HEADER_NAME = "x-csrf-token"

# GET/HEAD/OPTIONSはstate変更を行わないため、CSRF token検証の対象外とする
# （owner方針: GET endpointはstateを変更してはならない前提に立つ）。
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Session:
    session_id: str
    csrf_token: str
    actor_id: str
    created_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


_lock = threading.Lock()
_sessions: dict[str, Session] = {}


def create_session(*, actor_id: str) -> Session:
    """新規sessionを生成しstoreへ登録する。session_id/csrf_tokenは暗号論的乱数。"""
    now = datetime.now(timezone.utc)
    session = Session(
        session_id=secrets.token_urlsafe(32),
        csrf_token=secrets.token_urlsafe(32),
        actor_id=actor_id,
        created_at=now,
        expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
    )
    with _lock:
        _sessions[session.session_id] = session
    return session


def get_session(session_id: Optional[str]) -> Optional[Session]:
    """有効なsessionを返す。未存在・期限切れの場合はNone（期限切れは削除する）。"""
    if not session_id:
        return None
    with _lock:
        session = _sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired:
            del _sessions[session_id]
            return None
        return session


def delete_session(session_id: Optional[str]) -> None:
    """sessionを破棄する（logout）。存在しない場合も静かに成功する。"""
    if not session_id:
        return
    with _lock:
        _sessions.pop(session_id, None)


def session_count() -> int:
    """test/診断用: 現在保持しているsession件数（期限切れ含む）。"""
    with _lock:
        return len(_sessions)


def clear_all_sessions() -> None:
    """test専用: storeを完全にリセットする。"""
    with _lock:
        _sessions.clear()
