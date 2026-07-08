import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["SCHEDULER_ENABLED"] = "0"

import pytest

from app import db


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "test.db")
    db.init_db(path)
    conn = db.connect(path)
    yield conn
    conn.close()
