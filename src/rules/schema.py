"""Load and validate language rule files (e.g. ``java.yaml``).

A rule file declares which types are closeable resources, which methods
release them, and which AST patterns represent safe wrappers (like
try-with-resources).  This module parses the YAML and exposes the data
as typed dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Dataclasses mirroring the YAML structure
# ---------------------------------------------------------------------------

@dataclass
class AcquisitionRule:
    """A type whose constructor or factory method produces a closeable resource."""
    type: str
    module: str = ""
    factory_methods: list[str] = field(default_factory=list)


@dataclass
class ReleaseRule:
    """A method name that closes / releases a resource."""
    method: str


@dataclass
class SafeWrapperRule:
    """An AST pattern that guarantees safe resource management."""
    ast_node_type: str
    description: str = ""


@dataclass
class LanguageRules:
    """The complete rule-set for one language.

    Attributes:
        language:       Language identifier (e.g. ``java``).
        acquisitions:   Types/factories that produce closeable resources.
        releases:       Method names that close resources.
        safe_wrappers:  AST node types that represent safe-management patterns.
    """
    language: str
    acquisitions: list[AcquisitionRule] = field(default_factory=list)
    releases: list[ReleaseRule] = field(default_factory=list)
    safe_wrappers: list[SafeWrapperRule] = field(default_factory=list)

    # ----- convenience look-ups -------------------------------------------

    @property
    def acquisition_type_names(self) -> set[str]:
        """Set of type names that are known closeable resources."""
        return {a.type for a in self.acquisitions}

    @property
    def release_method_names(self) -> set[str]:
        """Set of method names that close a resource."""
        return {r.method for r in self.releases}

    @property
    def safe_wrapper_node_types(self) -> set[str]:
        """Set of AST node type strings that indicate safe wrappers."""
        return {s.ast_node_type for s in self.safe_wrappers}

    def is_acquisition_type(self, type_name: str) -> bool:
        """Return ``True`` if *type_name* is a known closeable resource."""
        return type_name in self.acquisition_type_names

    def is_release_method(self, method_name: str) -> bool:
        """Return ``True`` if *method_name* is a known release call."""
        return method_name in self.release_method_names


# ---------------------------------------------------------------------------
# Loading & validation
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"language", "acquisitions", "releases", "safe_wrappers"}


def load_rules(path: str | Path) -> LanguageRules:
    """Load and validate a YAML rule file.

    Args:
        path: Path to the ``.yaml`` rule file.

    Returns:
        A ``LanguageRules`` instance.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If required keys are missing or malformed.
    """
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"Rule file must be a YAML mapping, got {type(raw).__name__}")

    missing = _REQUIRED_KEYS - raw.keys()
    if missing:
        raise ValueError(f"Rule file is missing required keys: {missing}")

    acquisitions = [
        AcquisitionRule(
            type=a["type"],
            module=a.get("module", ""),
            factory_methods=a.get("factory_methods", []),
        )
        for a in raw.get("acquisitions", [])
    ]

    releases = [
        ReleaseRule(method=r["method"])
        for r in raw.get("releases", [])
    ]

    safe_wrappers = [
        SafeWrapperRule(
            ast_node_type=s["ast_node_type"],
            description=s.get("description", ""),
        )
        for s in raw.get("safe_wrappers", [])
    ]

    return LanguageRules(
        language=raw["language"],
        acquisitions=acquisitions,
        releases=releases,
        safe_wrappers=safe_wrappers,
    )


def load_default_java_rules() -> LanguageRules:
    """Load the built-in ``java.yaml`` rules shipped with the project."""
    rules_dir = Path(__file__).parent
    return load_rules(rules_dir / "java.yaml")
