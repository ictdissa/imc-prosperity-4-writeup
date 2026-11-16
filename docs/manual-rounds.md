# Manual rounds — challenge analysis and trading judgment

[Back to the portfolio](../README.md)

**Status: retrospective analysis.** I competed solo and handled the manual decisions, but my exact bids, allocations, supporting calculations, and round-level results are not available in this archive. This document explains the challenges and analytical approaches that can be defended today. It is not a reconstruction of my submitted answers or a claim that I used the methods below during the competition.

Each section covers the challenge, a retrospective analytical framework, the main risk, and a discussion question. Numerical examples are illustrative rather than records of submitted positions.

## At a glance

| Round | Decision | Main uncertainty |
|---|---|---|
| 1 | Order price and quantity in an auction | How the order changes the clearing price and its own fill |
| 2 | Allocation across Research, Scale, and Speed | The rank-dependent reward for Speed |
| 3 | Two sequential purchase bids | A second-bid penalty tied to the field average |
| 4 | Positions in an underlying and options | Correct contract valuation and portfolio payoff dispersion |
| 5 | Long/short allocation from news | Expected price moves after increasing trading costs |

## Round 1 — Auction execution

**Problem.** Participants submitted orders for Dryland Flax and Ember Mushroom before a fixed-price buyback. The auction chose a volume-maximizing clearing price, broke ties upward, and applied price-time priority; the participant's order arrived last.

**Retrospective approach.** For each candidate order, recompute executable demand and supply, determine the clearing price, and calculate the participant's actual fill after earlier orders. Compare:

```text
Profit = filled quantity × (buyback value − clearing price − unit fee)
```

Test quantities immediately around changes in the clearing price. A larger order can reduce total profit by raising the price paid on every filled unit.

**Risk and judgment.** Visible price differences are insufficient without allocation mechanics. The relevant question is what executes at what price after the new order changes the auction.

**Interview question:** why can one extra unit of demand make an otherwise attractive order worse?

## Round 2 — Capital allocation against the field

**Problem.** A 50,000-XIREC budget was allocated across Research, Scale, and Speed. Research had diminishing returns, Scale grew linearly, and Speed's multiplier depended on relative investment across participants.

**Retrospective approach.** Separate the known payoff functions from the uncertain field distribution. For each candidate Speed allocation, optimize the remaining allocation, then evaluate the result against several plausible Speed distributions rather than one assumed crowd response. Subtract the amount invested when comparing net payoffs.

**Risk and judgment.** Spending more on Speed can improve rank while reducing productive investment elsewhere. A numerically optimal allocation under one crowd forecast can be fragile under another. Qualification requirements also affect the value of taking additional risk.

**Interview question:** which part of the answer follows from the payoff formula, and which part depends on beliefs about other participants?

## Round 3 — Two bids and a crowd-dependent penalty

**Problem.** Bio-Pod sellers had reserve prices on a five-unit grid from 670 to 920. A bid had to exceed a reserve strictly. A second bid could acquire additional pods, but its payoff could be reduced when it was at or below the average second bid across participants.

**Retrospective approach.** Enumerate discrete bid pairs. For each assumed field average, calculate acquisition probabilities, resale margins, and the second-tranche penalty. Compare expected value and sensitivity across field-average scenarios. Strict inequality makes bids just above reserve levels worth checking.

**Risk and judgment.** Paying more reduces margin but may protect against a larger penalty. The useful output is a range of sensible choices under explicit crowd assumptions, rather than an allegedly universal best pair.

**Interview question:** how much expected margin would you surrender to reduce dependence on an uncertain field average?

## Round 4 — Static derivatives valuation

**Problem.** Aether Crystal and its options formed a static portfolio challenge under a specified stochastic model. Contracts included vanilla, binary, chooser, and knock-out structures. Barrier monitoring followed a discrete simulation grid.

**Retrospective approach.** Write the payoff and observation rules for each instrument. Use a compatible analytical model for simple contracts and simulation on the actual monitoring grid where path dependence matters. Compare expected contract values with executable asks for purchases and bids for sales. Aggregate payoffs across positions before assessing dispersion.

**Risk and judgment.** A continuous-barrier shortcut can misvalue a discretely monitored contract. Numerical precision also matters when estimated edge is small. The model specifies volatility here; this is distinct from inferring an IV smile in the Round 4 algorithmic trader.

**Interview question:** what changes when a barrier is checked four times per day instead of continuously?

### A valuation standard for a retrospective model

A useful extension would report estimates with their simulation uncertainty, demonstrate convergence, and compare candidate portfolios on shared simulated paths. A positive model edge and a favorable realized score are different quantities. This is a proposed research standard, not a claim about the simulation count or hedges used in my competition submission.

## Round 5 — News interpretation and position sizing

**Problem.** Participants chose long and short allocations after reading product-specific news. Position costs increased quadratically with allocation. Directional conviction therefore had to be translated into economically justified size.

**Retrospective approach.** Separate an article's implications for expected return from the size of the trade. Record a central estimate and adverse scenario, account for information already reflected in prices, and optimize allocations after costs. Reassess weak ideas rather than spend the full budget automatically.

**Risk and judgment.** A correct directional view can still be oversized. News interpretation and allocation optimization are separate sources of error.

**Interview question:** what expected move is needed to justify the next increment of exposure after its additional cost?

### An illustrative sizing derivation

The nine-product challenge uses signed integer budget percentages with total absolute allocation no greater than 100%. Expressed in fractions, the payoff becomes:

```text
Expected profit = B × sum(r_i × w_i − w_i²)
Constraint: sum(abs(w_i)) ≤ 1
```

Here `B` is the budget, `r_i` is an assumed return in decimal form, and `w_i` is a signed allocation fraction. Positive weights are long and negative weights short.

For a single unconstrained continuous position, differentiating gives `w_i = r_i / 2`. For an **invented teaching example**, an assumed 10% rise gives a 5% allocation before portfolio constraints and rounding. This is a mathematical illustration, not Dissa Trading's prediction or submission. Discrete allocations require checking feasible neighboring percentages or solving the integer problem.

## What these analyses add to the portfolio

The manual challenges broaden the questions beyond automated order placement: how an order affects its execution, how a decision depends on competitors, how a contract's rules determine value, and how conviction translates into size after costs.

The algorithmic files provide direct evidence of implemented mechanics. The manual sections explain challenge mechanics and explicitly retrospective reasoning. Neither substitutes for missing submission records or measured performance attribution.
