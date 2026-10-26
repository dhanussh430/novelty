import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _fresh_cache():
    from novelty import sources
    sources.clear_cache()
    yield
    sources.clear_cache()
