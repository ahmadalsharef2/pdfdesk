import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).parent / "corpus"))
import build  # noqa: E402


@pytest.fixture
def v1(tmp_path):
    p = tmp_path / "v1.pdf"
    build.contract(p, False)
    return pymupdf.open(p)


@pytest.fixture
def v1_path(tmp_path):
    p = tmp_path / "v1.pdf"
    build.contract(p, False)
    return str(p)
