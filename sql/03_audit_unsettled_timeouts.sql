-- ============================================================================
-- SQL QA Audit Script 03: Audit Unsettled Timeout / Suspect Transactions
-- Purpose: Identifies financial transactions currently stuck in 'TIMEOUT_SUSPECT'
--          status that have not yet been successfully reversed by an MTI 0400 message.
-- Domain: Payment Switching Exception Management & Settlement Clearance
-- ============================================================================

SELECT
    s.id AS suspect_tx_id,
    s.pan,
    s.processing_code,
    s.amount,
    s.stan,
    s.rrn,
    s.terminal_id,
    s.response_code,
    s.status,
    s.notes,
    s.created_at AS suspect_timestamp
FROM transaction_logs s
WHERE s.mti = '0200'
  AND s.status = 'TIMEOUT_SUSPECT'
  AND NOT EXISTS (
      SELECT 1
      FROM transaction_logs r
      WHERE r.mti = '0400'
        AND r.stan = s.stan
        AND r.rrn = s.rrn
        AND r.status = 'APPROVED'
  )
ORDER BY s.created_at ASC;
