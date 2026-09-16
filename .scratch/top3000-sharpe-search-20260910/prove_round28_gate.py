"""Independent constructive check: positive Rank IC is not necessary for TopN profit."""
import json
from fractions import Fraction
from pathlib import Path

from thesistrace.research_kernel.factor import factor_values

ROOT = Path(__file__).resolve().parent
scores = list(range(1, 6))
returns = [Fraction(0), Fraction(3, 100), Fraction(2, 100), Fraction(-2, 100), Fraction(1, 100)]
ranks = [sorted(returns).index(v) + 1 for v in returns]
distance = sum((a-b)**2 for a, b in zip(scores, ranks))
rho = 1 - Fraction(6*distance, 5*(5**2-1))
assert rho == Fraction(-1, 5)
alpha = [float(v) for v in scores for _ in range(600)]
labels = [float(v) for v in returns for _ in range(600)]
result = factor_values(alpha, labels)
assert result["rank_ic"] == float(rho)
assert result["quantile_returns"]["q5"] == .01
assert result["top_bottom_return"] == .01
assert result["quantile_reason"] is None

# Twenty-session labels, compounded independently from alternating daily returns.
compound = [(1+r)**10 * (1+2*r)**10 - 1 for r in returns]
assert [sorted(compound).index(v)+1 for v in compound] == ranks
twenty = factor_values(alpha, [float(v) for v in compound for _ in range(600)])
assert abs(twenty["rank_ic"] + .2) < 1e-12
ledgers = []
for n, shares in ((10, 900), (20, 400)):
    principal = 100000
    purchase_value = n * shares * 10
    buy_fee = Fraction(purchase_value, 1000)
    cash = principal - purchase_value - buy_fee
    terminal_sale = Fraction(purchase_value) * Fraction(101,100) * Fraction(102,100)
    sell_fee = terminal_sale / 1000
    terminal = cash + terminal_sale - sell_fee
    assert cash >= 0 and terminal > principal
    ledgers.append({"holdings_count":n,"shares_each":shares,"initial_cash_cny":principal,
        "cash_after_purchase":str(cash),"terminal_cash_exact":str(terminal),
        "terminal_cash_cny":float(terminal),"profit_cny":float(terminal-principal)})
proof = {"universe_size":3000,"groups":5,"names_per_group":600,
    "score_group_ranks":scores,"return_group_ranks":ranks,"rank_distance_sum":distance,
    "rank_ic_exact":str(rho),"native_factor":result,"native_twenty_day_factor":twenty,
    "two_period_ledgers":ledgers,
    "limitations":"Artificial mathematical counterexample. Assumed0.1% fees per side, not native/broker fees; no Sharpe estimate, empirical strategy or future-profit claim. Original QS27 gate remains closed; QS28 is a separately frozen uniform account audit."}
(ROOT/"round28-gate-proof.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"rank_ic":result["rank_ic"],"q5":result["quantile_returns"]["q5"],
    "paired_spread":result["top_bottom_return"],"ledgers":ledgers},ensure_ascii=False))
