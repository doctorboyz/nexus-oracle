---
name: real-goal-vs-proxy-metrics
description: Trading strategy real goal is profit consistency, not arbitrary WR targets
type: project
---

## Real Goal vs Proxy Metrics

**Rule**: When proxy metrics (WR, PF, MaxDD) conflict with the real goal, the real goal wins.

**Real goal**: Profit consistently without blowing up (port ได้เรื่อยๆ และไม่แตก)

**Why**: WR ≥ 55% was set as a proxy for "good strategy". But at PF=1.64 and MaxDD=11.8%, the strategy IS profitable and safe even at WR=53%. The 2pp gap (53% vs 55%) has negligible impact on the real goal because:
- PF=1.64 means wins are 1.64x larger than losses
- MaxDD=11.8% means worst case is well under control
- WR=53% with high PF = reliable profit stream

**How to apply**: When evaluating trading strategies, always ask: "Does this metric gap actually impact the real goal of consistent profit without blowing up?" If not, accept the proxy shortfall and proceed.

**Context**: Human made this decision on 2026-04-29 for god-port trading agent (XAUUSD H1).