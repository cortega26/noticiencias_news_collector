# Production Training Report

**Status:** Completed
**Sources Analyzed:** 10

## 1. Yield & Success Rates

Columns: T=Total, Pub=Publishable, Yield=Pub/T

      source_id  total_enrichment_attempted  total_publishable  yield_pct  http_rate  headless_rate
  new_scientist                          50                 25       50.0      100.0            0.0
      stat_news                           4                  2       50.0      100.0            0.0
          wired                          50                 25       50.0      100.0            0.0
      space_com                          40                 20       50.0      100.0            0.0
google_research                          50                 25       50.0      100.0            0.0
           cell                          60                 20       33.3        0.0          100.0
    openai_blog                          75                 20       26.7        0.0          100.0
  deepmind_blog                          10                  0        0.0      100.0            0.0
        science                          50                  0        0.0        0.0            0.0
           nejm                          40                  0        0.0        0.0            0.0

## 2. Headless Impact (Lift)

  source_id  http_rate  headless_rate  headless_attempts
openai_blog        0.0          100.0                 25
       cell        0.0          100.0                 20

## 3. Strategy Lock Recommendations

Criteria: >5 attempts AND (Headless Yield > HTTP Yield + 20% OR HTTP Yield == 0)

- **openai_blog**: LOCK to `headless_fallback` (HTTP: 0.0%, Headless: 100.0%)
- **cell**: LOCK to `headless_fallback` (HTTP: 0.0%, Headless: 100.0%)
