"""
Base Test Fixture and Database Assertions for Payment QA Suite.
Provides isolated in-memory database setup, seeding, and SQL validation helpers.
"""

import unittest
from typing import Optional

from src.database import DatabaseManager, DEFAULT_CARDS
from src.payment_switch import PaymentSwitchSimulator


class BasePaymentTestCase(unittest.TestCase):
    """
    Base test fixture configuring an isolated in-memory SQLite database for each test.
    """

    def setUp(self):
        # Create fresh in-memory database instance
        self.db = DatabaseManager(":memory:")
        self.db.seed_default_accounts()
        # Reference date set to November 2024 ('2411')
        self.switch = PaymentSwitchSimulator(self.db, reference_date_yymm="2411")

        # Standard test card credentials
        self.card_active = DEFAULT_CARDS[0]["pan"]          # 4000123456780001 (Bal: 1,000,000, PIN: 1234, Exp: 2812)
        self.card_low_balance = DEFAULT_CARDS[1]["pan"]     # 4000123456780002 (Bal: 50,000, PIN: 5678, Exp: 2812)
        self.card_expired = DEFAULT_CARDS[2]["pan"]         # 4000123456780003 (Bal: 500,000, PIN: 9999, Exp: 2101)
        self.card_low_limit = DEFAULT_CARDS[3]["pan"]       # 4000123456780004 (Bal: 1,000,000, PIN: 1111, Exp: 2812, Limit: 100,000)

    def tearDown(self):
        self.db.close()

    # --- SQL QA Assertion Helpers ---

    def assert_balance(self, pan: str, expected_balance: int):
        """Verify directly in SQL that the card balance equals expected amount."""
        card = self.db.get_card(pan)
        self.assertIsNotNone(card, f"Card {pan} not found in database")
        self.assertEqual(
            card["balance"],
            expected_balance,
            f"Balance mismatch for card {pan}. Expected {expected_balance}, got {card['balance']}"
        )

    def assert_daily_accumulated(self, pan: str, expected_accumulated: int):
        """Verify directly in SQL that the daily accumulated total matches expected."""
        card = self.db.get_card(pan)
        self.assertIsNotNone(card, f"Card {pan} not found in database")
        self.assertEqual(
            card["daily_accumulated"],
            expected_accumulated,
            f"Daily accumulated mismatch for card {pan}. Expected {expected_accumulated}, got {card['daily_accumulated']}"
        )

    def assert_transaction_logged(
        self,
        stan: str,
        rrn: str,
        expected_status: str,
        expected_rc: str,
        mti: Optional[str] = None
    ):
        """Verify transaction record audit trail in SQL database."""
        tx = self.db.get_transaction_by_stan_rrn(stan, rrn, mti)
        self.assertIsNotNone(
            tx,
            f"Transaction with STAN={stan}, RRN={rrn}, MTI={mti} not found in transaction_logs"
        )
        self.assertEqual(
            tx["status"],
            expected_status,
            f"Transaction status mismatch. Expected {expected_status}, got {tx['status']}"
        )
        self.assertEqual(
            tx["response_code"],
            expected_rc,
            f"Transaction response_code mismatch. Expected {expected_rc}, got {tx['response_code']}"
        )
