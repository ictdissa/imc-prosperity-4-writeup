# Running and reviewing the traders

[Back to the portfolio](../README.md)

## What these files are

Each file implements a competition-facing `Trader` class. The exchange calls `Trader.run(state)` with the latest order books, positions, recent trades, and serialized memory. The trader returns orders, a zero conversion request, and updated memory.

These are strategy submissions, not command-line programs. Running `python strategies/round_4.py` does not start a trading simulation.

## Requirements

- **Python 3.10 or later** for the combined repository: the Round 5 file uses modern union type annotations.
- The competition's compatible **`datamodel` module**, including the order and trading-state classes expected by the submissions.
- A **compatible exchange simulator or backtester** that supplies trading states and applies fills and position limits.
- Appropriate **market data** for a historical replay.

The supplied files otherwise use Python's standard library. Round 5 optionally imports `prosperity4bt.data` to register product limits for a local backtester; a failed optional import is caught. That compatibility branch is not needed to understand the strategy.

## Review without a simulator

Read the [portfolio summary](../README.md) first, then the [technical reference](strategy-reference.md). The reference maps each mechanism to source functions.

You can check Python syntax without importing the unavailable competition runtime:

```bash
python3 - <<'PY'
import ast
from pathlib import Path

for path in sorted(Path("strategies").glob("*.py")):
    ast.parse(path.read_text(), filename=str(path))
    print(f"Syntax OK: {path}")
PY
```

This checks parsing only. It does not validate order acceptance, position accounting, strategy profitability, or runtime compatibility.

## Replaying strategies

Load one trader at a time into a compatible simulator using that simulator's documented submission interface. Supply the corresponding round's products, limits, trading states, and market data. Compare submitted orders with actual fills and positions rather than treating every submitted order as executed.

No backtester, dependency lockfile, or replay command is included because a complete tested runtime was not provided. No backtest was run while preparing this repository.

## Source integrity

All three Python files are byte-for-byte copies of the supplied versions. Their checksums are in [source-manifest.json](source-manifest.json). This is a writeup and archival package; documentation does not silently repair or refactor the submitted algorithms.
