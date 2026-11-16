# Results, attribution, and scope

[Back to the portfolio](../README.md)

## Competition result

| Item | Value | Basis |
|---|---|---|
| Competition | IMC Prosperity 4 | Source-file labels and official event website |
| Team | Dissa Trading | Confirmed by the participant |
| Entry | Solo participant | Confirmed by the participant |
| Global overall rank | 188th | Participant-reported |
| Hong Kong placement | Top 3 | Participant-reported; no exact regional rank asserted |
| Participating teams | 18,803 | [Official IMC Prosperity website](https://prosperity.imc.com/) |
| Approximate share of field | Top 1.0% | `188 / 18,803 × 100 ≈ 0.99984%` |

The percentile describes placement relative to all participating teams, using the field size above. It does not describe the proportion of teams completing every round. A top-three Hong Kong finish is not a claim of third place globally or of winning a regional award.

No leaderboard export, certificate, or result screenshot was supplied with these source files. The reported placement is retained as the participant's achievement; it is not independently verified by the Python programs. Official competition information was checked on November 16, 2026.

## What the result does and does not establish

The stated 188th placement is the overall competition result. It is not presented as an algorithmic-only rank. The event includes algorithmic and manual challenges. This repository documents the supplied Round 3–5 algorithms and a separate retrospective analysis of the five manual challenges.

There are no per-round P&L figures, Sharpe ratios, drawdown measurements, trading-volume claims, or comparisons against other strategies in this repository. Source comments describing successful local or official replay are not treated as reproduced empirical results.

## Authorship and team attribution

The participant competed **solo** under the name **Dissa Trading** and confirmed responsibility for strategy research, Python implementation, backtesting, and manual-trading decisions. The portfolio describes that end-to-end ownership. No academic affiliation has been added.

The source files are the participant-supplied versions. Their original filenames and SHA-256 checksums are recorded in [the source manifest](source-manifest.json). Repository names are simplified for navigation; the Python contents are unchanged.

Backtesting was part of the participant's development workflow. No replay was run while preparing this documentation, and the development backtest data and outputs are not included. That distinction separates work performed during the competition from the checks reproducible from this archive.

## Manual-round attribution

The participant confirmed responsibility for manual trading but does not recall exact submissions. The manual chapter explains challenge mechanics and presents analytical frameworks retrospectively. It does not assert that the participant used a particular solver, forecast, simulation, bid pair, hedge, allocation, or number of scenarios during the competition. No manual scores have been added.

The worked sizing example is illustrative. [Manual analysis](manual-rounds.md)

## Repository status

The GitHub repository is public: [ictdissa/imc-prosperity-4-writeup](https://github.com/ictdissa/imc-prosperity-4-writeup). The original strategy files are preserved unchanged, with separate documentation for their operation and the retrospective manual analysis.

## Documentation scope

Included:

- Recruiter-readable explanations of the Round 3–5 approaches.
- Original supplied trader implementations.
- Detailed formulas, parameter tables, examples, and code behavior notes.
- Retrospective manual-challenge analysis and illustrative calculations.
- Runtime requirements and limits of reproducibility.

Not included in the supplied material:

- Round 1–2 implementations or manual challenge submissions.
- A competition runtime, market-data archive, or recorded backtest output.
- Confirmed position histories or a breakdown explaining the final overall score.

The examples illustrate decision rules. They are not reconstructed actual trades or realized returns.
