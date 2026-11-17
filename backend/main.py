"""Start the TripWeave API: python main.py (from backend)."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys


def main():
    backend = Path(__file__).resolve().parent
    if importlib.util.find_spec('uvicorn') is None:
        interpreter = backend / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if interpreter.is_file() and interpreter.resolve() != Path(sys.executable).resolve():
            print('Using the backend virtual environment.', file=sys.stderr, flush=True)
            os.execv(str(interpreter), [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]])
        raise SystemExit(
            'Backend dependencies are missing. From the repository root run:\n'
            '  uv sync --project backend --frozen\n'
            'Then run python main.py again from backend.'
        )
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--reload', action='store_true', help='Restart when backend code changes')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    os.chdir(backend)
    uvicorn.run('app.main:app', app_dir=str(backend), host=args.host, port=args.port, reload=args.reload)


if __name__ == '__main__':
    main()
