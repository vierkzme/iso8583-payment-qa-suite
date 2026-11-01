"""
Database Management and Schema Setup for Payment Switching Simulator.
Provides thread-safe SQLite connection handling, schema migration, and test account seeding.
"""

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS card_accounts (
    pan TEXT PRIMARY KEY,
    cardholder_name TEXT NOT NULL,
    pin TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    initial_balance INTEGER NOT NULL,
    balance INTEGER NOT NULL CHECK (balance >= 0),
    daily_limit INTEGER NOT NULL,
    daily_accumulated INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transaction_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mti TEXT NOT NULL,
    response_mti TEXT NOT NULL,
    pan TEXT NOT NULL,
    processing_code TEXT NOT NULL,
    amount INTEGER NOT NULL,
    stan TEXT NOT NULL,
    rrn TEXT NOT NULL,
    terminal_id TEXT NOT NULL,
    response_code TEXT NOT NULL,
    status TEXT NOT NULL,
    original_tx_id INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (original_tx_id) REFERENCES transaction_logs(id)
);

CREATE INDEX IF NOT EXISTS idx_tx_stan_rrn ON transaction_logs(stan, rrn);
CREATE INDEX IF NOT EXISTS idx_tx_pan ON transaction_logs(pan);
CREATE INDEX IF NOT EXISTS idx_tx_status ON transaction_logs(status);
"""

DEFAULT_CARDS: List[Dict[str, Any]] = [
    {
        "pan": "4000123456780001",
        "cardholder_name": "JOHN DOE",
        "pin": "1234",
        "expiry_date": "2812",       # Valid until Dec 2028
        "initial_balance": 1000000,   # IDR / Cents 1,000,000
        "balance": 1000000,
        "daily_limit": 5000000,
        "daily_accumulated": 0,
        "status": "ACTIVE",
    },
    {
        "pan": "4000123456780002",
        "cardholder_name": "JANE SMITH",
        "pin": "5678",
        "expiry_date": "2812",       # Valid until Dec 2028
        "initial_balance": 50000,     # Low balance (50,000)
        "balance": 50000,
        "daily_limit": 2000000,
        "daily_accumulated": 0,
        "status": "ACTIVE",
    },
    {
        "pan": "4000123456780003",
        "cardholder_name": "ALICE WONDER",
        "pin": "9999",
        "expiry_date": "2101",       # Expired (Jan 2021)
        "initial_balance": 500000,
        "balance": 500000,
        "daily_limit": 2000000,
        "daily_accumulated": 0,
        "status": "ACTIVE",
    },
    {
        "pan": "4000123456780004",
        "cardholder_name": "BOB BUILDER",
        "pin": "1111",
        "expiry_date": "2812",       # Valid
        "initial_balance": 1000000,
        "balance": 1000000,
        "daily_limit": 100000,       # Strict daily limit (100,000)
        "daily_accumulated": 0,
        "status": "ACTIVE",
    },
]


class DatabaseManager:
    """
    Manages database connections, table creation, seed data, and atomic transaction execution.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None  # Enable explicit transaction control
        )
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def get_lock(self) -> threading.RLock:
        """Return the database mutex lock for concurrency synchronization."""
        return self._lock

    def init_schema(self) -> None:
        """Initialize database schema tables and indexes."""
        with self._lock:
            with self.conn:
                self.conn.executescript(SCHEMA_SQL)

    def seed_default_accounts(self) -> None:
        """Insert or replace initial test card accounts."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self.conn:
                for card in DEFAULT_CARDS:
                    self.conn.execute(
                        """
                        INSERT OR REPLACE INTO card_accounts (
                            pan, cardholder_name, pin, expiry_date,
                            initial_balance, balance, daily_limit,
                            daily_accumulated, status, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            card["pan"],
                            card["cardholder_name"],
                            card["pin"],
                            card["expiry_date"],
                            card["initial_balance"],
                            card["balance"],
                            card["daily_limit"],
                            card["daily_accumulated"],
                            card["status"],
                            now,
                            now,
                        )
                    )

    def get_card(self, pan: str) -> Optional[sqlite3.Row]:
        """Fetch card account by PAN."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM card_accounts WHERE pan = ?", (pan,))
            return cur.fetchone()

    def get_transaction_by_stan_rrn(self, stan: str, rrn: str, mti: Optional[str] = None) -> Optional[sqlite3.Row]:
        """Fetch transaction by STAN and RRN, optionally filtering by MTI."""
        with self._lock:
            cur = self.conn.cursor()
            if mti:
                cur.execute(
                    "SELECT * FROM transaction_logs WHERE stan = ? AND rrn = ? AND mti = ? ORDER BY id DESC LIMIT 1",
                    (stan, rrn, mti),
                )
            else:
                cur.execute(
                    "SELECT * FROM transaction_logs WHERE stan = ? AND rrn = ? ORDER BY id DESC LIMIT 1",
                    (stan, rrn),
                )
            return cur.fetchone()

    def get_transaction_by_id(self, tx_id: int) -> Optional[sqlite3.Row]:
        """Fetch transaction by primary key ID."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM transaction_logs WHERE id = ?", (tx_id,))
            return cur.fetchone()

    def get_all_transactions(self) -> List[sqlite3.Row]:
        """Retrieve all transaction logs ordered by ID."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM transaction_logs ORDER BY id ASC")
            return cur.fetchall()

    def execute_query(self, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
        """Execute custom SQL read query and return rows."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(sql, params)
            return cur.fetchall()

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            try:
                self.conn.close()
            except Exception:
                pass
