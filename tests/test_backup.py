import re
import sqlite3

from scripts import backup_db


def _make_source(path):
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE places (id INTEGER PRIMARY KEY, name TEXT)')
        conn.executemany('INSERT INTO places (name) VALUES (?)', [('西湖',), ('灵隐寺',)])
        conn.commit()


def _backups(dest):
    return sorted(dest.glob('trip-*.db'))


def test_backup_creates_valid_copy(tmp_path):
    src = tmp_path / 'trip.db'
    dest = tmp_path / 'backups'
    _make_source(src)

    assert backup_db.main(['--source', str(src), '--dest-dir', str(dest), '--keep', '2']) == 0

    files = _backups(dest)
    assert len(files) == 1
    assert re.fullmatch(r'trip-\d{8}T\d{6}Z\.db', files[0].name)
    with sqlite3.connect(files[0]) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('SELECT COUNT(*) FROM places').fetchone()[0] == 2


def test_backup_retains_latest_files_only(tmp_path, monkeypatch):
    src = tmp_path / 'trip.db'
    dest = tmp_path / 'backups'
    _make_source(src)
    stamps = iter(['20260101T000000Z', '20260102T000000Z', '20260103T000000Z'])
    monkeypatch.setattr(backup_db, '_timestamp', lambda: next(stamps))

    for _ in range(3):
        assert backup_db.main(['--source', str(src), '--dest-dir', str(dest), '--keep', '2']) == 0

    assert [path.name for path in _backups(dest)] == [
        'trip-20260102T000000Z.db',
        'trip-20260103T000000Z.db',
    ]


def test_backup_missing_source_fails(tmp_path, capsys):
    dest = tmp_path / 'backups'

    code = backup_db.main(['--source', str(tmp_path / 'missing.db'), '--dest-dir', str(dest)])

    assert code != 0
    assert not _backups(dest)
    assert not dest.exists()
    assert 'missing.db' in capsys.readouterr().err


def test_resolve_source_prefers_database_url(tmp_path, monkeypatch):
    custom = tmp_path / 'custom.db'
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{custom.as_posix()}')
    assert backup_db.resolve_source(None) == custom

    monkeypatch.delenv('DATABASE_URL')
    assert backup_db.resolve_source(None) == backup_db.Path('trip.db')
