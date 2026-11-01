-- ============================================================================
-- SQL QA Audit Script 02: Detect Orphan Reversals
-- Purpose: Identifies reversal requests (MTI 0400) that have no matching original
--          financial transaction (MTI 0200) or where the original was never debited.
-- Domain: Payment Switching & Reversal Auditing
-- ============================================================================

SELECT
    rev.id AS reversal_tx_id,
    rev.mti AS reversal_mti,
    rev.pan,
    rev.amount,
    rev.stan,
    rev.rrn,
    rev.terminal_id,
    rev.response_code AS reversal_rc,
    rev.status AS reversal_status,
    rev.created_at AS reversal_time,
    orig.id AS matched_original_id,
    orig.status AS matched_original_status
FROM transaction_logs rev
LEFT JOIN transaction_logs orig
    ON rev.stan = orig.stan
   AND rev.rrn = orig.rrn
   AND orig.mti = '0200'
WHERE rev.mti = '0400'
  AND (
      orig.id IS NULL
      OR rev.status = 'ORPHAN_REJECTED'
      OR orig.status NOT IN ('APPROVED', 'TIMEOUT_SUSPECT', 'REVERSED')
  )
ORDER BY rev.created_at DESC;
