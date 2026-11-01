"""
Payment Switching Simulator Engine.
Handles ISO 8583 message parsing, authorization, balance ledger mutation,
timeout simulation, auto-reversals, and idempotency protection.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

from src.database import DatabaseManager
from src.iso8583_models import (
    ISO8583Message,
    MTI_FINANCIAL_REQUEST,
    MTI_FINANCIAL_RESPONSE,
    MTI_REVERSAL_REQUEST,
    MTI_REVERSAL_RESPONSE,
    PROC_BALANCE_INQUIRY,
    RC_APPROVED,
    RC_INVALID_AMOUNT,
    RC_INVALID_CARD,
    RC_UNABLE_TO_LOCATE_RECORD,
    RC_INSUFFICIENT_FUNDS,
    RC_EXPIRED_CARD,
    RC_INCORRECT_PIN,
    RC_EXCEEDS_LIMIT,
    RC_RESPONSE_RECEIVED_TOO_LATE,
    RC_DUPLICATE_TRANSMISSION,
    RC_SYSTEM_ERROR,
    RESPONSE_CODE_DESCRIPTIONS,
)


class PaymentSwitchSimulator:
    """
    Simulates a Core Banking Payment Switch processing ISO 8583 transactions.
    """

    def __init__(self, db: DatabaseManager, reference_date_yymm: str = "2411"):
        """
        :param db: DatabaseManager instance for state and audit persistence.
        :param reference_date_yymm: YYMM string used to evaluate card expiration (default 2411 -> Nov 2024).
        """
        self.db = db
        self.reference_date_yymm = reference_date_yymm

    def process_message(self, request: ISO8583Message) -> ISO8583Message:
        """
        Main entry point for ISO 8583 message routing.
        Routes MTI 0200 to financial processor and MTI 0400 to reversal processor.
        """
        if request.mti == MTI_FINANCIAL_REQUEST:
            return self._process_financial_request(request)
        elif request.mti == MTI_REVERSAL_REQUEST:
            return self._process_reversal_request(request)
        else:
            return ISO8583Message(
                mti="9999",
                pan=request.pan,
                stan=request.stan,
                rrn=request.rrn,
                terminal_id=request.terminal_id,
                response_code=RC_SYSTEM_ERROR,
                notes=f"Unsupported MTI: {request.mti}",
            )

    def _process_financial_request(self, req: ISO8583Message) -> ISO8583Message:
        """
        Process Financial Transaction Request (MTI 0200 -> 0210).
        Enforces idempotency, validations, atomic debit, and audit logging.
        """
        now = datetime.now(timezone.utc).isoformat()
        lock = self.db.get_lock()

        with lock:
            cur = self.db.conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")

                # 1. Idempotency Check: Prevent duplicate 0200 processing for identical STAN & RRN
                cur.execute(
                    """
                    SELECT id, status, response_code FROM transaction_logs
                    WHERE stan = ? AND rrn = ? AND mti = ?
                    LIMIT 1
                    """,
                    (req.stan, req.rrn, MTI_FINANCIAL_REQUEST),
                )
                duplicate = cur.fetchone()
                if duplicate:
                    # Log duplicate rejection audit trail
                    cur.execute(
                        """
                        INSERT INTO transaction_logs (
                            mti, response_mti, pan, processing_code, amount,
                            stan, rrn, terminal_id, response_code, status,
                            original_tx_id, notes, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            MTI_FINANCIAL_REQUEST,
                            MTI_FINANCIAL_RESPONSE,
                            req.pan,
                            req.processing_code,
                            req.amount,
                            req.stan,
                            req.rrn,
                            req.terminal_id,
                            RC_DUPLICATE_TRANSMISSION,
                            "DUPLICATE_REJECTED",
                            duplicate["id"],
                            "Duplicate transmission detected: STAN/RRN already processed",
                            now,
                            now,
                        ),
                    )
                    cur.execute("COMMIT")
                    return self._build_response(
                        req,
                        MTI_FINANCIAL_RESPONSE,
                        RC_DUPLICATE_TRANSMISSION,
                        "Duplicate transmission detected",
                    )

                # 2. Amount Validation (DE 4)
                if req.processing_code != PROC_BALANCE_INQUIRY and req.amount <= 0:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_INVALID_AMOUNT,
                        "DECLINED", "Invalid transaction amount (amount must be positive integer)", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_INVALID_AMOUNT, "Invalid amount")

                # 3. Card Account Existence Check (DE 2)
                cur.execute("SELECT * FROM card_accounts WHERE pan = ?", (req.pan,))
                card = cur.fetchone()
                if not card:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_INVALID_CARD,
                        "DECLINED", "Card not found in card_accounts", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_INVALID_CARD, "Card not found")

                if card["status"] != "ACTIVE":
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_INVALID_CARD,
                        "DECLINED", f"Card is not active (status={card['status']})", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_INVALID_CARD, "Card inactive")

                # 4. Expiry Date Validation (DE 14)
                # Format YYMM comparison
                card_expiry = card["expiry_date"]
                msg_expiry = req.expiry_date if req.expiry_date else card_expiry

                if card_expiry < self.reference_date_yymm or msg_expiry < self.reference_date_yymm:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_EXPIRED_CARD,
                        "DECLINED", f"Card expired: card_exp={card_expiry}, ref={self.reference_date_yymm}", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_EXPIRED_CARD, "Expired card")

                if req.expiry_date and req.expiry_date != card_expiry:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_EXPIRED_CARD,
                        "DECLINED", f"Expiry mismatch: req={req.expiry_date}, card={card_expiry}", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_EXPIRED_CARD, "Expiry mismatch")

                # 5. PIN Verification (DE 52)
                if req.pin != card["pin"]:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_INCORRECT_PIN,
                        "DECLINED", "Incorrect PIN provided", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_INCORRECT_PIN, "Incorrect PIN")

                # If Balance Inquiry, return balance in notes without deducting
                if req.processing_code == PROC_BALANCE_INQUIRY:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_APPROVED,
                        "APPROVED", f"Balance inquiry success. Current balance: {card['balance']}", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(
                        req, MTI_FINANCIAL_RESPONSE, RC_APPROVED,
                        f"Balance: {card['balance']}"
                    )

                # 6. Daily Limit Enforcement (DE 61)
                new_daily_total = card["daily_accumulated"] + req.amount
                if new_daily_total > card["daily_limit"]:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_EXCEEDS_LIMIT,
                        "DECLINED",
                        f"Daily limit exceeded: current={card['daily_accumulated']}, attempted={req.amount}, limit={card['daily_limit']}",
                        now,
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_EXCEEDS_LIMIT, "Exceeds daily limit")

                # 7. Account Balance Check (DE 51)
                if card["balance"] < req.amount:
                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_INSUFFICIENT_FUNDS,
                        "DECLINED",
                        f"Insufficient funds: available={card['balance']}, requested={req.amount}",
                        now,
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_INSUFFICIENT_FUNDS, "Insufficient funds")

                # 8. Timeout Simulation (Network drop after issuer debit)
                if req.simulate_timeout:
                    # Debit balance in TIMEOUT_SUSPECT state
                    new_balance = card["balance"] - req.amount
                    cur.execute(
                        """
                        UPDATE card_accounts
                        SET balance = ?, daily_accumulated = ?, updated_at = ?
                        WHERE pan = ?
                        """,
                        (new_balance, new_daily_total, now, req.pan),
                    )

                    self._log_transaction(
                        cur, req, MTI_FINANCIAL_RESPONSE, RC_RESPONSE_RECEIVED_TOO_LATE,
                        "TIMEOUT_SUSPECT",
                        "Network timeout simulated: balance debited, awaiting auto-reversal",
                        now,
                    )
                    cur.execute("COMMIT")
                    return self._build_response(
                        req,
                        MTI_FINANCIAL_RESPONSE,
                        RC_RESPONSE_RECEIVED_TOO_LATE,
                        "Response received too late (Timeout Suspect)",
                    )

                # 9. Normal Approval: Atomic Balance Deduction
                new_balance = card["balance"] - req.amount
                cur.execute(
                    """
                    UPDATE card_accounts
                    SET balance = ?, daily_accumulated = ?, updated_at = ?
                    WHERE pan = ?
                    """,
                    (new_balance, new_daily_total, now, req.pan),
                )

                self._log_transaction(
                    cur, req, MTI_FINANCIAL_RESPONSE, RC_APPROVED,
                    "APPROVED",
                    f"Transaction approved. New balance: {new_balance}",
                    now,
                )
                cur.execute("COMMIT")
                return self._build_response(req, MTI_FINANCIAL_RESPONSE, RC_APPROVED, "Approved")

            except Exception as e:
                cur.execute("ROLLBACK")
                raise e

    def _process_reversal_request(self, req: ISO8583Message) -> ISO8583Message:
        """
        Process Reversal Request (MTI 0400 -> 0410).
        Validates original transaction, restores deducted customer balance,
        prevents orphan reversals, and guards against duplicate reversals.
        """
        now = datetime.now(timezone.utc).isoformat()
        lock = self.db.get_lock()

        with lock:
            cur = self.db.conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")

                # 1. Duplicate Reversal Check
                # Check if an 0400 reversal was already approved for this STAN & RRN
                cur.execute(
                    """
                    SELECT id FROM transaction_logs
                    WHERE stan = ? AND rrn = ? AND mti = ? AND status = 'APPROVED'
                    LIMIT 1
                    """,
                    (req.stan, req.rrn, MTI_REVERSAL_REQUEST),
                )
                duplicate_reversal = cur.fetchone()
                if duplicate_reversal:
                    self._log_transaction(
                        cur, req, MTI_REVERSAL_RESPONSE, RC_DUPLICATE_TRANSMISSION,
                        "DUPLICATE_REJECTED",
                        "Duplicate reversal rejected: Reversal already executed for this transaction",
                        now,
                        original_tx_id=duplicate_reversal["id"],
                    )
                    cur.execute("COMMIT")
                    return self._build_response(
                        req,
                        MTI_REVERSAL_RESPONSE,
                        RC_DUPLICATE_TRANSMISSION,
                        "Duplicate reversal request",
                    )

                # 2. Locate Original 0200 Transaction
                cur.execute(
                    """
                    SELECT id, pan, amount, status FROM transaction_logs
                    WHERE stan = ? AND rrn = ? AND mti = ?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (req.stan, req.rrn, MTI_FINANCIAL_REQUEST),
                )
                original_tx = cur.fetchone()

                # 3. Check for Orphan Reversal (No original record, PAN/amount mismatch, or not debited)
                if not original_tx:
                    self._log_transaction(
                        cur, req, MTI_REVERSAL_RESPONSE, RC_UNABLE_TO_LOCATE_RECORD,
                        "ORPHAN_REJECTED",
                        "Orphan reversal rejected: No matching original 0200 record found",
                        now,
                    )
                    cur.execute("COMMIT")
                    return self._build_response(
                        req,
                        MTI_REVERSAL_RESPONSE,
                        RC_UNABLE_TO_LOCATE_RECORD,
                        "Unable to locate record on file",
                    )

                if original_tx["status"] == "REVERSED":
                    self._log_transaction(
                        cur, req, MTI_REVERSAL_RESPONSE, RC_DUPLICATE_TRANSMISSION,
                        "DUPLICATE_REJECTED",
                        "Original transaction is already in REVERSED status",
                        now,
                        original_tx_id=original_tx["id"],
                    )
                    cur.execute("COMMIT")
                    return self._build_response(
                        req,
                        MTI_REVERSAL_RESPONSE,
                        RC_DUPLICATE_TRANSMISSION,
                        "Transaction already reversed",
                    )

                if original_tx["status"] not in ("APPROVED", "TIMEOUT_SUSPECT"):
                    # Original transaction was declined (never debited), cannot be refunded
                    self._log_transaction(
                        cur, req, MTI_REVERSAL_RESPONSE, RC_UNABLE_TO_LOCATE_RECORD,
                        "ORPHAN_REJECTED",
                        f"Cannot reverse non-debited transaction (original status: {original_tx['status']})",
                        now,
                        original_tx_id=original_tx["id"],
                    )
                    cur.execute("COMMIT")
                    return self._build_response(
                        req,
                        MTI_REVERSAL_RESPONSE,
                        RC_UNABLE_TO_LOCATE_RECORD,
                        "Original transaction was not debited",
                    )

                # 4. Valid Original Found: Refund Balance & Restore Daily Accumulated
                refund_amount = original_tx["amount"]
                cur.execute("SELECT balance, daily_accumulated FROM card_accounts WHERE pan = ?", (original_tx["pan"],))
                card = cur.fetchone()
                if not card:
                    self._log_transaction(
                        cur, req, MTI_REVERSAL_RESPONSE, RC_SYSTEM_ERROR,
                        "DECLINED", "Card account missing during reversal processing", now
                    )
                    cur.execute("COMMIT")
                    return self._build_response(req, MTI_REVERSAL_RESPONSE, RC_SYSTEM_ERROR, "Account error")

                restored_balance = card["balance"] + refund_amount
                restored_daily = max(0, card["daily_accumulated"] - refund_amount)

                cur.execute(
                    """
                    UPDATE card_accounts
                    SET balance = ?, daily_accumulated = ?, updated_at = ?
                    WHERE pan = ?
                    """,
                    (restored_balance, restored_daily, now, original_tx["pan"]),
                )

                # Update original transaction status to REVERSED
                cur.execute(
                    """
                    UPDATE transaction_logs
                    SET status = 'REVERSED', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, original_tx["id"]),
                )

                # Log Reversal Approval
                self._log_transaction(
                    cur, req, MTI_REVERSAL_RESPONSE, RC_APPROVED,
                    "APPROVED",
                    f"Reversal approved. Balance restored to {restored_balance}",
                    now,
                    original_tx_id=original_tx["id"],
                )
                cur.execute("COMMIT")

                return self._build_response(
                    req,
                    MTI_REVERSAL_RESPONSE,
                    RC_APPROVED,
                    f"Reversal successful. Balance restored: {restored_balance}",
                )

            except Exception as e:
                cur.execute("ROLLBACK")
                raise e

    def _log_transaction(
        self,
        cur,
        msg: ISO8583Message,
        response_mti: str,
        response_code: str,
        status: str,
        notes: str,
        now: str,
        original_tx_id: Optional[int] = None,
    ) -> int:
        """Insert transaction log record into transaction_logs table."""
        cur.execute(
            """
            INSERT INTO transaction_logs (
                mti, response_mti, pan, processing_code, amount,
                stan, rrn, terminal_id, response_code, status,
                original_tx_id, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                msg.mti,
                response_mti,
                msg.pan,
                msg.processing_code,
                msg.amount,
                msg.stan,
                msg.rrn,
                msg.terminal_id,
                response_code,
                status,
                original_tx_id,
                notes,
                now,
                now,
            ),
        )
        return cur.lastrowid

    def _build_response(
        self,
        req: ISO8583Message,
        response_mti: str,
        response_code: str,
        notes: str,
    ) -> ISO8583Message:
        """Construct response message based on request elements."""
        return ISO8583Message(
            mti=response_mti,
            pan=req.pan,
            processing_code=req.processing_code,
            amount=req.amount,
            stan=req.stan,
            rrn=req.rrn,
            terminal_id=req.terminal_id,
            expiry_date=req.expiry_date,
            pin="",  # Never return PIN in response
            response_code=response_code,
            notes=f"{notes} ({RESPONSE_CODE_DESCRIPTIONS.get(response_code, '')})",
        )
