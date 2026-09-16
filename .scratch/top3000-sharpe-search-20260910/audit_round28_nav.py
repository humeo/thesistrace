"""Recompute selected complete native paths independently with Decimal arithmetic."""
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parent
output = ROOT / "round28-nav-audits.json"
records = json.loads(output.read_text()) if output.exists() else {}
for rid in sys.argv[1:]:
    result = json.loads((ROOT/"results"/f"{rid}.json").read_text())
    data = json.loads((ROOT/"observations"/f"{rid}.json").read_text())
    observations = data["items"]
    assert data["next_cursor"] is None
    sessions = [o["session"] for o in observations]
    assert sessions == sorted(set(sessions))
    assert len(sessions) == result["run"]["progress"]["total_research_sessions"]
    reported = result["summary"]["metrics"]
    with localcontext() as ctx:
        ctx.prec = 50
        nav = [Decimal(o["net_nav"]) for o in observations]
        assert all(v.is_finite() and v > 0 for v in nav)
        returns = [nav[i]/nav[i-1]-1 for i in range(1,len(nav))]
        count = Decimal(len(returns))
        mean = sum(returns)/count
        deviation = (sum((v-mean)**2 for v in returns)/(count-1)).sqrt()
        sharpe = mean/deviation * Decimal(252).sqrt()
        peak = nav[0]; peak_session = sessions[0]; drawdown = Decimal(0); worst = None
        for session, value in zip(sessions, nav):
            if value > peak:
                peak = value; peak_session = session
            current = 1-value/peak
            if current > drawdown:
                drawdown = current; worst = [peak_session, session]
        capital = Decimal(result["summary"]["initial_cash_cny"])
        net_return = nav[-1]/capital-1
        fees = sum(Decimal(o["transaction_cost_cny"]) for o in observations)
        errors = {"sharpe":abs(float(sharpe)-reported["sharpe"]),
            "maximum_drawdown":abs(float(drawdown)-reported["maximum_drawdown"]["value"]),
            "net_return":abs(float(net_return)-reported["net_cumulative_return"]),
            "fees_cny":abs(float(fees)-reported["transaction_costs"]["cumulative_amount"])}
        assert all(v < 1e-8 for v in errors.values()), errors
        assert worst == [reported["maximum_drawdown"]["peak_session"], reported["maximum_drawdown"]["trough_session"]]
        record = {"run_id":rid, "checked_at":datetime.now(timezone.utc).isoformat(),
            "observations":len(nav),"return_intervals":len(returns),"pages":data.get("pages"),
            "native_capital_cny":str(capital),"recomputed":{"sharpe":str(sharpe),"maximum_drawdown":str(drawdown),
            "net_return":str(net_return),"fees_cny":str(fees),"peak_trough_sessions":worst},
            "absolute_errors":errors,"method":"50-digit Decimal; adjacent NAV returns only, sampleSDsqrt252, running-peak drawdown, exact sum of recorded fees. No extra zero return, capital scaling, new backtest or broker-ledger claim."}
        records[rid] = record
        print(json.dumps(record,ensure_ascii=False))
output.write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n")
