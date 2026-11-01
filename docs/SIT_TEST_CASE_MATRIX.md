# System Integration Testing (SIT) Test Case Matrix
## Payment Switching Simulator & Automated QA Testing Suite (`iso8583-payment-qa-suite`)

This document serves as the comprehensive System Integration Testing (SIT) Matrix for the ISO 8583 Payment Switching Simulator. It provides the mapping between business requirements, ISO 8583 protocol specifications, test inputs, expected DE 39 response codes, SQL data validation queries, and automated test implementation.

---

### Test Execution Summary
- **Total Test Cases**: 22
- **Passed**: 22 (100%)
- **Failed**: 0
- **Execution Engine**: Python `unittest` / `pytest`
- **Database Engine**: In-memory / Relational SQLite

---

### Category 1: Positive Scenarios (Happy Path)

| Test ID | Scenario Description | ISO 8583 Input Data Elements | Expected DE 39 | SQL Validation Query & Assertion | Test Method | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SIT-POS-001** | Valid POS Merchant Purchase | `MTI=0200`, `DE3=000000`, `DE4=150000`, `DE11=000101`, `DE37=202611010001`, `DE14=2812`, `DE52=1234` | `00` (Approved) | `SELECT balance, daily_accumulated FROM card_accounts WHERE pan='...';`<br>Assert `balance=850000`, `daily_accumulated=150000`.<br>`SELECT status FROM transaction_logs WHERE stan='000101';`<br>Assert `status='APPROVED'`. | `test_SIT_POS_001_valid_pos_purchase` | **PASSED** |
| **SIT-POS-002** | Valid ATM Cash Withdrawal | `MTI=0200`, `DE3=010000`, `DE4=200000`, `DE11=000102`, `DE37=202611010002`, `DE14=2812`, `DE52=1234` | `00` (Approved) | `SELECT balance, daily_accumulated FROM card_accounts WHERE pan='...';`<br>Assert `balance=800000`, `daily_accumulated=200000`.<br>Assert `status='APPROVED'` in `transaction_logs`. | `test_SIT_POS_002_valid_atm_cash_withdrawal` | **PASSED** |
| **SIT-POS-003** | Sequential Multi-Tx Balance Integrity | `MTI=0200`, sequential purchases (100k, 250k, 50k) totaling 400k | `00` (Approved) on all | `SELECT balance, daily_accumulated FROM card_accounts WHERE pan='...';`<br>Assert ending `balance=600000`, `daily_accumulated=400000`. | `test_SIT_POS_003_sequential_transactions_ledger_integrity` | **PASSED** |
| **SIT-POS-004** | Balance Inquiry (Non-financial debit) | `MTI=0200`, `DE3=300000`, `DE4=0`, `DE11=000106`, `DE37=202611010006`, `DE52=1234` | `00` (Approved) | Assert `balance=1000000` (untouched), `daily_accumulated=0`.<br>Assert inquiry logged in `transaction_logs`. | `test_SIT_POS_004_balance_inquiry` | **PASSED** |
| **SIT-POS-005** | HTTP JSON Endpoint Transaction | `POST /iso8583/transaction` with JSON payload representing MTI 0200, 75k | `00` (Approved) | HTTP response status `200 OK`, JSON body contains `MTI 0210`, `RC 00`.<br>SQL checks assert `balance=925000`. | `test_SIT_POS_005_http_endpoint_transaction` | **PASSED** |

---

### Category 2: Negative Scenarios (Declines & Validations)

| Test ID | Scenario Description | ISO 8583 Input Data Elements | Expected DE 39 | SQL Validation Query & Assertion | Test Method | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SIT-NEG-001** | Insufficient Account Funds | `MTI=0200`, `DE4=100000`, available balance `50000` | `51` (Insufficient Funds) | `SELECT balance FROM card_accounts WHERE pan='...';`<br>Assert `balance=50000` (100% untouched).<br>Assert `status='DECLINED'` in `transaction_logs`. | `test_SIT_NEG_001_insufficient_funds` | **PASSED** |
| **SIT-NEG-002** | Incorrect Customer PIN | `MTI=0200`, `DE4=50000`, `DE52=9999` (correct is `1234`) | `55` (Incorrect PIN) | `SELECT balance FROM card_accounts WHERE pan='...';`<br>Assert `balance=1000000` (untouched).<br>Assert `status='DECLINED'` in `transaction_logs`. | `test_SIT_NEG_002_incorrect_pin` | **PASSED** |
| **SIT-NEG-003** | Expired Card Expiration Date | `MTI=0200`, `DE14=2101` (Card expired Jan 2021, Ref Nov 2024) | `54` (Expired Card) | `SELECT balance FROM card_accounts WHERE pan='...';`<br>Assert `balance=500000` (untouched).<br>Assert `status='DECLINED'` in `transaction_logs`. | `test_SIT_NEG_003_expired_card` | **PASSED** |
| **SIT-NEG-004** | Expiration Date Mismatch | `MTI=0200`, `DE14=2510` (card DB expiry is `2812`) | `54` (Expired / Mismatch) | Assert card balance untouched in `card_accounts`.<br>Assert `status='DECLINED'` in `transaction_logs`. | `test_SIT_NEG_004_expiry_date_mismatch` | **PASSED** |
| **SIT-NEG-005** | Invalid Amount (Zero or Negative) | `MTI=0200`, `DE4=0` and `DE4=-50000` | `13` (Invalid Amount) | Assert card balance untouched in `card_accounts`.<br>Assert `status='DECLINED'` in `transaction_logs`. | `test_SIT_NEG_005_invalid_amount_zero_or_negative` | **PASSED** |
| **SIT-NEG-006** | Exceeds Daily Limit (Single Tx) | `MTI=0200`, `DE4=150000` on card with `daily_limit=100000` | `61` (Exceeds Limit) | Assert card balance untouched in `card_accounts`.<br>Assert `status='DECLINED'` in `transaction_logs`. | `test_SIT_NEG_006_exceeds_daily_limit_single_tx` | **PASSED** |
| **SIT-NEG-007** | Exceeds Daily Limit (Cumulative) | Tx 1: 80k (Approved). Tx 2: 30k (would total 110k > 100k) | `61` on Tx 2 | Assert Tx 2 balance untouched (`920000` maintained).<br>Assert Tx 2 logged as `DECLINED`. | `test_SIT_NEG_007_exceeds_daily_limit_cumulative` | **PASSED** |
| **SIT-NEG-008** | Unregistered Card PAN | `MTI=0200`, `DE2=4000999999999999` (non-existent) | `14` (Invalid Card Number) | Assert `status='DECLINED'` in `transaction_logs`.<br>Zero records modified in `card_accounts`. | `test_SIT_NEG_008_unregistered_card_pan` | **PASSED** |

---

### Category 3: Timeout & Auto-Reversal Scenarios

| Test ID | Scenario Description | ISO 8583 Input Data Elements | Expected DE 39 | SQL Validation Query & Assertion | Test Method | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SIT-REV-001** | Network Timeout followed by Auto-Reversal | Step 1: `MTI=0200`, `simulate_timeout=True`, 100k<br>Step 2: `MTI=0400`, matching STAN/RRN, 100k | Step 1: `68`<br>Step 2: `00` | Step 1: `balance=900000`, `status='TIMEOUT_SUSPECT'`.<br>Step 2: `balance=1000000` (100% restored).<br>Original tx updated to `status='REVERSED'`. | `test_SIT_REV_001_timeout_and_auto_reversal` | **PASSED** |
| **SIT-REV-002** | Orphan Reversal Rejection | `MTI=0400`, non-existent `STAN=999999`, `RRN=999999999999` | `25` (Unable to Locate Record) | Assert balance is NOT credited in `card_accounts`.<br>Assert reversal logged as `ORPHAN_REJECTED`. | `test_SIT_REV_002_orphan_reversal_rejected` | **PASSED** |
| **SIT-REV-003** | Reversal of Declined Tx Rejected | `MTI=0400` targeting a previously declined (wrong PIN) tx | `25` (Original not debited) | Assert balance remains untouched (`1000000`).<br>Prevents balance inflation fraud. | `test_SIT_REV_003_reversal_of_declined_transaction_rejected` | **PASSED** |
| **SIT-REV-004** | Duplicate Reversal Guard | First `MTI=0400` (Approved), followed by second identical `MTI=0400` | First: `00`<br>Second: `94` | Assert customer is NOT refunded twice in `card_accounts`.<br>Second reversal logged as `DUPLICATE_REJECTED`. | `test_SIT_REV_004_duplicate_reversal_rejected` | **PASSED** |
| **SIT-REV-005** | Approved Transaction Manual Void/Reversal | `MTI=0200` Approved (250k) followed by `MTI=0400` Reversal | `00` on both | Initial debit: `750000`.<br>Post-reversal: `balance=1000000` (fully restored).<br>Original tx status updated to `REVERSED`. | `test_SIT_REV_005_approved_transaction_manual_reversal` | **PASSED** |

---

### Category 4: Idempotency, Concurrency & SQL Audits

| Test ID | Scenario Description | ISO 8583 Input Data Elements | Expected DE 39 | SQL Validation Query & Assertion | Test Method | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SIT-IDM-001** | Sequential Duplicate Transmission | Two identical `MTI=0200` requests with identical `STAN/RRN` | Tx 1: `00`<br>Tx 2: `94` | Assert balance debited exactly once (`900000`).<br>Assert Tx 2 logged as `DUPLICATE_REJECTED`. | `test_SIT_IDM_001_sequential_duplicate_transaction` | **PASSED** |
| **SIT-IDM-002** | Concurrent Duplicate Burst (10 Threads) | 10 simultaneous threads sending identical `MTI=0200`, `STAN`, `RRN` | Exactly 1 `00`,<br>9 `94` | Assert balance debited exactly once (`900000`).<br>Anti-double-debit thread lock verified under concurrency. | `test_SIT_IDM_002_concurrent_duplicate_burst` | **PASSED** |
| **SIT-IDM-003** | Concurrent Balance Exhaustion (Anti-Overdraft) | 5 simultaneous threads requesting 20k each on card with 50k balance | Exactly 2 `00`,<br>3 `51` | Assert `balance=10000` (50k - 40k).<br>Balance never drops below zero, zero race condition overdraft. | `test_SIT_IDM_003_concurrent_balance_exhaustion_no_overdraft` | **PASSED** |
| **SIT-IDM-004** | Standalone SQL QA Scripts Execution | Execution of `sql/01_*.sql`, `sql/02_*.sql`, `sql/03_*.sql`, `sql/04_*.sql` | N/A | Query 1 returns 0 double debits.<br>Query 2 detects orphan reversal.<br>Query 3 detects unsettled suspect tx.<br>Query 4 confirms `BALANCED` status across all card accounts. | `test_SIT_IDM_004_sql_audit_and_reconciliation_scripts` | **PASSED** |
