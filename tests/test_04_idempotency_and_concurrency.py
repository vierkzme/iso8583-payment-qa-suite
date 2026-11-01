"""
Category 4: Idempotency, Concurrency, and SQL Audit Test Scenarios.
Validates duplicate request rejection (RC 94), multi-threaded anti-double-debit protection,
race-condition overdraft prevention, and verification of standalone SQL reconciliation scripts.
"""

import os
import threading
from typing import List

from src.iso8583_models import (
    ISO8583Message,
    MTI_FINANCIAL_REQUEST,
    MTI_FINANCIAL_RESPONSE,
    PROC_PURCHASE,
    PROC_WITHDRAWAL,
    RC_APPROVED,
    RC_INSUFFICIENT_FUNDS,
    RC_DUPLICATE_TRANSMISSION,
)
from tests.base_test import BasePaymentTestCase


class TestIdempotencyAndConcurrencyScenarios(BasePaymentTestCase):
    """
    SIT Test Cases for Idempotency, High-Concurrency Race Conditions, and SQL Reconciliation.
    """

    def test_SIT_IDM_001_sequential_duplicate_transaction(self):
        """
        SIT-IDM-001: Sequential Duplicate Transmission (RC 94).
        Sends two identical 0200 requests with identical STAN & RRN sequentially.
        First request: Approved (RC 00), balance debited by 100,000.
        Second request: Duplicate Transmission (RC 94), balance NOT debited again.
        """
        stan = "000401"
        rrn = "202611010041"
        amount = 100000

        req1 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_IDM_01",
            expiry_date="2812",
            pin="1234",
        )
        res1 = self.switch.process_message(req1)
        self.assertEqual(res1.response_code, RC_APPROVED)
        self.assert_balance(self.card_active, 900000)

        # Duplicate request
        req2 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_IDM_01",
            expiry_date="2812",
            pin="1234",
        )
        res2 = self.switch.process_message(req2)
        self.assertEqual(res2.response_code, RC_DUPLICATE_TRANSMISSION)

        # Prove zero double debit in SQL
        self.assert_balance(self.card_active, 900000)
        self.assert_daily_accumulated(self.card_active, 100000)

        # Confirm DUPLICATE_REJECTED logged
        txs = self.db.execute_query(
            "SELECT status, response_code FROM transaction_logs WHERE stan = ? AND rrn = ? ORDER BY id ASC",
            (stan, rrn),
        )
        self.assertEqual(len(txs), 2)
        self.assertEqual(txs[0]["status"], "APPROVED")
        self.assertEqual(txs[0]["response_code"], RC_APPROVED)
        self.assertEqual(txs[1]["status"], "DUPLICATE_REJECTED")
        self.assertEqual(txs[1]["response_code"], RC_DUPLICATE_TRANSMISSION)

    def test_SIT_IDM_002_concurrent_duplicate_burst(self):
        """
        SIT-IDM-002: Concurrent Duplicate Burst (10 Simultaneous Threads).
        Fires 10 threads concurrently sending the exact same STAN & RRN.
        Expected: Exactly 1 thread gets Approved (RC 00), 9 threads receive Duplicate (RC 94).
        Balance is debited exactly once (900,000, NOT lower).
        """
        stan = "000402"
        rrn = "202611010042"
        amount = 100000
        thread_count = 10

        results: List[ISO8583Message] = []
        threads: List[threading.Thread] = []
        barrier = threading.Barrier(thread_count)

        def worker():
            msg = ISO8583Message(
                mti=MTI_FINANCIAL_REQUEST,
                pan=self.card_active,
                processing_code=PROC_PURCHASE,
                amount=amount,
                stan=stan,
                rrn=rrn,
                terminal_id="POS_BURST_01",
                expiry_date="2812",
                pin="1234",
            )
            barrier.wait()  # Synchronize thread launch
            res = self.switch.process_message(msg)
            results.append(res)

        for _ in range(thread_count):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Count response codes
        approved_count = sum(1 for r in results if r.response_code == RC_APPROVED)
        duplicate_count = sum(1 for r in results if r.response_code == RC_DUPLICATE_TRANSMISSION)

        self.assertEqual(approved_count, 1, f"Expected exactly 1 approval, got {approved_count}")
        self.assertEqual(duplicate_count, 9, f"Expected 9 duplicate rejections, got {duplicate_count}")

        # SQL balance verification: Debited exactly once
        self.assert_balance(self.card_active, 900000)
        self.assert_daily_accumulated(self.card_active, 100000)

    def test_SIT_IDM_003_concurrent_balance_exhaustion_no_overdraft(self):
        """
        SIT-IDM-003: High-Concurrency Balance Exhaustion (Anti-Race Condition).
        Initial Balance: 50,000.
        5 simultaneous threads each attempt to withdraw 20,000 (Total attempted: 100,000).
        Each thread has a unique STAN/RRN.
        Expected: Exactly 2 transactions succeed (2 * 20,000 = 40,000), leaving 10,000.
        The other 3 transactions are declined with RC 51 (Insufficient Funds).
        Card balance never drops below zero and no race condition overdraft occurs.
        """
        thread_count = 5
        amount_per_tx = 20000

        results: List[ISO8583Message] = []
        threads: List[threading.Thread] = []
        barrier = threading.Barrier(thread_count)

        def worker(idx: int):
            msg = ISO8583Message(
                mti=MTI_FINANCIAL_REQUEST,
                pan=self.card_low_balance,
                processing_code=PROC_WITHDRAWAL,
                amount=amount_per_tx,
                stan=f"00041{idx}",
                rrn=f"20261101005{idx}",
                terminal_id=f"ATM_RACE_{idx}",
                expiry_date="2812",
                pin="5678",
            )
            barrier.wait()
            res = self.switch.process_message(msg)
            results.append(res)

        for i in range(thread_count):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        approved_count = sum(1 for r in results if r.response_code == RC_APPROVED)
        insufficient_count = sum(1 for r in results if r.response_code == RC_INSUFFICIENT_FUNDS)

        self.assertEqual(approved_count, 2, f"Expected exactly 2 approvals, got {approved_count}")
        self.assertEqual(insufficient_count, 3, f"Expected 3 insufficient funds declines, got {insufficient_count}")

        # Final balance must be 50,000 - 40,000 = 10,000
        self.assert_balance(self.card_low_balance, 10000)
        self.assert_daily_accumulated(self.card_low_balance, 40000)

    def test_SIT_IDM_004_sql_audit_and_reconciliation_scripts(self):
        """
        SIT-IDM-004: Validation of Standalone SQL QA Scripts.
        Executes all 4 standalone SQL scripts against active and simulated anomaly conditions:
        1. 01_detect_double_debits.sql
        2. 02_find_orphan_reversals.sql
        3. 03_audit_unsettled_timeouts.sql
        4. 04_daily_ledger_reconciliation.sql
        """
        sql_dir = os.path.join(os.path.dirname(__file__), "..", "sql")

        def read_sql(filename: str) -> str:
            path = os.path.join(sql_dir, filename)
            with open(path, "r", encoding="utf-8") as f:
                return f.read()

        # Step 1: Clean transactions on card_active
        # Normal purchase 100,000
        self.switch.process_message(
            ISO8583Message(
                mti=MTI_FINANCIAL_REQUEST,
                pan=self.card_active,
                amount=100000,
                stan="000491",
                rrn="202611010091",
                expiry_date="2812",
                pin="1234",
            )
        )
        # Timeout and reversed purchase 50,000
        self.switch.process_message(
            ISO8583Message(
                mti=MTI_FINANCIAL_REQUEST,
                pan=self.card_active,
                amount=50000,
                stan="000492",
                rrn="202611010092",
                expiry_date="2812",
                pin="1234",
                simulate_timeout=True,
            )
        )
        self.switch.process_message(
            ISO8583Message(
                mti="0400",
                pan=self.card_active,
                amount=50000,
                stan="000492",
                rrn="202611010092",
            )
        )

        # Audit 1: No double debits on clean system
        sql_01 = read_sql("01_detect_double_debits.sql")
        rows_01 = self.db.execute_query(sql_01)
        self.assertEqual(len(rows_01), 0, "Clean switch should have zero double-debit anomalies")

        # Audit 2: Orphan reversal audit (send orphan reversal attempt)
        self.switch.process_message(
            ISO8583Message(
                mti="0400",
                pan=self.card_active,
                amount=25000,
                stan="000499",
                rrn="202611010099",
            )
        )
        sql_02 = read_sql("02_find_orphan_reversals.sql")
        rows_02 = self.db.execute_query(sql_02)
        self.assertGreaterEqual(len(rows_02), 1)
        self.assertEqual(rows_02[0]["stan"], "000499")

        # Audit 3: Unsettled timeout audit (send unsettled timeout without 0400 reversal)
        self.switch.process_message(
            ISO8583Message(
                mti=MTI_FINANCIAL_REQUEST,
                pan=self.card_active,
                amount=30000,
                stan="000493",
                rrn="202611010093",
                expiry_date="2812",
                pin="1234",
                simulate_timeout=True,
            )
        )
        sql_03 = read_sql("03_audit_unsettled_timeouts.sql")
        rows_03 = self.db.execute_query(sql_03)
        self.assertEqual(len(rows_03), 1)
        self.assertEqual(rows_03[0]["stan"], "000493")
        self.assertEqual(rows_03[0]["status"], "TIMEOUT_SUSPECT")

        # Audit 4: Daily ledger reconciliation must report BALANCED for all accounts
        sql_04 = read_sql("04_daily_ledger_reconciliation.sql")
        rows_04 = self.db.execute_query(sql_04)
        self.assertGreaterEqual(len(rows_04), 4)
        for r in rows_04:
            self.assertEqual(
                r["reconciliation_status"],
                "BALANCED",
                f"Ledger discrepancy on PAN {r['pan']}: Diff={r['discrepancy_amount']}"
            )
