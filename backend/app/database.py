import aiosqlite
import os
import logging

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: aiosqlite.Connection = None  # type: ignore

    async def initialize(self):
        """Create the database and tables if they don't exist."""
        # Ensure the directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            try:
                os.makedirs(db_dir, exist_ok=True)
            except OSError:
                pass

        try:
            self._conn = await aiosqlite.connect(self.db_path)
        except Exception:
            # Fallback to /tmp if current dir is read-only (e.g. serverless)
            fallback = "/tmp/app.db"
            os.makedirs("/tmp", exist_ok=True)
            self._conn = await aiosqlite.connect(fallback)
        self._conn.row_factory = aiosqlite.Row

        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT NOT NULL,
                metadata    TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        await self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_id
            ON messages(session_id)
        """)
        await self._conn.commit()
        logger.info(f"Database initialized at {self.db_path}")

    async def health_check(self):
        """Check that the database is reachable."""
        async with self._conn.execute("SELECT 1") as cursor:
            await cursor.fetchone()

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: str | None,
        created_at: str,
    ):
        """Insert a message into the messages table."""
        await self._conn.execute(
            """
            INSERT INTO messages (session_id, role, content, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, metadata, created_at),
        )
        await self._conn.commit()

    async def get_messages(self, session_id: str) -> list[dict]:
        """Retrieve all messages for a session, oldest first."""
        async with self._conn.execute(
            """
            SELECT role, content, metadata, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "role": row["role"],
                    "content": row["content"],
                    "metadata": row["metadata"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    async def close(self):
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
