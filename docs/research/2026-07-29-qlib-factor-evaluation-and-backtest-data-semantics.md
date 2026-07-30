# Qlib Factor Evaluation and Backtest Data Semantics

Date: 2026-07-29

## Decision boundary

ThesisTrace V1 does not use Qlib or generate a Qlib Provider. This note remains
comparative research evidence for price, label, and backtest semantics; it is
not a V1 runtime or data-format contract. See ADR-0024.

## Question

What price data does Microsoft Qlib actually use for factor evaluation and strategy backtesting, and how do its adjusted prices, labels, execution prices, `$factor`, share amounts, and China A-share lot sizes relate?

## Scope and version

This note treats the locally installed package as the runtime source of truth and Microsoft/qlib as the upstream source of truth.

- `histack-data` pins `pyqlib==0.9.7` in
  `/Users/koltenluca/code-github/histack-data/pyproject.toml:19-23`.
- The environment reports both the distribution version and `qlib.__version__` as
  `0.9.7`; its package root is
  `/Users/koltenluca/code-github/histack-data/.venv/lib/python3.12/site-packages/qlib`.
- Qlib tag `v0.9.7` resolves to commit
  [`da920b7f954f48ab1bb64117c976710de198373e`](https://github.com/microsoft/qlib/tree/da920b7f954f48ab1bb64117c976710de198373e).
- SHA-256 comparisons of the installed and tagged versions of
  `qlib/backtest/exchange.py`, `qlib/contrib/data/handler.py`, and
  `qlib/contrib/eva/alpha.py` are identical. The line anchors below therefore
  describe the installed runtime, not merely current upstream `main`.

## Conclusions

1. Qlib's canonical OHLCV fields are **adjusted data in Qlib's own normalized
   coordinate system**, not a universal `raw` / Chinese `qfq` / Chinese `hfq`
   choice. The first valid `$close` is normalized to 1; the other OHLC fields
   are scaled by the same base, while volume is adjusted inversely. The exact
   corporate-action adjustments still depend on the upstream data source.
2. Qlib defines `$factor` as:

   ```text
   factor = adjusted_price / original_price
   original_price = adjusted_price / factor
   ```

3. The standard Alpha360/Alpha158 label is
   `Ref($close, -2) / Ref($close, -1) - 1`: the return from next session's close
   to the following session's close. This is a default, not a system-wide
   invariant; handlers may override it.
4. Factor evaluation consumes a prediction/score and a separately generated
   label. Strategy backtesting consumes a strategy, an Exchange, and a configured
   `deal_price`. Qlib does not automatically bind the factor-evaluation label to
   the backtest execution price.
5. `Exchange.deal_price` uses the configured Qlib field directly (for example,
   `$close`, `$open`, or `$vwap`). It does **not** silently convert it to
   `$close / $factor`. End-of-day portfolio valuation is based on `$close`.
6. Qlib order/position amounts are adjusted amounts. The conversion is:

   ```text
   actual_shares = adjusted_amount * factor
   adjusted_amount = actual_shares / factor
   adjusted_amount_per_lot = trade_unit / factor
   ```

   This makes `adjusted_price * adjusted_amount` equal
   `original_price * actual_shares`. With the China default `trade_unit=100`,
   Qlib rounds the actual-share equivalent to 100-share lots.

## 1. What “adjusted” means in Qlib

The official data documentation says that Qlib's price and volume data are
adjusted, that adjustment methods may differ by source, and that the first
trading day's price is normalized to 1. It explicitly documents
`$close / $factor` as the recovery path to the original close:

- [Official data documentation: adjusted price](https://qlib.readthedocs.io/en/latest/component/data.html#adjusted-price)
- Local upstream mirror:
  `/Users/koltenluca/code-github/qlib/docs/component/data.rst:52-60`
  and `:180-197`.

The official Yahoo collector shows one concrete implementation:

- `scripts/data_collector/yahoo/collector.py:452-473` computes
  `factor = adjclose / close`, multiplies price fields by the factor, and divides
  volume by it.
- `scripts/data_collector/yahoo/collector.py:491-507` then normalizes fields
  against the first valid adjusted close.
- `scripts/data_collector/utils.py:697-784`, especially `:745-753`, explains
  that Yahoo daily `adjclose` contains dividend and split adjustments.

Tagged source:

- [`collector.py` v0.9.7, factor and field adjustment](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/scripts/data_collector/yahoo/collector.py#L452-L473)
- [`collector.py` v0.9.7, first-day normalization](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/scripts/data_collector/yahoo/collector.py#L491-L507)

Consequences:

- Calling Qlib's stored field “raw price” is wrong.
- Calling it categorically `qfq` or `hfq` is also too strong. Qlib specifies an
  adjusted, first-day-normalized representation; the upstream source determines
  the economic adjustment series.
- A global normalization scalar cancels in a return ratio, but the
  corporate-action adjustment does not.
- The phrase “raw stock returns” in Qlib's long-short evaluator means
  stock-return labels before Handler processor transformations (for example,
  before cross-sectional rank normalization), not returns computed from
  unadjusted prices.

## 2. Factor evaluation: score versus label

### Default labels

Both Alpha360 and Alpha158 default to:

```text
Ref($close, -2) / Ref($close, -1) - 1
```

The default is installed at:

- `/Users/koltenluca/code-github/histack-data/.venv/lib/python3.12/site-packages/qlib/contrib/data/handler.py:89-95`
  for Alpha360.
- `/Users/koltenluca/code-github/histack-data/.venv/lib/python3.12/site-packages/qlib/contrib/data/handler.py:151-157`
  for Alpha158.

Tagged source:

- [`handler.py` v0.9.7, Alpha360](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/contrib/data/handler.py#L89-L95)
- [`handler.py` v0.9.7, Alpha158](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/contrib/data/handler.py#L151-L157)

The expression is evaluated at each sample date `t` as:

```text
close[t+2] / close[t+1] - 1
```

It is therefore a one-session forward close-to-close return with one session of
execution lag. Because the constructor accepts a supplied `label`, this is only
the contrib handler default.

The official LSTM/Alpha158 workflow uses the same label and separately configures
the strategy backtest:

- [`workflow_config_lstm_Alpha158.yaml` v0.9.7, lines 27-52](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/examples/benchmarks/LSTM/workflow_config_lstm_Alpha158.yaml#L27-L52)

### Evaluation path

`SigAnaRecord` loads prediction and label artifacts, joins them, and computes IC
and Rank IC via `calc_ic`; optionally it runs long-short analysis:

- Installed
  `/Users/koltenluca/code-github/histack-data/.venv/lib/python3.12/site-packages/qlib/workflow/record_temp.py:296-355`.
- `calc_ic` computes per-date Pearson and Spearman correlations:
  `/Users/koltenluca/code-github/histack-data/.venv/lib/python3.12/site-packages/qlib/contrib/eva/alpha.py:160-183`.
- Long-short evaluation expects a stock-return label:
  `/Users/koltenluca/code-github/histack-data/.venv/lib/python3.12/site-packages/qlib/contrib/eva/alpha.py:71-113`.

Tagged source:

- [`record_temp.py` v0.9.7, Signal Analysis](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/workflow/record_temp.py#L296-L355)
- [`alpha.py` v0.9.7, IC and Rank IC](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/contrib/eva/alpha.py#L160-L183)

Thus factor evaluation does not obtain a return from `Exchange.deal_price`.
Its return semantics come from the dataset handler's label expression.

## 3. Strategy backtest: Exchange execution and valuation prices

`Exchange` accepts either one deal-price field for both sides or a two-element
buy/sell pair. Missing `$` prefixes are added automatically. The documented
examples are `$close`, `$open`, and `$vwap`:

- Installed `qlib/backtest/exchange.py:38-68` and `:135-164`.
- [`exchange.py` v0.9.7, constructor contract](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L28-L68)
- [`exchange.py` v0.9.7, configured buy/sell fields](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L135-L178)

At execution time:

- `get_deal_price` returns the configured field and falls back to `$close` when
  it is missing, NaN, or non-positive:
  installed `qlib/backtest/exchange.py:494-514`;
  [tagged source](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L494-L514).
- Execution obtains `trade_price` from `get_deal_price`, obtains `$factor`
  separately, rounds the adjusted amount, and calculates
  `trade_val = adjusted_amount * adjusted_price`:
  installed `qlib/backtest/exchange.py:859-952`;
  [tagged source](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L859-L952).
- End-of-day account valuation uses `$close`, not `deal_price`:
  installed `qlib/backtest/exchange.py:28-35` and `:475-482`.

The default China-region configuration is `trade_unit=100` and
`deal_price="close"`:

- Installed `qlib/config.py:295-310`.
- [`config.py` v0.9.7, China defaults](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/config.py#L295-L310).

The important boundary is that `deal_price="close"` means Qlib's adjusted
`$close` coordinate. `Exchange` does not first recover the original close.

## 4. `$factor`, real shares, and lot rounding

Order creation explicitly describes `amount` as an **adjusted trading amount**:

- Installed `qlib/backtest/decision.py:154-203`, especially `:176-196`.
- [`decision.py` v0.9.7, adjusted order amount](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/decision.py#L154-L203).

`Exchange` then applies the factor:

- `get_factor`: installed `qlib/backtest/exchange.py:516-532`;
  [tagged source](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L516-L532).
- One actual trading lot corresponds to adjusted amount `trade_unit / factor`:
  installed `qlib/backtest/exchange.py:728-759`;
  [tagged source](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L728-L759).
- Rounding first maps adjusted amount to its actual-share equivalent, rounds to
  `trade_unit`, and maps back:
  installed `qlib/backtest/exchange.py:761-784`;
  [tagged source](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L761-L784).

Example:

```text
factor = 0.02
adjusted_price = 0.20
original_price = 0.20 / 0.02 = 10.00

actual_shares = 100
adjusted_amount = 100 / 0.02 = 5,000

adjusted notional = 0.20 * 5,000 = 1,000
original notional = 10.00 * 100   = 1,000
```

If `$factor` is absent while `$close` is present, `Exchange` enters its
“adjusted price mode” and disables trade-unit rounding:

- Installed `qlib/backtest/exchange.py:221-232`.
- [`exchange.py` v0.9.7, missing-factor behavior](https://github.com/microsoft/qlib/blob/da920b7f954f48ab1bb64117c976710de198373e/qlib/backtest/exchange.py#L221-L232).

In that case Qlib can still backtest in adjusted coordinates, but it cannot
faithfully enforce an actual 100-share lot boundary.

## 5. Reference lessons for ThesisTrace

Qlib separates three contracts:

| Contract | Source of semantics |
|---|---|
| Model features | Handler feature expressions over Qlib fields |
| Factor evaluation return | Handler label expression |
| Strategy execution/valuation | Exchange `deal_price`, `$close`, delay, costs, constraints, and `$factor` |

ThesisTrace V1 does not reuse these Qlib contracts, but its own bounded research
runtime must still keep the corresponding semantics separate. A frozen Research
Definition should therefore record at least:

- the dataset release and adjustment convention;
- the exact evaluation label expression, horizon, and lag;
- buy and sell `deal_price` fields;
- execution delay/timing;
- valuation field;
- actual-share trade-unit rule and the chosen adjusted-return treatment of
  company actions.

These lessons do not require a Qlib Provider, Qlib `$factor`, or Qlib runtime.

The current `histack-data` working tree uses
`Ref($close, -horizon) / $close - 1` in
`src/thesistrace/run_layer/research_inputs.py:50-58`. That differs from the Qlib
Alpha158/Alpha360 default because it begins at `t` rather than `t+1`. This is not
intrinsically invalid, but it is a material research-definition choice and
should not be described as “the Qlib default.” Because `histack-data` is
currently a working-tree snapshot, this comparison is local implementation
evidence, not a claim about a released ThesisTrace version.

## Sources

Primary sources only:

- [Microsoft Qlib data documentation](https://qlib.readthedocs.io/en/latest/component/data.html)
- [Microsoft/qlib v0.9.7 source tree](https://github.com/microsoft/qlib/tree/da920b7f954f48ab1bb64117c976710de198373e)
- [pyqlib 0.9.7 on PyPI](https://pypi.org/project/pyqlib/0.9.7/)
- Local installed `pyqlib==0.9.7` source under
  `/Users/koltenluca/code-github/histack-data/.venv/lib/python3.12/site-packages/qlib`
- Local official checkout under `/Users/koltenluca/code-github/qlib`
