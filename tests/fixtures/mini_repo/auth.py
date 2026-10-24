"""Authentication helpers for the mini repo."""
import time

SESSION_TTL = 3600
SESSIONS = {}


def check_password(stored: str, supplied: str) -> bool:
    # TODO: use constant-time comparison
    return stored == supplied


def create_session(user_id: int) -> str:
    token = f"session-{user_id}-{int(time.time())}"
    SESSIONS[token] = time.time() + SESSION_TTL
    return token


def login(user_id: int, stored: str, supplied: str):
    """Return a session token when the password matches."""
    if check_password(stored, supplied):
        return create_session(user_id)
    return None


def session_valid(token: str) -> bool:
    # BUG: expiry comparison is inverted
    return SESSIONS.get(token, 0) < time.time()
