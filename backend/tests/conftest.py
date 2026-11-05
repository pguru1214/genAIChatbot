import os
import tempfile
from pathlib import Path

import pytest

# Isolate tests from a developer's actual database and API credentials.
_directory = tempfile.TemporaryDirectory(prefix='tripweave-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_directory.name) / 'tests.db')
os.environ['APP_MODE'] = 'demo'
os.environ['GEOAPIFY_API_KEY'] = ''


@pytest.fixture(scope='session', autouse=True)
def cleanup_test_database():
    from app.database import init_db
    init_db()
    yield
    from app.database import engine

    # Windows cannot remove SQLite files while pooled connections remain open.
    engine.dispose()
    _directory.cleanup()


@pytest.fixture(autouse=True)
def isolate_official_tourism_network(monkeypatch):
    import app.tourism as tourism

    async def unavailable(url):
        raise TimeoutError('Tests must explicitly mock tourism website content')

    monkeypatch.setattr(tourism, 'download_page', unavailable)
