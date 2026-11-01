-- ============================================================================
-- SQL QA Audit Script 04: Daily Ledger Reconciliation
-- Purpose: Compares current customer balances against initial ledger balances,
--          sum of all financial debits (MTI 0200), and approved reversals (MTI 0400)
--          to guarantee zero ledger drift and detect unauthorized balance alterations.
-- Domain: Core Banking General Ledger Reconciliation & Audit
-- ============================================================================

WITH transaction_summary AS (
    SELECT
        pan,
        -- Gross debits: All financial transactions where balance was debited
        COALESCE(SUM(
            CASE
                WHEN mti = '0200'
                 AND status IN ('APPROVED', 'TIMEOUT_SUSPECT', 'REVERSED')
                 AND processing_code != '300000'
                THEN amount
                ELSE 0
            END
        ), 0) AS total_gross_debits,

        -- Gross refunds: All approved auto-reversals
        COALESCE(SUM(
            CASE
                WHEN mti = '0400'
                 AND status = 'APPROVED'
                THEN amount
                ELSE 0
            END
        ), 0) AS total_approved_reversals,

        -- Active debits currently reducing balance
        COALESCE(SUM(
            CASE
                WHEN mti = '0200'
                 AND status IN ('APPROVED', 'TIMEOUT_SUSPECT')
                 AND processing_code != '300000'
                THEN amount
                ELSE 0
            END
        ), 0) AS net_active_debits
    FROM transaction_logs
    GROUP BY pan
)
SELECT
    ca.pan,
    ca.cardholder_name,
    ca.initial_balance,
    COALESCE(ts.total_gross_debits, 0) AS total_gross_debits,
    COALESCE(ts.total_approved_reversals, 0) AS total_approved_reversals,
    (ca.initial_balance - COALESCE(ts.total_gross_debits, 0) + COALESCE(ts.total_approved_reversals, 0)) AS calculated_expected_balance,
    ca.balance AS actual_current_balance,
    (ca.balance - (ca.initial_balance - COALESCE(ts.total_gross_debits, 0) + COALESCE(ts.total_approved_reversals, 0))) AS discrepancy_amount,
    CASE
        WHEN ca.balance = (ca.initial_balance - COALESCE(ts.total_gross_debits, 0) + COALESCE(ts.total_approved_reversals, 0))
        THEN 'BALANCED'
        ELSE 'DISCREPANCY_DETECTED'
    END AS reconciliation_status
FROM card_accounts ca
LEFT JOIN transaction_summary ts ON ca.pan = ts.pan
ORDER BY ca.pan ASC;
