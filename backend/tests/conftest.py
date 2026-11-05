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


@pytest.fixture
def itinerary_payload():
    def build(days=3, sources=None):
        sources = sources or ['source-1']
        activities = [
            {'kind': kind, 'title': title, 'duration_minutes': minutes, 'description': 'Planning estimate.', 'source_ids': sources if kind == 'visit' else []}
            for kind, title, minutes in [('visit', 'First attraction', 90), ('transfer', 'Local transfer', 20),
                ('visit', 'Second attraction', 120), ('meal', 'Lunch', 60), ('transfer', 'Walk to next attraction', 20),
                ('visit', 'Third attraction', 90), ('break', 'Return and rest', 60)]]
        return {'overview': 'Suggested trip with timed activities.', 'recommended_mode': 'Compare road and rail; services unverified.',
            'transport_options': [{'mode': 'car/taxi', 'route': 'Origin to destination', 'duration_estimate': 'Estimate only',
                'cost_estimate': 'Not verified', 'best_for': 'Flexible departure'}],
            'days': [{'day': i, 'base': 'Destination base', 'activities': activities} for i in range(1, days + 1)],
            'budget_allocation': [{'category': 'Trip allocation', 'amount': 10000}],
            'packing_list': ['Comfortable shoes', 'Charger'], 'notes': ['Confirm opening days before travel.'], 'source_ids': sources}
    return build
