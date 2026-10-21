import os
import tempfile
from pathlib import Path

# Isolate tests from a developer's actual database and API credentials.
_directory = tempfile.TemporaryDirectory(prefix='tripweave-tests-')
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(_directory.name) / 'tests.db')
os.environ['APP_MODE'] = 'demo'
