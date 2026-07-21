"""Utilities for harmonizing per-domain and per-source rate limit overrides."""

from __future__ import annotations

from typing import Dict, Optional

from news_collector.config.settings import get_runtime_config


def _normalize_domain(domain: str) -> str:
    """Return a lowercase domain without port information."""
    if not domain:
        return ""
    return domain.split(":", 1)[0].lower()


def _candidate_domains(domain: str) -> list[str]:
    normalized = _normalize_domain(domain)
    if not normalized:
        return []
    candidates = [normalized]
    if normalized.startswith("www."):
        candidates.append(normalized[4:])
    else:
        candidates.append(f"www.{normalized}")
    return candidates


def resolve_domain_override(
    domain: str, overrides: Optional[Dict[str, float]] = None
) -> float:
    """Return the configured minimum delay (seconds) for a domain, if any."""

    cfg = get_runtime_config()
    config_overrides = (
        overrides
        if overrides is not None
        else cfg.rate_limiting_config.get("domain_overrides", {})
    )
    if not config_overrides:
        return 0.0

    for candidate in _candidate_domains(domain):
        if candidate in config_overrides:
            return float(config_overrides[candidate])
    return 0.0


def calculate_effective_delay(
    domain: str,
    robots_delay: Optional[float],
    source_min_delay: Optional[float],
) -> float:
    """Combine global, domain, robots.txt and source-specific delays."""

    cfg = get_runtime_config()
    base_delay = float(
        cfg.rate_limiting_config.get(
            "domain_default_delay", cfg.rate_limiting_config["delay_between_requests"]
        )
    )
    global_min = float(cfg.rate_limiting_config["delay_between_requests"])
    robots_component = float(robots_delay) if robots_delay is not None else 0.0
    source_component = float(source_min_delay) if source_min_delay is not None else 0.0
    domain_component = resolve_domain_override(domain)

    return max(
        base_delay, global_min, robots_component, domain_component, source_component
    )
