"""
Category 3: Timeout and Auto-Reversal Test Scenarios.
Validates network timeout handling (RC 68, TIMEOUT_SUSPECT), auto-reversals (MTI 0400 -> 0410),
100% balance restoration, orphan reversal rejection (RC 25), and duplicate reversal guards (RC 94).
"""

from src.iso8583_models import (
    ISO8583Message,
    MTI_FINANCIAL_REQUEST,
    MTI_FINANCIAL_RESPONSE,
    MTI_REVERSAL_REQUEST,
    MTI_REVERSAL_RESPONSE,
    PROC_PURCHASE,
    PROC_WITHDRAWAL,
    RC_APPROVED,
    RC_UNABLE_TO_LOCATE_RECORD,
    RC_RESPONSE_RECEIVED_TOO_LATE,
    RC_DUPLICATE_TRANSMISSION,
)
from tests.base_test import BasePaymentTestCase


class TestTimeoutAndReversalScenarios(BasePaymentTestCase):
    """
    SIT Test Cases for Network Drop Timeouts and Reversal Processing.
    """

    def test_SIT_REV_001_timeout_and_auto_reversal(self):
        """
        SIT-REV-001: Timeout Suspect (RC 68) followed by Automated Reversal (0400 -> 0410 RC 00).
        Scenario:
        1. Terminal sends 0200 Purchase of 100,000.
        2. Switch encounters timeout: balance debited from 1,000,000 to 900,000, status TIMEOUT_SUSPECT.
        3. Terminal automatically fires 0400 Reversal with matching STAN & RRN.
        4. Switch validates original suspect tx, refunds balance back to 1,000,000, sets status REVERSED.
        """
        stan = "000301"
        rrn = "202611010031"
        amount = 100000

        # Step 1: Simulate Financial Request with Network Timeout
        req_0200 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_AIRPORT_1",
            expiry_date="2812",
            pin="1234",
            simulate_timeout=True,
        )

        res_0200 = self.switch.process_message(req_0200)

        # Assert Step 1: Switch returned RC 68 and debited balance in suspect state
        self.assertEqual(res_0200.mti, MTI_FINANCIAL_RESPONSE)
        self.assertEqual(res_0200.response_code, RC_RESPONSE_RECEIVED_TOO_LATE)
        self.assert_balance(self.card_active, 900000)
        self.assert_daily_accumulated(self.card_active, 100000)
        self.assert_transaction_logged(
            stan=stan,
            rrn=rrn,
            expected_status="TIMEOUT_SUSPECT",
            expected_rc=RC_RESPONSE_RECEIVED_TOO_LATE,
            mti=MTI_FINANCIAL_REQUEST,
        )

        # Step 2: Dispatch 0400 Auto-Reversal
        req_0400 = ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_AIRPORT_1",
        )

        res_0400 = self.switch.process_message(req_0400)

        # Assert Step 2: Reversal approved, balance 100% restored to 1,000,000
        self.assertEqual(res_0400.mti, MTI_REVERSAL_RESPONSE)
        self.assertEqual(res_0400.response_code, RC_APPROVED)
        self.assert_balance(self.card_active, 1000000)
        self.assert_daily_accumulated(self.card_active, 0)

        # SQL Audit Verification: Original record must now be REVERSED
        orig_tx = self.db.get_transaction_by_stan_rrn(stan, rrn, MTI_FINANCIAL_REQUEST)
        self.assertIsNotNone(orig_tx)
        self.assertEqual(orig_tx["status"], "REVERSED")

        # 0400 record must be logged as APPROVED
        rev_tx = self.db.get_transaction_by_stan_rrn(stan, rrn, MTI_REVERSAL_REQUEST)
        self.assertIsNotNone(rev_tx)
        self.assertEqual(rev_tx["status"], "APPROVED")
        self.assertEqual(rev_tx["original_tx_id"], orig_tx["id"])

    def test_SIT_REV_002_orphan_reversal_rejected(self):
        """
        SIT-REV-002: Orphan Reversal Attempt (RC 25).
        Terminal issues an 0400 reversal for a STAN/RRN that does not exist in the database.
        Expected: RC 25 (Unable to locate record), Balance untouched, status ORPHAN_REJECTED.
        """
        initial_balance = 1000000
        stan = "999999"
        rrn = "999999999999"

        req_orphan = ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=50000,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_ORPHAN",
        )

        res_orphan = self.switch.process_message(req_orphan)

        self.assertEqual(res_orphan.mti, MTI_REVERSAL_RESPONSE)
        self.assertEqual(res_orphan.response_code, RC_UNABLE_TO_LOCATE_RECORD)

        # Ensure balance was not erroneously credited
        self.assert_balance(self.card_active, initial_balance)
        self.assert_daily_accumulated(self.card_active, 0)
        self.assert_transaction_logged(
            stan=stan,
            rrn=rrn,
            expected_status="ORPHAN_REJECTED",
            expected_rc=RC_UNABLE_TO_LOCATE_RECORD,
            mti=MTI_REVERSAL_REQUEST,
        )

    def test_SIT_REV_003_reversal_of_declined_transaction_rejected(self):
        """
        SIT-REV-003: Reversal of a Declined Transaction Rejected (RC 25).
        Attempts to reverse a transaction that was previously DECLINED (never debited).
        Expected: RC 25, Balance unchanged, prevents malicious balance inflation.
        """
        stan = "000303"
        rrn = "202611010033"

        # Step 1: Failed transaction due to incorrect PIN
        req_0200 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=100000,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_DECLINED",
            expiry_date="2812",
            pin="0000",  # Incorrect PIN
        )
        res_0200 = self.switch.process_message(req_0200)
        self.assertEqual(res_0200.response_code, "55")
        self.assert_balance(self.card_active, 1000000)

        # Step 2: Attempt 0400 reversal on the declined transaction
        req_0400 = ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=100000,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_DECLINED",
        )
        res_0400 = self.switch.process_message(req_0400)

        self.assertEqual(res_0400.response_code, RC_UNABLE_TO_LOCATE_RECORD)
        # Customer balance must remain exactly 1,000,000 (no fraudulent refund)
        self.assert_balance(self.card_active, 1000000)
        self.assert_daily_accumulated(self.card_active, 0)

    def test_SIT_REV_004_duplicate_reversal_rejected(self):
        """
        SIT-REV-004: Duplicate Reversal Guard (RC 94).
        Terminal sends two consecutive 0400 reversal requests for the same transaction.
        First reversal succeeds (RC 00), second reversal is rejected (RC 94).
        Proves customer is not credited twice.
        """
        stan = "000304"
        rrn = "202611010034"
        amount = 120000

        # Step 1: Timeout transaction
        req_0200 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_DUP_REV",
            expiry_date="2812",
            pin="1234",
            simulate_timeout=True,
        )
        self.switch.process_message(req_0200)
        self.assert_balance(self.card_active, 880000)

        # Step 2: First Reversal (Approved)
        req_rev1 = ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_DUP_REV",
        )
        res_rev1 = self.switch.process_message(req_rev1)
        self.assertEqual(res_rev1.response_code, RC_APPROVED)
        self.assert_balance(self.card_active, 1000000)

        # Step 3: Second Reversal (Duplicate)
        req_rev2 = ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_DUP_REV",
        )
        res_rev2 = self.switch.process_message(req_rev2)
        self.assertEqual(res_rev2.response_code, RC_DUPLICATE_TRANSMISSION)

        # Balance must still be 1,000,000 (NOT 1,120,000)
        self.assert_balance(self.card_active, 1000000)
        self.assert_daily_accumulated(self.card_active, 0)

    def test_SIT_REV_005_approved_transaction_manual_reversal(self):
        """
        SIT-REV-005: Reversal of an Approved Transaction (Void / Refund).
        Tests that an initially APPROVED transaction can be reversed,
        restoring customer balance to original amount.
        """
        stan = "000305"
        rrn = "202611010035"
        amount = 250000

        # Step 1: Normal approval
        req_0200 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_VOID_1",
            expiry_date="2812",
            pin="1234",
        )
        res_0200 = self.switch.process_message(req_0200)
        self.assertEqual(res_0200.response_code, RC_APPROVED)
        self.assert_balance(self.card_active, 750000)

        # Step 2: Reversal request
        req_0400 = ISO8583Message(
            mti=MTI_REVERSAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=amount,
            stan=stan,
            rrn=rrn,
            terminal_id="POS_VOID_1",
        )
        res_0400 = self.switch.process_message(req_0400)
        self.assertEqual(res_0400.response_code, RC_APPROVED)

        # Final Balance Check
        self.assert_balance(self.card_active, 1000000)
        self.assert_daily_accumulated(self.card_active, 0)
