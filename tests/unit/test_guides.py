"""Every core module ships a five-bullet guide in its sub-package's guide/ folder."""

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "refund_agent"
CORE_MODULES = [
    "policy/models",
    "policy/clock",
    "policy/rules",
    "data/repository",
    "data/memory",
    "data/postgres",
    "data/demo",
    "service/refund_service",
]


@pytest.mark.parametrize("module", CORE_MODULES)
def test_every_core_module_has_guide(module: str) -> None:
    package, stem = module.split("/")
    guide = SRC / package / "guide" / f"{stem}.md"
    assert guide.is_file(), f"missing guide: {guide}"
    lines = guide.read_text().splitlines()
    assert lines[0] == f"# {stem}.py"
    assert sum(1 for line in lines if line.startswith("- ")) == 5
