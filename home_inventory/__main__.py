"""CLI for filesystem inventory."""
import argparse
import hashlib
import os
import sqlite3
import stat
import sys
import time
import zipfile
import tarfile
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
 path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
 dev INTEGER NOT NULL, inode INTEGER NOT NULL, sha256 TEXT,
 scanned_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS repositories (
 path TEXT PRIMARY KEY, origin TEXT, scanned_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS archive_entries (
 archive_path TEXT NOT NULL, entry_name TEXT NOT NULL,
 size INTEGER, sha256 TEXT, scanned_at INTEGER NOT NULL,
 PRIMARY KEY (archive_path, entry_name)
);
"""

def db_path(path):
    """Preserve invalid UTF-8 names as BLOB; retain existing TEXT keys."""
    value = os.fsdecode(os.fspath(path))
    return sqlite3.Binary(os.fsencode(value)) if any(0xDC80 <= ord(c) <= 0xDCFF for c in value) else value

def safe_display(value):
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    return ascii(value) if any(0xDC80 <= ord(c) <= 0xDCFF for c in value) else str(value)

def digest(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        h.update(block)
    return h.hexdigest()

def scan(root, mode, database):
    import subprocess
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.executescript(SCHEMA)
    conn.execute("""CREATE TABLE IF NOT EXISTS file_access (
        path BLOB PRIMARY KEY, uid INTEGER, gid INTEGER, mode INTEGER,
        hash_status TEXT, scanned_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS scan_errors (
        path BLOB, operation TEXT, message TEXT, scanned_at INTEGER NOT NULL)""")
    root_dev = root.stat().st_dev
    started = time.monotonic()
    now = int(time.time())
    counters = {"files": 0, "repos": 0, "archives": 0, "errors": 0, "bytes": 0}
    def error(exc, path=None, operation="scan"):
        counters["errors"] += 1
        message = str(exc)
        if path is not None:
            conn.execute("INSERT INTO scan_errors VALUES (?,?,?,?)",
                         (db_path(path), operation, message.encode("utf-8", "backslashreplace").decode("utf-8"), now))
        print(f"WARNING: {ascii(message)}", file=sys.stderr)
    def record_repo(path):
        marker = Path(path) / ".git"
        if not (marker.is_dir() or marker.is_file()):
            return
        try:
            p = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                               capture_output=True, text=True, timeout=10, check=False)
            origin = p.stdout.strip() if p.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            origin = ""
        conn.execute("INSERT OR REPLACE INTO repositories VALUES (?,?,?)",
                     (db_path(path), origin, now))
        counters["repos"] += 1

    def walk(path):
        record_repo(path)
        try:
            with os.scandir(path) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        st = entry.stat(follow_symlinks=False)
                        if st.st_dev != root_dev:
                            continue
                        if stat.S_ISDIR(st.st_mode):
                            if entry.name == ".git":
                                continue
                            yield from walk(entry.path)
                        elif stat.S_ISREG(st.st_mode):
                            yield entry.path, st
                    except (OSError, PermissionError) as exc:
                        error(exc, entry.path, "entry")
        except (OSError, PermissionError) as exc:
            error(exc, path, "scandir")
    try:
        for path, st in walk(root):
            key = db_path(path)
            if Path(path).name == ".git":
                continue
            previous = conn.execute("SELECT size,mtime_ns,dev,inode,sha256 FROM files WHERE path=?", (key,)).fetchone()
            old_hash = previous[4] if previous and previous[:4] == (st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino) else None
            sha = old_hash
            hash_status = "not_requested" if mode == "quick" else "not_hashed"
            if mode == "deep" or (mode == "normal" and st.st_size > 0 and conn.execute(
                "SELECT 1 FROM files WHERE size=? AND path<>? LIMIT 1", (st.st_size, key)).fetchone()):
                if not sha:
                    try:
                        with open(path, "rb") as f:
                            sha = digest(f)
                        after = os.stat(path, follow_symlinks=False)
                        if (after.st_size, after.st_mtime_ns, after.st_ino) != (st.st_size, st.st_mtime_ns, st.st_ino):
                            sha = None
                            error("Changed while hashing", path, "hash")
                    except OSError as exc:
                        hash_status = "permission_denied" if isinstance(exc, PermissionError) else "read_error"
                        error(exc, path, "hash")
            if sha:
                hash_status = "hashed"
            conn.execute("INSERT OR REPLACE INTO file_access VALUES (?,?,?,?,?,?)",
                         (key, st.st_uid, st.st_gid, stat.S_IMODE(st.st_mode), hash_status, now))
            conn.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)",
                         (key, st.st_size, st.st_mtime_ns, st.st_dev, st.st_ino, sha, now))
            counters["files"] += 1
            counters["bytes"] += st.st_size
            if mode != "quick" and path.lower().endswith((".zip", ".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz")):
                try:
                    conn.execute("DELETE FROM archive_entries WHERE archive_path=?", (key,))
                    if zipfile.is_zipfile(path):
                        with zipfile.ZipFile(path) as archive:
                            for item in archive.infolist():
                                if item.is_dir():
                                    continue
                                entry_hash = None
                                if mode == "deep":
                                    with archive.open(item) as f:
                                        entry_hash = digest(f)
                                conn.execute("INSERT OR REPLACE INTO archive_entries VALUES (?,?,?,?,?)",
                                             (key, db_path(item.filename), item.file_size, entry_hash, now))
                    elif tarfile.is_tarfile(path):
                        with tarfile.open(path, "r:*") as archive:
                            for item in archive:
                                if not item.isfile():
                                    continue
                                entry_hash = None
                                if mode == "deep":
                                    f = archive.extractfile(item)
                                    if f:
                                        with f:
                                            entry_hash = digest(f)
                                conn.execute("INSERT OR REPLACE INTO archive_entries VALUES (?,?,?,?,?)",
                                             (key, db_path(item.name), item.size, entry_hash, now))
                    counters["archives"] += 1
                except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, RuntimeError, EOFError) as exc:
                    error(exc, path, "archive")
            if counters["files"] % 500 == 0:
                conn.commit()
                elapsed = time.monotonic() - started
                print(f"Indexed {counters['files']:,} files, {counters['bytes']:,} bytes, {elapsed:.1f}s elapsed", flush=True)
        conn.commit()
    finally:
        conn.close()
    counters["elapsed_seconds"] = round(time.monotonic() - started, 2)
    print(counters)

def report(database, kind):
    conn = sqlite3.connect(database)
    try:
        if kind == "repos":
            rows = conn.execute("SELECT path,origin FROM repositories ORDER BY path")
        elif kind == "largest":
            rows = conn.execute("SELECT size,path FROM files ORDER BY size DESC LIMIT 50")
        else:
            rows = conn.execute("SELECT sha256,COUNT(*),SUM(size)-MAX(size) FROM files WHERE sha256 IS NOT NULL GROUP BY sha256 HAVING COUNT(*)>1 ORDER BY 3 DESC LIMIT 50")
        for row in rows:
            print("\t".join(safe_display(value) for value in row))
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(prog="home-inventory")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--root", type=Path, default=Path.home())
    s.add_argument("--mode", choices=["quick", "normal", "deep"], default="quick")
    r = sub.add_parser("report")
    r.add_argument("kind", choices=["repos", "largest", "duplicates"])
    for p in (s, r):
        p.add_argument("--database", type=Path, default=Path.home() / ".local/share/home-filesystem-inventory/inventory.db")
    args = parser.parse_args()
    try:
        if args.command == "scan":
            scan(args.root, args.mode, args.database.expanduser())
        else:
            report(args.database.expanduser(), args.kind)
    except (OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")

if __name__ == "__main__":
    main()
