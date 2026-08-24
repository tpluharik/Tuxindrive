"""Private bounded SQLite storage for opaque TuxInDrive server data."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class ServerStoreError(RuntimeError):
    pass


class ServerStore:
    def __init__(self, path: Path, quota_bytes: int = 512 * 1024 * 1024) -> None:
        self.path = path
        self.quota_bytes = max(1024 * 1024, int(quota_bytes))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS mailbox (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, recipient TEXT NOT NULL,
              body BLOB NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL,
              UNIQUE(tenant, recipient, id)
            );
            CREATE INDEX IF NOT EXISTS mailbox_recipient ON mailbox(tenant, recipient, created);
            CREATE TABLE IF NOT EXISTS objects (
              digest TEXT NOT NULL, tenant TEXT NOT NULL, body BLOB NOT NULL,
              created INTEGER NOT NULL, expires INTEGER NOT NULL,
              PRIMARY KEY(tenant, digest)
            );
            CREATE INDEX IF NOT EXISTS objects_tenant ON objects(tenant, created);
            CREATE TABLE IF NOT EXISTS rendezvous (
              tenant TEXT NOT NULL, device TEXT NOT NULL, envelope BLOB NOT NULL,
              created INTEGER NOT NULL, expires INTEGER NOT NULL,
              PRIMARY KEY(tenant, device)
            );
            CREATE TABLE IF NOT EXISTS collaboration (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, workspace TEXT NOT NULL,
              body BLOB NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS collaboration_workspace ON collaboration(tenant, workspace, created);
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created INTEGER NOT NULL,
              tenant TEXT NOT NULL, action TEXT NOT NULL, result TEXT NOT NULL,
              detail TEXT NOT NULL
            );
            """
        )
        self._connection.commit()
        os.chmod(self.path, 0o600)

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        value = str(value or "").strip()
        if not value or len(value) > 128 or not all(char.isalnum() or char in "-_.:@" for char in value):
            raise ServerStoreError(f"Invalid {label}")
        return value

    @staticmethod
    def _expiry(ttl_seconds: int, maximum: int = 30 * 24 * 3600) -> tuple[int, int]:
        now = int(time.time())
        ttl = max(60, min(maximum, int(ttl_seconds)))
        return now, now + ttl

    def _used(self, tenant: str) -> int:
        row = self._connection.execute(
            """SELECT
              COALESCE((SELECT SUM(length(body)) FROM mailbox WHERE tenant=?),0) +
              COALESCE((SELECT SUM(length(body)) FROM objects WHERE tenant=?),0) +
              COALESCE((SELECT SUM(length(envelope)) FROM rendezvous WHERE tenant=?),0) +
              COALESCE((SELECT SUM(length(body)) FROM collaboration WHERE tenant=?),0)
            """, (tenant, tenant, tenant, tenant),
        ).fetchone()
        return int(row[0] or 0)

    def _reserve(self, tenant: str, size: int) -> None:
        if size < 0 or size > self.quota_bytes or self._used(tenant) + size > self.quota_bytes:
            raise ServerStoreError("Tenant storage quota exceeded")

    def purge(self) -> int:
        now = int(time.time())
        removed = 0
        with self._lock:
            for table in ("mailbox", "objects", "rendezvous", "collaboration"):
                cursor = self._connection.execute(f"DELETE FROM {table} WHERE expires <= ?", (now,))
                removed += cursor.rowcount
            self._connection.commit()
        return removed

    def put_mail(self, tenant: str, recipient: str, body: bytes, ttl: int) -> dict:
        tenant = self._identifier(tenant, "tenant")
        recipient = self._identifier(recipient, "recipient")
        now, expires = self._expiry(ttl, 7 * 24 * 3600)
        item_id = uuid.uuid4().hex
        with self._lock:
            self.purge(); self._reserve(tenant, len(body))
            self._connection.execute(
                "INSERT INTO mailbox VALUES(?,?,?,?,?,?)",
                (item_id, tenant, recipient, sqlite3.Binary(body), now, expires),
            )
            self._connection.commit()
        return {"id": item_id, "created": now, "expires": expires, "bytes": len(body)}

    def list_mail(self, tenant: str, recipient: str, limit: int = 100) -> list[dict]:
        tenant = self._identifier(tenant, "tenant"); recipient = self._identifier(recipient, "recipient")
        with self._lock:
            self.purge()
            rows = self._connection.execute(
                "SELECT id,body,created,expires FROM mailbox WHERE tenant=? AND recipient=? ORDER BY created,id LIMIT ?",
                (tenant, recipient, max(1, min(100, int(limit)))),
            ).fetchall()
        return [{"id": row[0], "body": bytes(row[1]), "created": row[2], "expires": row[3]} for row in rows]

    def acknowledge_mail(self, tenant: str, recipient: str, item_id: str) -> bool:
        tenant = self._identifier(tenant, "tenant"); recipient = self._identifier(recipient, "recipient")
        item_id = self._identifier(item_id, "message ID")
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM mailbox WHERE tenant=? AND recipient=? AND id=?", (tenant, recipient, item_id)
            )
            self._connection.commit()
        return cursor.rowcount == 1

    def put_object(self, tenant: str, body: bytes, ttl: int) -> dict:
        tenant = self._identifier(tenant, "tenant")
        digest = hashlib.sha256(body).hexdigest()
        now, expires = self._expiry(ttl)
        with self._lock:
            self.purge()
            existing = self._connection.execute(
                "SELECT length(body),expires FROM objects WHERE tenant=? AND digest=?",
                (tenant, digest),
            ).fetchone()
            if existing:
                return {"digest": digest, "bytes": existing[0], "expires": existing[1], "existing": True}
            self._reserve(tenant, len(body))
            self._connection.execute("INSERT INTO objects VALUES(?,?,?,?,?)", (digest, tenant, sqlite3.Binary(body), now, expires))
            self._connection.commit()
        return {"digest": digest, "bytes": len(body), "expires": expires, "existing": False}

    def get_object(self, tenant: str, digest: str) -> bytes | None:
        tenant = self._identifier(tenant, "tenant")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ServerStoreError("Invalid object digest")
        with self._lock:
            self.purge()
            row = self._connection.execute("SELECT body FROM objects WHERE tenant=? AND digest=?", (tenant, digest)).fetchone()
        return bytes(row[0]) if row else None

    def put_rendezvous(self, tenant: str, device: str, envelope: bytes, ttl: int) -> dict:
        tenant = self._identifier(tenant, "tenant"); device = self._identifier(device, "device")
        now, expires = self._expiry(ttl, 24 * 3600)
        with self._lock:
            self.purge()
            prior = self._connection.execute("SELECT length(envelope) FROM rendezvous WHERE tenant=? AND device=?", (tenant, device)).fetchone()
            self._reserve(tenant, max(0, len(envelope) - int(prior[0] if prior else 0)))
            self._connection.execute(
                "INSERT INTO rendezvous VALUES(?,?,?,?,?) ON CONFLICT(tenant,device) DO UPDATE SET envelope=excluded.envelope,created=excluded.created,expires=excluded.expires",
                (tenant, device, sqlite3.Binary(envelope), now, expires),
            )
            self._connection.commit()
        return {"device": device, "created": now, "expires": expires}

    def get_rendezvous(self, tenant: str, device: str) -> bytes | None:
        tenant = self._identifier(tenant, "tenant"); device = self._identifier(device, "device")
        with self._lock:
            self.purge()
            row = self._connection.execute("SELECT envelope FROM rendezvous WHERE tenant=? AND device=?", (tenant, device)).fetchone()
        return bytes(row[0]) if row else None

    def put_collaboration(self, tenant: str, workspace: str, body: bytes, ttl: int) -> dict:
        tenant = self._identifier(tenant, "tenant"); workspace = self._identifier(workspace, "workspace")
        item_id = uuid.uuid4().hex; now, expires = self._expiry(ttl, 30 * 24 * 3600)
        with self._lock:
            self.purge(); self._reserve(tenant, len(body))
            self._connection.execute("INSERT INTO collaboration VALUES(?,?,?,?,?,?)", (item_id, tenant, workspace, sqlite3.Binary(body), now, expires))
            self._connection.commit()
        return {"id": item_id, "created": now, "expires": expires, "bytes": len(body)}

    def list_collaboration(self, tenant: str, workspace: str, after: int = 0, limit: int = 100) -> list[dict]:
        tenant = self._identifier(tenant, "tenant"); workspace = self._identifier(workspace, "workspace")
        with self._lock:
            self.purge()
            rows = self._connection.execute(
                "SELECT id,body,created,expires FROM collaboration WHERE tenant=? AND workspace=? AND created>=? ORDER BY created,id LIMIT ?",
                (tenant, workspace, max(0, int(after)), max(1, min(100, int(limit)))),
            ).fetchall()
        return [{"id": row[0], "body": bytes(row[1]), "created": row[2], "expires": row[3]} for row in rows]

    def audit(self, tenant: str, action: str, result: str, detail: str = "") -> None:
        tenant = self._identifier(tenant, "tenant")
        safe_detail = str(detail).replace("\n", " ")[:512]
        with self._lock:
            self._connection.execute(
                "INSERT INTO audit(created,tenant,action,result,detail) VALUES(?,?,?,?,?)",
                (int(time.time()), tenant, str(action)[:64], str(result)[:32], safe_detail),
            )
            self._connection.execute(
                "DELETE FROM audit WHERE tenant=? AND id NOT IN (SELECT id FROM audit WHERE tenant=? ORDER BY id DESC LIMIT 1000)",
                (tenant, tenant),
            )
            self._connection.commit()

    def recent_audit(self, tenant: str, limit: int = 100) -> list[dict]:
        tenant = self._identifier(tenant, "tenant")
        with self._lock:
            rows = self._connection.execute(
                "SELECT created,tenant,action,result,detail FROM audit WHERE tenant=? ORDER BY id DESC LIMIT ?",
                (tenant, max(1, min(500, int(limit)))),
            ).fetchall()
        return [dict(zip(("created", "tenant", "action", "result", "detail"), row)) for row in rows]

    def stats(self, tenant: str) -> dict:
        tenant = self._identifier(tenant, "tenant")
        with self._lock:
            self.purge()
            result = {}
            for table in ("mailbox", "objects", "rendezvous", "collaboration"):
                count, size = self._connection.execute(
                    f"SELECT COUNT(*),COALESCE(SUM(length({'envelope' if table == 'rendezvous' else 'body'})),0) FROM {table} WHERE tenant=?",
                    (tenant,),
                ).fetchone()
                result[table] = {"items": int(count), "bytes": int(size)}
            return result

    def close(self) -> None:
        with self._lock:
            self._connection.close()
