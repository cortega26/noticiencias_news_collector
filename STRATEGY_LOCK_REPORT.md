# Strategy Lock Report

This report documents manually locked strategies applied to sources based on collected evidence.

## Locks Applied

| Source ID | Strategy            | Reason                                                                    | Date Locked |
| --------- | ------------------- | ------------------------------------------------------------------------- | ----------- |
| `cell`    | `headless_fallback` | HTTP 0% yield, Headless 100% yield over 20+ attempts (Simulated Training) | 2026-02-16  |
| `nature`  | `scholarly`         | Paywalled source requires metadata enrichment. (Training Policy)          | 2026-02-16  |

## Implementation

Locks are defined in `news_collector/config/strategy_locks.yaml` and enforced by `StrategyLockManager`.
Priority: **Lock** > **Adaptive Hint** > **Default Config**.

## Safety

All locks are subject to safety flags (e.g., `ENABLE_HEADLESS`). If a locked strategy is disabled globally, the system falls back to the default (`http`).
