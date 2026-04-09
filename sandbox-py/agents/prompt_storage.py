import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class AgentPromptStore:
    """Storage for per-agent prompts with version tracking."""

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.base_dir = Path(__file__).parent / "prompts" / agent_name
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.meta_file = self.base_dir / "meta.json"

    def _load_meta(self) -> dict:
        """Load metadata file."""
        if self.meta_file.exists():
            with open(self.meta_file, "r") as f:
                return json.load(f)
        return {"current_version": None, "versions": []}

    def _save_meta(self, meta: dict):
        """Save metadata file."""
        with open(self.meta_file, "w") as f:
            json.dump(meta, f, indent=2)

    def get_current_prompt(self) -> str:
        """Get current prompt.

        Preference order:
        1) current_version (explicitly selected/latest)
        2) highest scored version
        3) v0 fallback
        """
        meta = self._load_meta()

        if meta.get("current_version") is None:
            # Return default v0
            return self._load_version(0)

        current_version = meta.get("current_version")
        if current_version is not None:
            try:
                return self._load_version(current_version)
            except Exception:
                pass

        versions = meta.get("versions", [])
        if not versions:
            return self._load_version(0)

        scored = [v for v in versions if v.get("score") is not None]
        if not scored:
            # Return current version or v0
            current = meta.get("current_version", 0)
            return self._load_version(current)

        best = max(scored, key=lambda v: v["score"])
        return self._load_version(best["version_id"])

    def _load_version(self, version_id: int) -> str:
        """Load a specific version of the prompt."""
        prompt_file = self.base_dir / f"v{version_id}.txt"

        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                return f.read()

        # Default: load v0
        if version_id != 0:
            return self._load_version(0)

        raise FileNotFoundError(f"No prompt found for {self.agent_name}")

    def save_prompt(
        self,
        version_id: int,
        content: str,
        score: Optional[float] = None,
        parent_version_id: Optional[int] = None,
        changes_summary: str = "",
    ):
        """Save a new version of the prompt."""
        # Save prompt file
        prompt_file = self.base_dir / f"v{version_id}.txt"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(content)

        # Update metadata
        meta = self._load_meta()

        # Add new version
        version_info = {
            "version_id": version_id,
            "score": score,
            "parent_version_id": parent_version_id,
            "changes_summary": changes_summary,
            "created_at": datetime.now().isoformat(),
        }

        meta["versions"] = [
            v for v in meta.get("versions", []) if v["version_id"] != version_id
        ]
        meta["versions"].append(version_info)
        meta["current_version"] = version_id

        self._save_meta(meta)

        return version_id

    def get_best_version(self) -> Optional[Dict[str, Any]]:
        """Get version with highest score."""
        meta = self._load_meta()
        versions = meta.get("versions", [])

        scored = [v for v in versions if v.get("score") is not None]
        if not scored:
            return None

        return max(scored, key=lambda v: v["score"])

    def get_latest_version_id(self) -> int:
        """Get the latest version ID."""
        meta = self._load_meta()
        versions = meta.get("versions", [])

        if not versions:
            return 0

        return max(v["version_id"] for v in versions)

    def get_next_version_id(self) -> int:
        """Get next version ID to use."""
        return self.get_latest_version_id() + 1

    def get_all_versions(self) -> List[Dict[str, Any]]:
        """Get all versions with metadata."""
        meta = self._load_meta()
        return meta.get("versions", [])

    def load_version_with_highest_score(self) -> tuple[int, str]:
        """Load version with highest score. Returns (version_id, prompt)."""
        meta = self._load_meta()
        versions = meta.get("versions", [])

        scored = [v for v in versions if v.get("score") is not None]

        if scored:
            best = max(scored, key=lambda v: v["score"])
            version_id = best["version_id"]
        else:
            version_id = self.get_latest_version_id() if versions else 0

        return version_id, self._load_version(version_id)


# Convenience functions
def get_prompt(agent_name: str) -> str:
    """Get current prompt for an agent."""
    store = AgentPromptStore(agent_name)
    return store.get_current_prompt()


def save_prompt(
    agent_name: str,
    version_id: int,
    content: str,
    score: Optional[float] = None,
    parent_version_id: Optional[int] = None,
    changes_summary: str = "",
):
    """Save a new version of an agent's prompt."""
    store = AgentPromptStore(agent_name)
    return store.save_prompt(
        version_id, content, score, parent_version_id, changes_summary
    )
