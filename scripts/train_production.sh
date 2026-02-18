#!/bin/bash
set -e

# ==========================================
# Production Training Run (Clean Metrics)
# ==========================================
# Role: Populate data/metrics/production/ with trustworthy evidence.
# Policy: HTTP First, Fail-Closed, Strict Attribution.

# 1. Environment Configuration
export RUN_ENVIRONMENT="production"
export ENABLE_HEADLESS="true"
export ENABLE_PROXY="true"
export ENABLE_ADAPTIVE_OPTIMIZER="true"

# Safety Limits
export HEADLESS_MAX_SOURCES_PER_RUN=10
export HEADLESS_MAX_TOTAL_SECONDS_PER_RUN=300
export PROXY_MAX_TOTAL_REQUESTS_PER_RUN=50
# Bypass Cooldowns for forced training
export ENABLE_CIRCUIT_BREAKER="false"

# Training Cohort
SOURCES="cell nature science nejm phys_org medicalxpress techxplore sciencedaily_top openai_blog deepmind_blog google_research microsoft_research wired stat_news space_com new_scientist"

echo "Using Sources: $SOURCES"
echo "Environment: $RUN_ENVIRONMENT"

# 2. Execution Loop
for i in {1..3}; do
    echo ""
    echo ">>> Training Cycle $i/3 <<<"
    echo "--------------------------"
    python3 scripts/run_collector.py --sources $SOURCES
    # Small sleep between cycles to separate logs/timestamps slightly
    sleep 2
done

# 3. Verification Cycle
echo ""
echo ">>> Verification Cycle (Stability Check) <<<"
echo "------------------------------------------"
python3 scripts/run_collector.py --sources $SOURCES
