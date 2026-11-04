"""Connect an existing local PostgreSQL database without exposing its password."""

from getpass import getpass
from pathlib import Path

from dotenv import set_key
from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


def main():
    print('Configure an existing PostgreSQL database (press Enter for defaults).')
    host = input('Host [localhost]: ').strip() or 'localhost'
    port = input('Port [5432]: ').strip() or '5432'
    database = input('Database [tripweave]: ').strip() or 'tripweave'
    username = input('Username [postgres]: ').strip() or 'postgres'
    password = getpass('PostgreSQL password (hidq2den): ')
    try:
        url = URL.create('postgresql+psycopg', username=username, password=password,
                         host=host, port=int(port), database=database)
    except ValueError:
        print('Port must be a number. Configuration was not changed.')
        return 1

    # Test credentials before changing the application's configuration.
    probe = create_engine(url, connect_args={'connect_timeout': 5})
    try:
        with probe.connect() as connection:
            connection.execute(text('SELECT 1'))
        from app.database import Base

        Base.metadata.create_all(probe)
        tables = inspect(probe).get_table_names()
        required = {'trips', 'action_proposals'}
        if not required.issubset(tables):
            print('Required tables were not found. Configuration was not changed.')
            return 1
    except SQLAlchemyError:
        print('Connection or table creation failed. Check PostgreSQL is running,')
        print('the database name, port, credentials, and table creation permissions.')
        print('Configuration was not changed.')
        return 1
    finally:
        probe.dispose()

    env_path = Path(__file__).resolve().parent / '.env'
    set_key(str(env_path), 'DATABASE_URL', url.render_as_string(hide_password=False))
    print('Connected successfully. Tables verified: trips, action_proposals.')
    print('Saved backend/.env. Restart the backend to use PostgreSQL.')
    print('Existing SQLite plans have not been copied.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
