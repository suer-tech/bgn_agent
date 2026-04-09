import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PromptVersion(BaseModel):
    version_id: int
    system_prompt: str
    created_at: datetime = Field(default_factory=datetime.now)
    parent_version: Optional[int] = None
    generation_method: Literal["manual", "evolution", "merge"] = "manual"
    test_score: Optional[float] = None
    failure_patterns: List[str] = Field(default_factory=list)
    changes_summary: str = ""
    rationale: str = ""


class PromptStore:
    def __init__(self, store_dir: str = "prompts"):
        self.store_dir = Path(__file__).parent / store_dir
        self.store_dir.mkdir(exist_ok=True)
        self.prompt_versions: List[PromptVersion] = []
        self._load_all_versions()

    def _load_all_versions(self):
        """Load all prompt versions from disk."""
        index_file = self.store_dir / "index.json"
        if index_file.exists():
            with open(index_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for v_data in data.get("versions", []):
                    if "created_at" in v_data and isinstance(v_data["created_at"], str):
                        v_data["created_at"] = datetime.fromisoformat(
                            v_data["created_at"]
                        )
                    self.prompt_versions.append(PromptVersion(**v_data))

    def _save_index(self):
        """Save index of all versions."""
        data = {
            "versions": [
                {
                    "version_id": v.version_id,
                    "system_prompt": v.system_prompt[:500]
                    + "...",  # Don't store full prompt in index
                    "created_at": v.created_at.isoformat(),
                    "parent_version": v.parent_version,
                    "generation_method": v.generation_method,
                    "test_score": v.test_score,
                    "failure_patterns": v.failure_patterns,
                }
                for v in self.prompt_versions
            ]
        }
        with open(self.store_dir / "index.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def save(self, version: PromptVersion):
        """Save a prompt version to disk."""
        # Save full prompt to separate file
        prompt_file = self.store_dir / f"v{version.version_id}.txt"
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(version.system_prompt)

        # Add to versions list
        existing_idx = None
        for i, v in enumerate(self.prompt_versions):
            if v.version_id == version.version_id:
                existing_idx = i
                break

        if existing_idx is not None:
            self.prompt_versions[existing_idx] = version
        else:
            self.prompt_versions.append(version)

        self._save_index()

    def save_with_score(self, version: PromptVersion):
        """Save version with test score."""
        self.save(version)
        # Also save metadata for quick lookup
        meta_file = self.store_dir / f"v{version.version_id}_meta.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version_id": version.version_id,
                    "test_score": version.test_score,
                    "generation_method": version.generation_method,
                    "failure_patterns": version.failure_patterns,
                    "created_at": version.created_at.isoformat(),
                },
                f,
                indent=2,
            )

    def load_version(self, version_id: int) -> PromptVersion:
        """Load a specific version of the prompt."""
        prompt_file = self.store_dir / f"v{version_id}.txt"
        if not prompt_file.exists():
            raise FileNotFoundError(f"Version {version_id} not found")

        with open(prompt_file, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        # Try to load metadata
        meta_file = self.store_dir / f"v{version_id}_meta.json"
        meta = {}
        if meta_file.exists():
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)

        return PromptVersion(
            version_id=version_id,
            system_prompt=system_prompt,
            parent_version=meta.get("parent_version"),
            generation_method=meta.get("generation_method", "manual"),
            test_score=meta.get("test_score"),
            failure_patterns=meta.get("failure_patterns", []),
        )

    def get_best_version(self) -> Optional[PromptVersion]:
        """Get the version with the highest test score."""
        if not self.prompt_versions:
            return None
        scored = [v for v in self.prompt_versions if v.test_score is not None]
        if not scored:
            return None
        return max(scored, key=lambda v: v.test_score)

    def get_latest_version(self) -> Optional[PromptVersion]:
        """Get the latest version by ID."""
        if not self.prompt_versions:
            return None
        return max(self.prompt_versions, key=lambda v: v.version_id)


def get_baseline_prompt_text() -> str:
    """Extract the baseline system prompt from agent.py"""
    # Read from agent.py - extract system_prompt variable
    agent_file = Path(__file__).parent.parent / "agent.py"
    with open(agent_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Find system_prompt variable
    import re

    match = re.search(r'system_prompt\s*=\s+r?"""(.*?)"""', content, re.DOTALL)
    if not match:
        # Try single quotes
        match = re.search(r"system_prompt\s*=\s+r'''(.*?)'''", content, re.DOTALL)

    if match:
        return match.group(1).strip()

    raise ValueError("Could not find system_prompt in agent.py")


def load_baseline_prompt() -> PromptVersion:
    """Load or create the baseline prompt (version 0)."""
    store = PromptStore()

    # Try to load existing v0
    try:
        return store.load_version(0)
    except FileNotFoundError:
        pass

    # Create new baseline
    baseline = PromptVersion(
        version_id=0,
        system_prompt=get_baseline_prompt_text(),
        generation_method="manual",
    )
    store.save(baseline)
    return baseline
