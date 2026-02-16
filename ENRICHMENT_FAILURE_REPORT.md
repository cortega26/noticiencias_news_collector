# Enrichment Failure Report (Session: db245e43-20260215-201747)

This report details sources that were successfully discovered (Stage A) but failed the enrichment quality check (Stage B).

| Source | Failure Type | Recommended Mode | Details |
| :--- | :--- | :--- | :--- |
| `cell` | Content Too Short | **headless** | HTTP 200 <br> Len: 234 <br> [Example](https://cell.com/cell/fulltext/S0092-8674(25)01504-1?rss=yes) |
| `science` | Paywall/Bot-Protection | **impossible (or headless+auth)** | HTTP 200 <br> Len: 61 <br> [Example](https://science.org/doi/abs/10.1126/science.aec2352?af=R) |
| `phys_org` | Content Too Short | **headless** | HTTP 200 <br> Len: 194 <br> [Example](https://phys.org/news/2026-02-bird-poo-fueled-peru-powerful.html) |
| `nejm` | Paywall/Bot-Protection | **impossible (or headless+auth)** | HTTP 200 <br> Len: 86 <br> [Example](https://nejm.org/doi/full/10.1056/NEJMoa2514824?af=R&rss=currentIssue) |
| `sciencedaily_top` | Content Too Short | **headless** | HTTP 200 <br> Len: 498 <br> [Example](https://sciencedaily.com/releases/2026/02/260213223926.htm) |
| `scitechdaily` | Content Too Short | **headless** | HTTP 200 <br> Len: 368 <br> [Example](https://scitechdaily.com/this-bonobo-just-did-something-scientists-thought-only-humans-could-do/) |
| `nature` | Paywall/Bot-Protection | **impossible (or headless+auth)** | HTTP 200 <br> Len: 132 <br> [Example](https://nature.com/articles/d41586-026-00476-1) |
| `uw_news` | Content Too Short | **headless** | HTTP 200 <br> Len: 249 <br> [Example](https://washington.edu/news/2026/02/11/qa-uw-course-uses-the-olympic-games-as-a-historical-lens/) |
| `uw_madison_news` | Content Too Short | **headless** | HTTP 200 <br> Len: 121 <br> [Example](https://news.wisc.edu/icecube-neutrino-observatory-gets-a-major-upgrade-beneath-the-ice/) |
| `michigan_news` | Content Too Short | **headless** | HTTP 200 <br> Len: 347 <br> [Example](https://news.umich.edu/betrayal-experiences-in-the-military-linked-to-difficulty-dealing-with-the-military-to-civilian-transition-for-veterans/) |
| `techxplore` | Content Too Short | **headless** | HTTP 200 <br> Len: 322 <br> [Example](https://techxplore.com/news/2026-02-llms-violate-boundaries-mental-health.html) |
| `harvard_gazette` | Empty/Stub (81 chars) | **headless** | HTTP 200 <br> Len: 81 <br> [Example](https://news.harvard.edu/gazette/story/2026/02/how-academia-can-help-america-heal/) |
| `medicalxpress` | Content Too Short | **headless** | HTTP 200 <br> Len: 226 <br> [Example](https://medicalxpress.com/news/2026-02-grand-small-tweaks-life.html) |
| `deepmind_blog` | Content Too Short (112 chars) | **headless** | HTTP 200 <br> Len: 112 <br> [Example](https://deepmind.google/blog/gemini-3-deep-think-advancing-science-research-and-engineering/) |
| `microsoft_research` | Content Too Short | **headless** | HTTP 200 <br> Len: 359 <br> [Example](https://microsoft.com/en-us/research/blog/rethinking-imitation-learning-with-predictive-inverse-dynamics-models/) |
| `reddit_science` | Content Too Short | **headless** | HTTP 200 <br> Len: 351 <br> [Example](https://reddit.com/r/science/comments/1r5ltvc/this_madeincanada_psychopath_test_doesnt_work_and/) |
| `openai_blog` | Content Too Short (148 chars) | **headless** | HTTP 200 <br> Len: 148 <br> [Example](https://openai.com/index/new-result-theoretical-physics) |
