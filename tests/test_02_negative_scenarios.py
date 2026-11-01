"""
Category 2: Negative Test Scenarios.
Validates business rule rejections (Insufficient Funds, Wrong PIN, Expired Card,
Invalid Amounts, Exceeded Daily Limits, Non-existent Cards) and proves via SQL assertions
that customer account balances remain completely untouched.
"""

from src.iso8583_models import (
    ISO8583Message,
    MTI_FINANCIAL_REQUEST,
    MTI_FINANCIAL_RESPONSE,
    PROC_PURCHASE,
    PROC_WITHDRAWAL,
    RC_INVALID_AMOUNT,
    RC_INVALID_CARD,
    RC_INSUFFICIENT_FUNDS,
    RC_EXPIRED_CARD,
    RC_INCORRECT_PIN,
    RC_EXCEEDS_LIMIT,
)
from tests.base_test import BasePaymentTestCase


class TestNegativeScenarios(BasePaymentTestCase):
    """
    SIT Test Cases for Transaction Declines and Failure Protection.
    """

    def test_SIT_NEG_001_insufficient_funds(self):
        """
        SIT-NEG-001: Insufficient Account Balance (RC 51).
        Card Balance: 50,000 -> Requested Amount: 100,000.
        Expected: RC 51, Balance remains 50,000, Status DECLINED.
        """
        initial_balance = 50000
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_low_balance,
            processing_code=PROC_PURCHASE,
            amount=100000,
            stan="000201",
            rrn="202611010011",
            terminal_id="POS_NEG_01",
            expiry_date="2812",
            pin="5678",
        )

        response = self.switch.process_message(request)

        # 1. ISO 8583 Assertions
        self.assertEqual(response.mti, MTI_FINANCIAL_RESPONSE)
        self.assertEqual(response.response_code, RC_INSUFFICIENT_FUNDS)

        # 2. SQL Audit & Balance Untouched Assertions
        self.assert_balance(self.card_low_balance, initial_balance)
        self.assert_daily_accumulated(self.card_low_balance, 0)
        self.assert_transaction_logged(
            stan="000201",
            rrn="202611010011",
            expected_status="DECLINED",
            expected_rc=RC_INSUFFICIENT_FUNDS,
        )

    def test_SIT_NEG_002_incorrect_pin(self):
        """
        SIT-NEG-002: Incorrect Customer PIN (RC 55).
        Correct PIN: 1234 -> Provided PIN: 9999.
        Expected: RC 55, Balance remains 1,000,000, Status DECLINED.
        """
        initial_balance = 1000000
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=50000,
            stan="000202",
            rrn="202611010012",
            terminal_id="POS_NEG_02",
            expiry_date="2812",
            pin="9999",  # Wrong PIN
        )

        response = self.switch.process_message(request)

        self.assertEqual(response.response_code, RC_INCORRECT_PIN)
        self.assert_balance(self.card_active, initial_balance)
        self.assert_daily_accumulated(self.card_active, 0)
        self.assert_transaction_logged(
            stan="000202",
            rrn="202611010012",
            expected_status="DECLINED",
            expected_rc=RC_INCORRECT_PIN,
        )

    def test_SIT_NEG_003_expired_card(self):
        """
        SIT-NEG-003: Expired Card Expiration Date (RC 54).
        Card Expiry: 2101 (Jan 2021) -> Reference Date: 2411 (Nov 2024).
        Expected: RC 54, Balance remains 500,000, Status DECLINED.
        """
        initial_balance = 500000
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_expired,
            processing_code=PROC_WITHDRAWAL,
            amount=100000,
            stan="000203",
            rrn="202611010013",
            terminal_id="ATM_NEG_03",
            expiry_date="2101",
            pin="9999",
        )

        response = self.switch.process_message(request)

        self.assertEqual(response.response_code, RC_EXPIRED_CARD)
        self.assert_balance(self.card_expired, initial_balance)
        self.assert_daily_accumulated(self.card_expired, 0)
        self.assert_transaction_logged(
            stan="000203",
            rrn="202611010013",
            expected_status="DECLINED",
            expected_rc=RC_EXPIRED_CARD,
        )

    def test_SIT_NEG_004_expiry_date_mismatch(self):
        """
        SIT-NEG-004: Expiration Date Mismatch Between Request and Database (RC 54).
        Card Expiry in DB: 2812 -> Request Expiry: 2510.
        Expected: RC 54, Balance remains untouched, Status DECLINED.
        """
        initial_balance = 1000000
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=50000,
            stan="000204",
            rrn="202611010014",
            terminal_id="POS_NEG_04",
            expiry_date="2510",  # Mismatch
            pin="1234",
        )

        response = self.switch.process_message(request)

        self.assertEqual(response.response_code, RC_EXPIRED_CARD)
        self.assert_balance(self.card_active, initial_balance)
        self.assert_transaction_logged(
            stan="000204",
            rrn="202611010014",
            expected_status="DECLINED",
            expected_rc=RC_EXPIRED_CARD,
        )

    def test_SIT_NEG_005_invalid_amount_zero_or_negative(self):
        """
        SIT-NEG-005: Invalid Transaction Amount (RC 13).
        Tests both zero (0) and negative (-50000) amounts.
        Expected: RC 13, Balance untouched.
        """
        initial_balance = 1000000

        # Subtest A: Zero amount
        req_zero = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=0,
            stan="000205",
            rrn="202611010015",
            terminal_id="POS_NEG_05A",
            expiry_date="2812",
            pin="1234",
        )
        res_zero = self.switch.process_message(req_zero)
        self.assertEqual(res_zero.response_code, RC_INVALID_AMOUNT)
        self.assert_balance(self.card_active, initial_balance)

        # Subtest B: Negative amount
        req_neg = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=-50000,
            stan="000206",
            rrn="202611010016",
            terminal_id="POS_NEG_05B",
            expiry_date="2812",
            pin="1234",
        )
        res_neg = self.switch.process_message(req_neg)
        self.assertEqual(res_neg.response_code, RC_INVALID_AMOUNT)
        self.assert_balance(self.card_active, initial_balance)

    def test_SIT_NEG_006_exceeds_daily_limit_single_tx(self):
        """
        SIT-NEG-006: Exceeds Daily Limit on Single Transaction (RC 61).
        Card Daily Limit: 100,000 -> Single Request: 150,000.
        Expected: RC 61, Balance remains 1,000,000, Status DECLINED.
        """
        initial_balance = 1000000
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_low_limit,
            processing_code=PROC_WITHDRAWAL,
            amount=150000,
            stan="000207",
            rrn="202611010017",
            terminal_id="ATM_NEG_06",
            expiry_date="2812",
            pin="1111",
        )

        response = self.switch.process_message(request)

        self.assertEqual(response.response_code, RC_EXCEEDS_LIMIT)
        self.assert_balance(self.card_low_limit, initial_balance)
        self.assert_daily_accumulated(self.card_low_limit, 0)
        self.assert_transaction_logged(
            stan="000207",
            rrn="202611010017",
            expected_status="DECLINED",
            expected_rc=RC_EXCEEDS_LIMIT,
        )

    def test_SIT_NEG_007_exceeds_daily_limit_cumulative(self):
        """
        SIT-NEG-007: Exceeds Daily Limit on Cumulative Transactions (RC 61).
        Card Daily Limit: 100,000.
        Tx 1: 80,000 -> Approved (RC 00), Accumulated = 80,000.
        Tx 2: 30,000 -> Total would be 110,000 -> Declined (RC 61).
        Final Balance: 1,000,000 - 80,000 = 920,000.
        """
        # Tx 1: 80,000
        req1 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_low_limit,
            processing_code=PROC_PURCHASE,
            amount=80000,
            stan="000208",
            rrn="202611010018",
            terminal_id="POS_NEG_07A",
            expiry_date="2812",
            pin="1111",
        )
        res1 = self.switch.process_message(req1)
        self.assertEqual(res1.response_code, "00")
        self.assert_balance(self.card_low_limit, 920000)
        self.assert_daily_accumulated(self.card_low_limit, 80000)

        # Tx 2: 30,000 (would push total to 110,000 > 100,000)
        req2 = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_low_limit,
            processing_code=PROC_PURCHASE,
            amount=30000,
            stan="000209",
            rrn="202611010019",
            terminal_id="POS_NEG_07B",
            expiry_date="2812",
            pin="1111",
        )
        res2 = self.switch.process_message(req2)
        self.assertEqual(res2.response_code, RC_EXCEEDS_LIMIT)

        # Verify balance was NOT touched on second transaction
        self.assert_balance(self.card_low_limit, 920000)
        self.assert_daily_accumulated(self.card_low_limit, 80000)
        self.assert_transaction_logged(
            stan="000209",
            rrn="202611010019",
            expected_status="DECLINED",
            expected_rc=RC_EXCEEDS_LIMIT,
        )

    def test_SIT_NEG_008_unregistered_card_pan(self):
        """
        SIT-NEG-008: Unregistered Card PAN (RC 14).
        Non-existent PAN: 4000999999999999.
        Expected: RC 14, Status DECLINED.
        """
        unknown_pan = "4000999999999999"
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=unknown_pan,
            processing_code=PROC_PURCHASE,
            amount=50000,
            stan="000210",
            rrn="202611010020",
            terminal_id="POS_NEG_08",
            expiry_date="2812",
            pin="1234",
        )

        response = self.switch.process_message(request)

        self.assertEqual(response.response_code, RC_INVALID_CARD)
        self.assert_transaction_logged(
            stan="000210",
            rrn="202611010020",
            expected_status="DECLINED",
            expected_rc=RC_INVALID_CARD,
        )
