"""
ISO 8583 Message Data Models and Standard Specification Constants.
Defines MTIs (Message Type Identifiers), Processing Codes, and Response Codes (DE 39).
"""

from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


# Message Type Identifiers (MTI)
MTI_FINANCIAL_REQUEST = "0200"
MTI_FINANCIAL_RESPONSE = "0210"
MTI_REVERSAL_REQUEST = "0400"
MTI_REVERSAL_RESPONSE = "0410"

# Processing Codes (DE 3)
PROC_PURCHASE = "000000"          # POS / Merchant Purchase
PROC_WITHDRAWAL = "010000"        # ATM Cash Withdrawal
PROC_BALANCE_INQUIRY = "300000"   # Balance Inquiry

# ISO 8583 Response Codes (DE 39)
RC_APPROVED = "00"
RC_INVALID_AMOUNT = "13"
RC_INVALID_CARD = "14"
RC_UNABLE_TO_LOCATE_RECORD = "25"
RC_INSUFFICIENT_FUNDS = "51"
RC_EXPIRED_CARD = "54"
RC_INCORRECT_PIN = "55"
RC_EXCEEDS_LIMIT = "61"
RC_RESPONSE_RECEIVED_TOO_LATE = "68"
RC_DUPLICATE_TRANSMISSION = "94"
RC_SYSTEM_ERROR = "96"

RESPONSE_CODE_DESCRIPTIONS: Dict[str, str] = {
    RC_APPROVED: "Approved or completed successfully",
    RC_INVALID_AMOUNT: "Invalid amount",
    RC_INVALID_CARD: "Invalid card number (no such card)",
    RC_UNABLE_TO_LOCATE_RECORD: "Unable to locate record on file",
    RC_INSUFFICIENT_FUNDS: "Insufficient funds",
    RC_EXPIRED_CARD: "Expired card",
    RC_INCORRECT_PIN: "Incorrect PIN",
    RC_EXCEEDS_LIMIT: "Exceeds withdrawal or purchase limit",
    RC_RESPONSE_RECEIVED_TOO_LATE: "Response received too late (Timeout Suspect)",
    RC_DUPLICATE_TRANSMISSION: "Duplicate transmission",
    RC_SYSTEM_ERROR: "System error",
}


@dataclass
class ISO8583Message:
    """
    Representation of an ISO 8583 Financial / Reversal Message.
    Maps common Data Elements (DE) to structured fields.
    """
    mti: str                                  # Message Type Identifier (0200, 0210, 0400, 0410)
    pan: str                                  # DE 2: Primary Account Number
    processing_code: str = PROC_PURCHASE      # DE 3: Processing Code
    amount: int = 0                           # DE 4: Amount in integer / smallest currency unit
    stan: str = ""                            # DE 11: Systems Trace Audit Number (6 digits)
    rrn: str = ""                             # DE 37: Retrieval Reference Number (12 characters)
    terminal_id: str = "TERM0001"             # DE 41: Card Acceptor Terminal ID
    expiry_date: str = ""                     # DE 14: Card Expiration Date (YYMM)
    pin: str = ""                             # DE 52: PIN (Encrypted / Plain simulation)
    response_code: Optional[str] = None       # DE 39: Action / Response Code
    notes: Optional[str] = None               # Additional audit context
    simulate_timeout: bool = False            # Testing flag to simulate network drop

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ISO8583Message":
        """Instantiate message from dictionary payload."""
        amount_val = data.get("amount", 0)
        try:
            amount_val = int(amount_val)
        except (ValueError, TypeError):
            amount_val = -1  # Invalid amount indicator

        return cls(
            mti=str(data.get("mti", "")),
            pan=str(data.get("pan", "")),
            processing_code=str(data.get("processing_code", PROC_PURCHASE)),
            amount=amount_val,
            stan=str(data.get("stan", "")),
            rrn=str(data.get("rrn", "")),
            terminal_id=str(data.get("terminal_id", "TERM0001")),
            expiry_date=str(data.get("expiry_date", "")),
            pin=str(data.get("pin", "")),
            response_code=data.get("response_code"),
            notes=data.get("notes"),
            simulate_timeout=bool(data.get("simulate_timeout", False)),
        )
