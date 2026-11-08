from pathlib import Path

import pytest

from llm_guard.config import load_policy, load_rules

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def rules():
    return load_rules(ROOT / "config" / "rules.yaml")


@pytest.fixture(scope="session")
def policy():
    return load_policy(ROOT / "config" / "policy.yaml")
