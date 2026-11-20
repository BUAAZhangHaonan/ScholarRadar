import hashlib
import sqlite3
from contextlib import contextmanager

from .settings import DB, ROOT, dump


def key(*items):
    return hashlib.sha256(dump(items).encode()).hexdigest()[:32]


@contextmanager
def database(path=None, *, write=False):
    path = path or DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=20000")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if conn.in_transaction:
            conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate(path=None):
    with database(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS migrations(version TEXT PRIMARY KEY)")
        for file in sorted((ROOT / "migrations").glob("*.sql")):
            if db.execute(
                "SELECT 1 FROM migrations WHERE version=?", (file.name,)
            ).fetchone():
                continue
            version = file.name.replace("'", "''")
            db.executescript(
                "BEGIN IMMEDIATE;\n"
                + file.read_text()
                + f"\nINSERT INTO migrations VALUES('{version}');\nCOMMIT;"
            )


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args)]
