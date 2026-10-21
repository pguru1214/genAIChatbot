import os
import tempfile
from pathlib import Path

import pytest

# Isolate tests from a developer's actual database and API credentials.
_directory = tempfile.TemporaryDirectory(prefix='tripweave-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_directory.name) / 'tests.db')
os.environ['APP_MODE'] = 'demo'


@pytest.fixture(scope='session', autouse=True)
def cleanup_test_database():
    yield
    from app.database import engine

    # Windows cannot remove SQLite files while pooled connections remain open.
    engine.dispose()
    _directory.cleanup()
