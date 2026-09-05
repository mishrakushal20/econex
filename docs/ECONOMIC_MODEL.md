# ECONEX — Economic Model

All monetary values are integer **paise** (1 INR = 100 paise) throughout
the system. Floats only ever appear at the UI boundary
(`app/core/money.py::to_paise`) and in `P_conv`/`EOV` (which are inherently
fractional by definition — EOV is an *expected value*, not a transacted
amount).

## Locked formula

```
ExpectedContribution = (finalPrice − cost − deliveryCost) × quantity
IncentiveCost         = cashback
EOV                   = P_conv × ExpectedContribution − IncentiveCost
```

No risk adjustment, no future value, no hidden penalty, no undocumented
multiplier. Discount is already reflected in `finalPrice`, so it flows into
`ExpectedContribution` — it is deliberately **not** subtracted again in
`EOV`'s incentive-cost term. See `app/core/economic_engine.py`.

## Incentive budget rule (locked, see docs/DECISIONS.md for the reconciliation)

```
Incentive budget consumption = discount + cashback
```

This is checked in `app/core/policy_engine.py`, check #5:

```
incentive_spend_to_date + discount + cashback <= incentive_budget
```

**This is intentionally a different number from EOV's `IncentiveCost`.**
Budget accounting tracks total merchant giveaway (both the price cut and
any cashback); EOV's incentive cost tracks only the cash that leaves the
merchant's pocket *after* the sale closes at `finalPrice` (a discount isn't
a separate cash outflow — it's already priced into the contribution). See
`docs/DECISIONS.md` for the full history of how this was reconciled after
a genuine contradiction was found between an earlier draft and the
product's own worked examples.

## Conversion probability heuristic

**Synthetic. Deterministic. Not a trained model — never described as one.**

```
budget_fit        = clamp((buyer_budget − final_price) / buyer_budget, -1, 1)
concession_signal = (base_price − final_price + cashback) / base_price
urgency_term       = 1.0 if buyer explicitly requested expedited delivery, else 0
raw_score         = 2.5·budget_fit + 1.5·concession_signal + 1.0·urgency_term
P_conv            = 1 / (1 + e^(−2·raw_score))
```

Properties (all unit-tested in `tests/test_conversion_heuristic.py`):
bounded in the open interval (0,1), monotonically decreasing in
`final_price` (holding everything else fixed), fully reproducible, no
hidden state.

**Implementation decision**: the doc specifies `urgency_term = 0 unless a
delivery preference is explicitly stated` but does not give the non-zero
value. `1.0` was chosen to match the other two signals' weight class; this
choice does not affect any of the documentation's worked P_conv values,
since none of them involve an expedited-delivery request.

## Worked example — and its real, verified outcome

Using the documentation's own Table 10 fixture (Wireless Earbuds X200,
`base_price=₹8,000`, `cost=₹4,500`, `delivery_cost=₹50`,
`margin_floor=₹2,000`, `max_discount=₹800`, `max_cashback=₹500`,
`incentive_budget=₹10,000`, `incentive_spend_to_date=₹9,800`,
`approval_threshold=₹1,000`; buyer budget `₹6,800`, asks for `₹6,800`):

- **19 candidates generated** (3 price steps × 3 cashback steps × 2
  delivery options, plus the buyer's own ask as an anchor).
- Under the **locked** discount+cashback budget rule, only **2 of 19 are
  feasible**: the two zero-discount, zero-cashback, full-price candidates.
  Remaining budget headroom is `₹10,000 − ₹9,800 = ₹200` — smaller than
  the smallest non-zero discount step (`₹400`) or cashback step (`₹250`).
- **Selected: ₹8,000, standard delivery.** Contribution `₹3,450`,
  `P_conv ≈ 0.2927`, `EOV ≈ ₹1,009.82`.
- **Decision: COUNTER** (buyer asked ₹6,800; merchant can't afford to move
  off list price given the budget already committed elsewhere).

This is reproduced end-to-end in
`tests/test_hero_scenario_end_to_end.py` and
`tests/test_negotiation_service_integration.py`, both running the real
code path against a real SQLite DB. Full reconciliation writeup, including
why this differs from the documentation's own illustrative narrative (which
assumed the superseded cashback-only budget rule): `docs/DECISIONS.md`.
