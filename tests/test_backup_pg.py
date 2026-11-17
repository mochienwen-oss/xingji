from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import backup_pg


def _completed(command, code=0, stderr=''):
    return SimpleNamespace(returncode=code, stdout='', stderr=stderr)


def _fake_run(record, *, fail=False):
    def run(command, **kwargs):
        record['commands'].append(command)
        record['env'] = kwargs.get('env', {})
        if fail and command[0] == 'pg_dump':
            return _completed(command, 1, 'connection failed')
        if command[0] == 'pg_dump':
            target = Path(command[command.index('--file') + 1])
            target.write_bytes(b'PGDMP fake dump')
        return _completed(command)
    return run


def test_parse_database_url_accepts_sqlalchemy_psycopg():
    settings = backup_pg.parse_database_url(
        'postgresql+psycopg://postgres:secret%40x@127.0.0.1:5433/trip'
    )
    assert settings == {
        'host': '127.0.0.1',
        'port': '5433',
        'user': 'postgres',
        'password': 'secret@x',
        'database': 'trip',
        'sslmode': '',
    }


def test_parse_database_url_passes_sslmode_to_environment(tmp_path, monkeypatch):
    record = {'commands': [], 'env': {}}
    monkeypatch.setattr(backup_pg.subprocess, 'run', _fake_run(record))
    monkeypatch.setattr(backup_pg, '_timestamp', lambda: '20260101T030000Z')

    backup_pg.backup(
        'postgresql://postgres@db.example.com:5432/trip?sslmode=verify-full',
        tmp_path / 'backups',
    )

    assert record['env']['PGSSLMODE'] == 'verify-full'


def test_parse_database_url_rejects_unknown_sslmode():
    with pytest.raises(backup_pg.BackupError, match='sslmode'):
        backup_pg.parse_database_url(
            'postgresql://postgres@db.example.com:5432/trip?sslmode=insecure'
        )


def test_parse_database_url_rejects_sqlite():
    with pytest.raises(backup_pg.BackupError, match='PostgreSQL'):
        backup_pg.parse_database_url('sqlite:///./trip.db')


def test_backup_runs_dump_and_verify_without_password_in_argv(tmp_path, monkeypatch):
    record = {'commands': [], 'env': {}}
    monkeypatch.setattr(backup_pg.subprocess, 'run', _fake_run(record))
    monkeypatch.setattr(backup_pg, '_timestamp', lambda: '20260101T030000Z')

    target = backup_pg.backup(
        'postgresql+psycopg://postgres:secret@127.0.0.1:5433/trip',
        tmp_path / 'backups', keep=2,
    )

    assert target.name == 'trip-20260101T030000Z.dump'
    assert target.stat().st_size > 0
    assert record['env']['PGPASSWORD'] == 'secret'
    command_text = ' '.join(' '.join(command) for command in record['commands'])
    assert 'secret' not in command_text
    assert '--format=custom' in record['commands'][0]
    assert '--dbname' in record['commands'][0]
    assert record['commands'][1][:2] == ['pg_restore', '--list']


def test_backup_failure_cleans_partial_file(tmp_path, monkeypatch):
    record = {'commands': [], 'env': {}}
    monkeypatch.setattr(backup_pg.subprocess, 'run', _fake_run(record, fail=True))
    monkeypatch.setattr(backup_pg, '_timestamp', lambda: '20260101T030000Z')

    with pytest.raises(backup_pg.BackupError, match='connection failed'):
        backup_pg.backup('postgresql://postgres@127.0.0.1:5433/trip', tmp_path / 'backups')

    dest = tmp_path / 'backups'
    assert not list(dest.glob('*.dump'))
    assert not list(dest.glob('.*.tmp'))


def test_backup_prunes_old_files(tmp_path, monkeypatch):
    record = {'commands': [], 'env': {}}
    monkeypatch.setattr(backup_pg.subprocess, 'run', _fake_run(record))
    stamps = iter(['20260101T000000Z', '20260102T000000Z', '20260103T000000Z'])
    monkeypatch.setattr(backup_pg, '_timestamp', lambda: next(stamps))
    dest = tmp_path / 'backups'

    for _ in range(3):
        backup_pg.backup('postgresql://postgres@127.0.0.1:5433/trip', dest, keep=2)

    assert [path.name for path in sorted(dest.glob('trip-*.dump'))] == [
        'trip-20260102T000000Z.dump',
        'trip-20260103T000000Z.dump',
    ]


def test_main_without_database_url_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    code = backup_pg.main(['--dest-dir', str(tmp_path / 'backups')])
    assert code == 1
    assert 'DATABASE_URL' in capsys.readouterr().err


def test_main_wraps_backup_errors(tmp_path, monkeypatch, capsys):
    record = {'commands': [], 'env': {}}
    monkeypatch.setattr(backup_pg.subprocess, 'run', _fake_run(record, fail=True))
    code = backup_pg.main([
        '--database-url', 'postgresql://postgres@127.0.0.1:5433/trip',
        '--dest-dir', str(tmp_path / 'backups'),
    ])
    assert code == 1
    assert 'connection failed' in capsys.readouterr().err
