# Statement stock source qualification

16 source columns each have a non-null independent consolidated-report amount comparison. These checks establish observed units and source line items, not full historical completeness or universal cross-company comparability.

| DSL | Source column | Evidence |
| --- | --- | --- |
| monetary_funds | money_cap | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json), [statement-stock-insurance-crosscheck.json](statement-stock-insurance-crosscheck.json) |
| accounts_receivable | accounts_receiv | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json) |
| notes_receivable | notes_receiv | [statement-stock-remaining-crosscheck.json](statement-stock-remaining-crosscheck.json) |
| other_receivables | oth_receiv | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json) |
| prepayments | prepayment | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json) |
| inventories | inventories | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json) |
| accounts_payable | acct_payable | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json) |
| contract_assets | contract_assets | [statement-stock-remaining-crosscheck.json](statement-stock-remaining-crosscheck.json) |
| contract_liabilities | contract_liab | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json), [statement-stock-insurance-crosscheck.json](statement-stock-insurance-crosscheck.json) |
| goodwill | goodwill | [statement-stock-insurance-crosscheck.json](statement-stock-insurance-crosscheck.json) |
| short_term_borrowings | st_borr | [statement-stock-insurance-crosscheck.json](statement-stock-insurance-crosscheck.json) |
| long_term_borrowings | lt_borr | [statement-stock-insurance-crosscheck.json](statement-stock-insurance-crosscheck.json) |
| bonds_payable | bond_payable | [statement-stock-insurance-crosscheck.json](statement-stock-insurance-crosscheck.json) |
| noncurrent_liabilities_due_1y | non_cur_liab_due_1y | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json) |
| other_equity_instruments | oth_eqt_tools | [statement-stock-remaining-crosscheck.json](statement-stock-remaining-crosscheck.json) |
| cash_equivalents | c_cash_equ_end_period | [statement-stock-unit-crosscheck.json](statement-stock-unit-crosscheck.json) |

Financial rows use consolidated report_type 1 and supported company categories 1/2/3/4. Each field retains a fixed source line item; empty supplier values remain missing even where an original company report contains an amount. No alternative column supplies missing values. contract_liabilities excludes category 3 because the observed supplier column maps to insurance contract liabilities. That boundary is enforced after latest-report selection in both readers.

The original four-category, annual/Q1 observations and the additional construction annual observation are saved separately. Contract collection completion, source null values, and inapplicability must not be conflated. Ticket 07 owns full-history coverage accounting.
