"""
CLI Runner for SQL QA and Payment Reconciliation Audits.
Simulates a day of payment switching operations and executes the 4 SQL audit queries.
"""

import os
import sys

# Ensure src is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database import DatabaseManager
from src.iso8583_models import (
    ISO8583Message,
    MTI_FINANCIAL_REQUEST,
    MTI_REVERSAL_REQUEST,
    PROC_PURCHASE,
    PROC_WITHDRAWAL,
)
from src.payment_switch import PaymentSwitchSimulator


def print_table(title: str, rows: list, empty_message: str = "No records found (Clean)."):
    print("\n" + "=" * 90)
    print(f" {title.upper()}")
    print("=" * 90)
    if not rows:
        print(f"  [STATUS: OK] {empty_message}\n")
        return

    # Print keys as header
    headers = list(rows[0].keys())
    header_str = " | ".join(f"{h:<20}" for h in headers)
    print(header_str)
    print("-" * len(header_str))

    for row in rows:
        line = " | ".join(f"{str(row[h]):<20}" for h in headers)
        print(line)
    print("=" * 90 + "\n")


def main():
    print("\n" + "#" * 90)
    print("  ISO 8583 PAYMENT SWITCHING SIMULATOR - SQL AUDIT & RECONCILIATION RUNNER")
    print("#" * 90)

    db = DatabaseManager(":memory:")
    db.seed_default_accounts()
    switch = PaymentSwitchSimulator(db, reference_date_yymm="2411")

    print("\n[*] Simulating real-world payment switching operations...")

    # 1. Normal Approved POS Purchase (Card 1)
    switch.process_message(
        ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan="4000123456780001",
            processing_code=PROC_PURCHASE,
            amount=150000,
            stan="100001",
            rrn="202611019001",
            terminal_id="POS_CENTRAL",
            expiry_date="2812",
            pin="1234",
        )
    )

    # 2. Normal Approved ATM Withdrawal (Card 1)
    switch.process_message(
        ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan="4000123456780001",
            processing_code=PROC_WITHDRAWAL,
            amount=200000,
            stan="100002",
            rrn="202611019002",
            terminal_id="ATM_BRANCH_1",
            expiry_date="2812",
            pin="1234",
        )
    )

    # 3. Timeout Suspect Transaction followed by Auto-Reversal (Card 1)
    switch.process_message(
        ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan="4000123456780001",
            amount=100000,
            stan="100003",
            rrn="202611019003",
            expiry_date="2812",
            pin="1234",
            simulate_timeout=True,
        )
    )
    switch.process_message(
        ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan="4000123456780001",
            amount=100000,
            stan="100003",
            rrn="202611019003",
        )
    )

    # 4. Duplicate Transmission Attempt (Card 1)
    switch.process_message(
        ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan="4000123456780001",
            amount=150000,
            stan="100001",
            rrn="202611019001",
            expiry_date="2812",
            pin="1234",
        )
    )

    # 5. Orphan Reversal Attempt (Non-existent transaction)
    switch.process_message(
        ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan="4000123456780002",
            amount=50000,
            stan="999001",
            rrn="999001999001",
        )
    )

    # 6. Unsettled Timeout Suspect Transaction (Card 4)
    switch.process_message(
        ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan="4000123456780004",
            amount=45000,
            stan="100004",
            rrn="202611019004",
            expiry_date="2812",
            pin="1111",
            simulate_timeout=True,
        )
    )

    print("[+] Simulation complete. Executing SQL audit reports...\n")

    sql_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sql"))

    def run_query(filename: str):
        path = os.path.join(sql_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            query = f.read()
        return db.execute_query(query)

    # Audit 1: Double-Debit Anomaly Detection
    res_01 = run_query("01_detect_double_debits.sql")
    print_table(
        "Audit 1: Double-Debit Anomaly Detection (01_detect_double_debits.sql)",
        res_01,
        empty_message="No double debits detected. Idempotency protection fully intact."
    )

    # Audit 2: Orphan Reversals Audit
    res_02 = run_query("02_find_orphan_reversals.sql")
    print_table(
        "Audit 2: Orphan Reversals Audit (02_find_orphan_reversals.sql)",
        res_02,
        empty_message="No orphan reversals detected."
    )

    # Audit 3: Unsettled Timeout Audit
    res_03 = run_query("03_audit_unsettled_timeouts.sql")
    print_table(
        "Audit 3: Unsettled Timeout / Suspect Transactions (03_audit_unsettled_timeouts.sql)",
        res_03,
        empty_message="No unsettled timeout transactions."
    )

    # Audit 4: Daily Ledger Reconciliation
    res_04 = run_query("04_daily_ledger_reconciliation.sql")
    print_table(
        "Audit 4: Daily Ledger Reconciliation (04_daily_ledger_reconciliation.sql)",
        res_04,
        empty_message="No card accounts found."
    )

    db.close()


if __name__ == "__main__":
    main()
