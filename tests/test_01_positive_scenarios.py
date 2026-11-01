"""
Category 1: Positive Test Scenarios (Happy Path).
Validates normal POS purchase, ATM withdrawal, sequential transactions,
and HTTP API integration with complete SQL balance & audit trail validation.
"""

import json
import socket
import threading
from http.server import HTTPServer
from urllib.request import Request, urlopen

from src.database import DatabaseManager
from src.iso8583_models import (
    ISO8583Message,
    MTI_FINANCIAL_REQUEST,
    MTI_FINANCIAL_RESPONSE,
    PROC_PURCHASE,
    PROC_WITHDRAWAL,
    PROC_BALANCE_INQUIRY,
    RC_APPROVED,
)
from src.payment_switch import PaymentSwitchSimulator
from src.server import make_switch_handler
from tests.base_test import BasePaymentTestCase


class TestPositiveScenarios(BasePaymentTestCase):
    """
    SIT Test Cases for Successful Transactions.
    """

    def test_SIT_POS_001_valid_pos_purchase(self):
        """
        SIT-POS-001: Valid POS Merchant Purchase (Processing Code 000000).
        Initial Balance: 1,000,000 -> Purchase: 150,000 -> Expected Balance: 850,000.
        Expected ISO 8583 Response Code: 00 (Approved).
        """
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_PURCHASE,
            amount=150000,
            stan="000101",
            rrn="202611010001",
            terminal_id="POS_MART_1",
            expiry_date="2812",
            pin="1234",
        )

        response = self.switch.process_message(request)

        # 1. ISO 8583 Message Assertions
        self.assertEqual(response.mti, MTI_FINANCIAL_RESPONSE)
        self.assertEqual(response.response_code, RC_APPROVED)
        self.assertEqual(response.pan, self.card_active)
        self.assertEqual(response.stan, "000101")
        self.assertEqual(response.rrn, "202611010001")

        # 2. SQL Database State Assertions
        self.assert_balance(self.card_active, 850000)
        self.assert_daily_accumulated(self.card_active, 150000)
        self.assert_transaction_logged(
            stan="000101",
            rrn="202611010001",
            expected_status="APPROVED",
            expected_rc=RC_APPROVED,
            mti=MTI_FINANCIAL_REQUEST,
        )

    def test_SIT_POS_002_valid_atm_cash_withdrawal(self):
        """
        SIT-POS-002: Valid ATM Cash Withdrawal (Processing Code 010000).
        Initial Balance: 1,000,000 -> Withdrawal: 200,000 -> Expected Balance: 800,000.
        Expected ISO 8583 Response Code: 00 (Approved).
        """
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_WITHDRAWAL,
            amount=200000,
            stan="000102",
            rrn="202611010002",
            terminal_id="ATM_CENTRAL_01",
            expiry_date="2812",
            pin="1234",
        )

        response = self.switch.process_message(request)

        # 1. ISO 8583 Assertions
        self.assertEqual(response.mti, MTI_FINANCIAL_RESPONSE)
        self.assertEqual(response.response_code, RC_APPROVED)

        # 2. SQL Database Assertions
        self.assert_balance(self.card_active, 800000)
        self.assert_daily_accumulated(self.card_active, 200000)
        self.assert_transaction_logged(
            stan="000102",
            rrn="202611010002",
            expected_status="APPROVED",
            expected_rc=RC_APPROVED,
        )

    def test_SIT_POS_003_sequential_transactions_ledger_integrity(self):
        """
        SIT-POS-003: Sequential Multiple Transactions on the Same Card.
        Tx 1: Purchase 100,000
        Tx 2: Withdrawal 250,000
        Tx 3: Purchase 50,000
        Total Debited: 400,000. Expected Ending Balance: 600,000.
        """
        tx_specs = [
            ("000103", "202611010003", PROC_PURCHASE, 100000),
            ("000104", "202611010004", PROC_WITHDRAWAL, 250000),
            ("000105", "202611010005", PROC_PURCHASE, 50000),
        ]

        expected_balance = 1000000
        accumulated = 0

        for stan, rrn, proc_code, amt in tx_specs:
            msg = ISO8583Message(
                mti=MTI_FINANCIAL_REQUEST,
                pan=self.card_active,
                processing_code=proc_code,
                amount=amt,
                stan=stan,
                rrn=rrn,
                terminal_id="TERM_SEQ",
                expiry_date="2812",
                pin="1234",
            )
            res = self.switch.process_message(msg)
            self.assertEqual(res.response_code, RC_APPROVED)

            expected_balance -= amt
            accumulated += amt

            self.assert_balance(self.card_active, expected_balance)
            self.assert_daily_accumulated(self.card_active, accumulated)

    def test_SIT_POS_004_balance_inquiry(self):
        """
        SIT-POS-004: Balance Inquiry (Processing Code 300000).
        Verifies balance inquiry returns 00 (Approved) and does NOT deduct customer balance.
        """
        request = ISO8583Message(
            mti=MTI_FINANCIAL_REQUEST,
            pan=self.card_active,
            processing_code=PROC_BALANCE_INQUIRY,
            amount=0,
            stan="000106",
            rrn="202611010006",
            terminal_id="ATM_INQ_01",
            expiry_date="2812",
            pin="1234",
        )

        response = self.switch.process_message(request)

        self.assertEqual(response.response_code, RC_APPROVED)
        self.assertIn("1000000", str(response.notes))
        # Balance must remain exactly 1,000,000
        self.assert_balance(self.card_active, 1000000)
        self.assert_daily_accumulated(self.card_active, 0)

    def test_SIT_POS_005_http_endpoint_transaction(self):
        """
        SIT-POS-005: End-to-end HTTP JSON Endpoint Transaction.
        Sends POST /iso8583/transaction over loopback HTTP and verifies JSON response.
        """
        # Find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        handler = make_switch_handler(self.switch)
        server = HTTPServer(("127.0.0.1", port), handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            url = f"http://127.0.0.1:{port}/iso8583/transaction"
            payload = {
                "mti": "0200",
                "pan": self.card_active,
                "processing_code": "000000",
                "amount": 75000,
                "stan": "000107",
                "rrn": "202611010007",
                "terminal_id": "POS_HTTP_1",
                "expiry_date": "2812",
                "pin": "1234",
            }

            req = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urlopen(req, timeout=5) as response:
                self.assertEqual(response.status, 200)
                body = json.loads(response.read().decode("utf-8"))

                self.assertEqual(body["mti"], "0210")
                self.assertEqual(body["response_code"], "00")
                self.assertEqual(body["pan"], self.card_active)
                self.assertEqual(body["amount"], 75000)

            # Validate database state
            self.assert_balance(self.card_active, 925000)
            self.assert_transaction_logged(
                stan="000107",
                rrn="202611010007",
                expected_status="APPROVED",
                expected_rc=RC_APPROVED,
            )
        finally:
            server.shutdown()
            server.server_close()
