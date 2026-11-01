-- ============================================================================
-- SQL QA Audit Script 01: Detect Double-Debit Anomalies
-- Purpose: Identifies duplicate debited transactions (APPROVED or TIMEOUT_SUSPECT)
--          sharing identical PAN, Amount, and Trace Identifiers (STAN / RRN).
-- Domain: Payment Switching & Core Banking Reconciliation
-- ============================================================================

SELECT
    t1.pan,
    t1.stan,
    t1.rrn,
    t1.amount,
    COUNT(t1.id) AS duplicate_count,
    GROUP_CONCAT(t1.id) AS transaction_ids,
    GROUP_CONCAT(t1.status) AS statuses,
    GROUP_CONCAT(t1.created_at) AS timestamps
FROM transaction_logs t1
WHERE t1.mti = '0200'
  AND t1.status IN ('APPROVED', 'TIMEOUT_SUSPECT')
GROUP BY t1.pan, t1.stan, t1.rrn, t1.amount
HAVING COUNT(t1.id) > 1
ORDER BY duplicate_count DESC, t1.pan ASC;
