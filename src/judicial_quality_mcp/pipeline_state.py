"""Pipeline state management v0.3.0 — TTL + file persistence + thread safety.

Manages the execution progress of quality assessment pipelines,
supporting checkpoint/resume across process restarts.

Bridge Architecture: NO LLM calls. Pure state management.
"""

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Default TTL: 24 hours (in seconds)
_DEFAULT_TTL = int(os.environ.get("JQ_PIPELINE_TTL", 86400))

# Default persistence directory
_DEFAULT_PERSIST_DIR = os.environ.get(
    "JQ_PIPELINE_PERSIST_DIR",
    str(Path.home() / ".judicial_quality" / "pipeline_state"),
)


class PipelineStateManager:
    """Thread-safe pipeline state manager with TTL and file persistence."""

    def __init__(
        self,
        ttl: int = _DEFAULT_TTL,
        persist_dir: str = _DEFAULT_PERSIST_DIR,
    ):
        self._state: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._persist_dir = persist_dir

    def _is_expired(self, state: dict) -> bool:
        """Check if a state entry has expired based on TTL."""
        started_at = state.get("started_at", "")
        if not started_at:
            return True
        try:
            start_time = datetime.fromisoformat(started_at).timestamp()
            return (time.time() - start_time) > self._ttl
        except (ValueError, OSError):
            return True

    def _persist_path(self, session_id: str) -> Path:
        """Get the file path for a session's persisted state."""
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        return Path(self._persist_dir) / f"{safe_id}.json"

    def _save_to_disk(self, session_id: str, state: dict) -> None:
        """Persist a session's state to disk."""
        try:
            path = self._persist_path(session_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("pipeline_state: failed to persist session=%s: %s", session_id, e)

    def _load_from_disk(self, session_id: str) -> dict | None:
        """Load a session's state from disk."""
        try:
            path = self._persist_path(session_id)
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if not self._is_expired(data):
                    return data
                else:
                    # Clean up expired file
                    path.unlink(missing_ok=True)
                    logger.info("pipeline_state: expired session=%s removed from disk", session_id)
        except Exception as e:
            logger.warning("pipeline_state: failed to load session=%s: %s", session_id, e)
        return None

    def _cleanup_disk(self, session_id: str) -> None:
        """Remove a session's persisted state from disk."""
        try:
            path = self._persist_path(session_id)
            path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("pipeline_state: failed to cleanup session=%s: %s", session_id, e)

    def start(self, session_id: str, dimensions: list[str]) -> dict:
        """Start a new pipeline session."""
        with self._lock:
            state = {
                "dimensions": dimensions,
                "completed": [],
                "results": {},
                "started_at": datetime.now().isoformat(),
            }
            self._state[session_id] = state
            self._save_to_disk(session_id, state)
            logger.info("pipeline_state: started session=%s", session_id)
            return state

    def get(self, session_id: str) -> dict | None:
        """Get a session's state, loading from disk if not in memory."""
        with self._lock:
            # Try memory first
            state = self._state.get(session_id)
            if state is not None:
                if self._is_expired(state):
                    del self._state[session_id]
                    self._cleanup_disk(session_id)
                    return None
                return state

            # Try disk
            state = self._load_from_disk(session_id)
            if state is not None:
                self._state[session_id] = state
                return state

            return None

    def complete(self, session_id: str, dimension_name: str, result_summary: str | None = None) -> dict | None:
        """Mark a dimension as completed."""
        with self._lock:
            state = self._state.get(session_id)
            if state is None:
                # Try loading from disk
                state = self._load_from_disk(session_id)
                if state is None:
                    return None
                self._state[session_id] = state

            if self._is_expired(state):
                del self._state[session_id]
                self._cleanup_disk(session_id)
                return None

            if dimension_name not in state["completed"]:
                state["completed"].append(dimension_name)
            if result_summary:
                state["results"][dimension_name] = result_summary

            self._save_to_disk(session_id, state)
            logger.info(
                "pipeline_state: completed dim=%s, progress=%d/%d",
                dimension_name, len(state["completed"]), len(state["dimensions"]),
            )
            return state

    def reset(self, session_id: str) -> dict | None:
        """Reset a session's progress."""
        with self._lock:
            state = self._state.get(session_id)
            if state is None:
                return None
            state["completed"] = []
            state["results"] = {}
            self._save_to_disk(session_id, state)
            logger.info("pipeline_state: reset session=%s", session_id)
            return state

    def cleanup_expired(self) -> int:
        """Remove all expired sessions from memory and disk. Returns count of cleaned sessions."""
        cleaned = 0
        with self._lock:
            expired_ids = [
                sid for sid, state in self._state.items()
                if self._is_expired(state)
            ]
            for sid in expired_ids:
                del self._state[sid]
                self._cleanup_disk(sid)
                cleaned += 1
        logger.info("pipeline_state: cleaned %d expired sessions", cleaned)
        return cleaned

    def list_sessions(self) -> list[dict]:
        """List all active (non-expired) sessions with progress summary.

        Scans both in-memory and on-disk sessions.

        Returns:
            List of dicts with session_id, progress, started_at fields.
        """
        sessions = []
        seen_ids = set()

        with self._lock:
            # In-memory sessions
            for sid, state in self._state.items():
                if not self._is_expired(state):
                    total = len(state.get("dimensions", []))
                    done = len(state.get("completed", []))
                    sessions.append({
                        "session_id": sid,
                        "completed_count": done,
                        "total_count": total,
                        "progress_pct": round(done / total * 100) if total else 100,
                        "started_at": state.get("started_at", ""),
                        "source": "memory",
                    })
                seen_ids.add(sid)

            # On-disk sessions not in memory
            persist_path = Path(self._persist_dir)
            if persist_path.exists():
                for f in persist_path.glob("*.json"):
                    sid = f.stem
                    if sid in seen_ids:
                        continue
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        if not self._is_expired(data):
                            total = len(data.get("dimensions", []))
                            done = len(data.get("completed", []))
                            sessions.append({
                                "session_id": sid,
                                "completed_count": done,
                                "total_count": total,
                                "progress_pct": round(done / total * 100) if total else 100,
                                "started_at": data.get("started_at", ""),
                                "source": "disk",
                            })
                    except Exception:
                        pass

        return sessions

    def save_checkpoint(self, session_id: str) -> bool:
        """Explicitly persist a session to disk (useful before long operations).

        Returns True if session was found and saved, False otherwise.
        """
        with self._lock:
            state = self._state.get(session_id)
            if state is None:
                state = self._load_from_disk(session_id)
            if state is None or self._is_expired(state):
                return False
            self._save_to_disk(session_id, state)
            return True

    def restore_checkpoint(self, session_id: str) -> dict | None:
        """Load a session from disk into memory (useful after process restart).

        Returns the session state if found and not expired, None otherwise.
        """
        with self._lock:
            # Already in memory?
            state = self._state.get(session_id)
            if state is not None and not self._is_expired(state):
                return state

            # Load from disk
            state = self._load_from_disk(session_id)
            if state is not None:
                self._state[session_id] = state
                return state
            return None

    def cleanup_expired_disk(self) -> int:
        """Scan persistence directory and remove expired session files.

        Returns count of cleaned files.
        """
        cleaned = 0
        persist_path = Path(self._persist_dir)
        if not persist_path.exists():
            return 0

        with self._lock:
            for f in persist_path.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if self._is_expired(data):
                        f.unlink(missing_ok=True)
                        cleaned += 1
                except Exception:
                    pass

        if cleaned:
            logger.info("pipeline_state: cleaned %d expired disk files", cleaned)
        return cleaned
