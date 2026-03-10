import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from news_collector.config.settings import CONFIG
from news_collector.infrastructure.llm.model_registry import get_model_for_stage
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.storage.models import Article
from news_collector.utils.logger import get_logger

from .basic_scorer import BasicScorer
from .heuristic_scorer import HeuristicScorer

logger = get_logger().create_module_logger(__name__)

CACHE_DB_PATH = Path("data/cache_cognitive.db")


class CognitiveScorer(BasicScorer):
    """
    Advanced Scorer using a Hybrid Strategy (LLM + Heuristic + Cache).

    Strategy:
    1. Check Cache (SQLite) for existing cognitive scores.
    2. If miss, check LLM Health & Budget.
    3. If healthy, Call LLM (Batched).
    4. If unhealthy/timeout/budget-exhausted, Fallback to HeuristicScorer.
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        llm_client: OllamaProvider | None = None,
    ):
        print(
            f"{datetime.now().strftime('%H:%M:%S')} | DEBUG: CognitiveScorer INITIALIZED (Hybrid Mode)"
        )

        # 1. Weights Setup
        default_weights = {
            "source_credibility": 0.20,
            "recency": 0.20,
            "content_quality": 0.20,
            "cognitive_engagement": 0.40,
        }
        final_weights = weights.copy() if weights else default_weights

        # Ensure 'engagement_potential' is used internally to match BaseScorer and config
        if "cognitive_engagement" in final_weights:
            final_weights["engagement_potential"] = final_weights.pop(
                "cognitive_engagement"
            )

        super().__init__(weights=final_weights)

        # 2. Components
        # Use provider directly
        if llm_client is None:
            model = get_model_for_stage("scoring", config=CONFIG, logger=logger)
            self.llm: OllamaProvider = OllamaProvider(
                api_url=CONFIG.ollama.api_url, model=model
            )
        else:
            self.llm = llm_client
        self.heuristic = HeuristicScorer()
        self.version = "2.2-hybrid-unified"

        # 3. Budget Config
        self.max_cycle_budget_sec = 45.0
        self.batch_timeout_sec = 20.0
        self.cycle_start_time = time.time()
        self.llm_calls_count = 0
        self.heuristic_used_count = 0
        self.is_llm_healthy = True

        # 4. Cache Init
        self._init_cache()

    def _init_cache(self):
        try:
            CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            from contextlib import closing

            with closing(sqlite3.connect(CACHE_DB_PATH)) as conn:  # noqa: SIM117
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS cognitive_scores (
                            key TEXT PRIMARY KEY,
                            score REAL,
                            details TEXT,
                            reasoning TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_created_at ON cognitive_scores(created_at)"
                    )
        except Exception as e:
            logger.error(f"Failed to init cognitive cache: {e}")

    def _get_cache_key(self, article: Any) -> str:
        # Simple key: Title + URL hash.
        # In prod, maybe hash inputs. For now, string concat is fine for uniqueness.
        safe_url = article.url or "no_url"
        safe_title = article.title or "no_title"
        return f"{safe_title[:50]}_{safe_url[-50:]}".replace(" ", "_")

    def reset_cycle_metrics(self):
        """Call this at the start of a collection cycle."""
        self.cycle_start_time = time.time()
        self.llm_calls_count = 0
        self.heuristic_used_count = 0
        # Basic connectivity check or assume healthy until failure
        # OllamaProvider doesn't have lightweight is_healthy, so assume True
        self.is_llm_healthy = True
        logger.info("CognitiveScorer Cycle Start.")

    def _check_budget(self) -> bool:
        """Return True if we have budget left."""
        if not self.is_llm_healthy:
            return False
        elapsed = time.time() - self.cycle_start_time
        return elapsed < self.max_cycle_budget_sec

    def _get_from_cache(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            from contextlib import closing

            with closing(sqlite3.connect(CACHE_DB_PATH)) as conn:
                # Default read is not transactional but good practice to be consistent
                cursor = conn.execute(
                    "SELECT score, details, reasoning FROM cognitive_scores WHERE key=?",
                    (key,),
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "score": row[0],
                        "details": json.loads(row[1]),
                        "reasoning": row[2] + " (Cached)",
                    }
        except sqlite3.Error as e:
            logger.debug(f"Cache read failed or table missing: {e}")
        return None

    def _save_to_cache(self, key: str, result: Dict[str, Any]):
        try:
            from contextlib import closing

            with closing(sqlite3.connect(CACHE_DB_PATH)) as conn:  # noqa: SIM117
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO cognitive_scores (key, score, details, reasoning) VALUES (?, ?, ?, ?)",
                        (
                            key,
                            result["score"],
                            json.dumps(result["details"]),
                            result.get("reasoning", ""),
                        ),
                    )
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

    async def score_batch_async(  # noqa: C901
        self, payload_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Batched Scoring entry point.
        Scores a list of articles using Hybrid Strategy.
        """
        # 1. Prep
        results_map = {}  # map index -> result
        articles_to_process = []  # list of (index, article_obj)

        # 2. Check Cache first for all
        for i, payload in enumerate(payload_list):
            article_data = payload.get("article", payload)

            # Simple wrapper
            class Wrapper:
                def __init__(self, d: Dict[str, Any]) -> None:
                    self.__dict__ = d

                def __getattr__(self, k: str) -> Any:
                    return self.__dict__.get(k)

            # Ensure dates are parsed/defaulted
            for date_field in ["published_date", "collected_date"]:
                val = article_data.get(date_field)
                if isinstance(val, str):
                    try:  # noqa: SIM105
                        article_data[date_field] = datetime.fromisoformat(
                            val.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        pass

            if not article_data.get("collected_date"):
                article_data["collected_date"] = datetime.now(timezone.utc)

            art_obj = Wrapper(article_data)

            key = self._get_cache_key(art_obj)
            cached = self._get_from_cache(key)
            if cached:
                # Apply cache hit immediately
                results_map[i] = self._finalize_score(
                    art_obj, cached, payload.get("source_config")
                )
            else:
                articles_to_process.append((i, art_obj))

        # 3. Process remaining items
        if articles_to_process:
            use_llm = self._check_budget()

            if use_llm:
                # Prepare Batch
                batch_inputs = []
                indices_for_llm = []

                for idx, art in articles_to_process:
                    text = f"Title: {art.title}\nSummary: {art.summary}\nContent: {(art.content or '')[:800]}"
                    batch_inputs.append(text)
                    indices_for_llm.append(idx)

                # Call LLM Batch
                llm_results = await self._call_llm_batch(batch_inputs)

                # Check results
                if llm_results:
                    for j, res in enumerate(llm_results):
                        original_idx = indices_for_llm[j]
                        art = articles_to_process[j][1]  # (idx, art)

                        # Cache it
                        key = self._get_cache_key(art)
                        self._save_to_cache(key, res)

                        # Finalize
                        results_map[original_idx] = self._finalize_score(
                            art, res, payload_list[original_idx].get("source_config")
                        )
                else:
                    # LLM failed completely for batch -> Fallback to heuristic
                    self.is_llm_healthy = False
                    use_llm = False

            if not use_llm:
                # Heuristic Fallback
                for idx, art in articles_to_process:
                    if idx in results_map:
                        continue

                    self.heuristic_used_count += 1
                    h_score = self.heuristic.calculate_score(cast(Article, art))
                    res = {
                        "score": h_score,
                        "details": {"heuristic": True},
                        "reasoning": "Heuristic fallback (Budget/LLM unavailable)",
                    }
                    results_map[idx] = self._finalize_score(
                        art,
                        res,
                        payload_list[idx].get("source_config"),
                        is_heuristic=True,
                    )

        # 4. Reconstruct ordered list
        final_results = []
        for i in range(len(payload_list)):
            if i in results_map:
                final_results.append(results_map[i])
            else:
                logger.error(f"Missing result for index {i} in batch scoring")
                # Fallback for missing items
                final_results.append(
                    {
                        "final_score": 0.0,
                        "should_include": False,
                        "components": {},
                        "decision_label": "error",
                        "explanation": {"reasoning": "Missing from batch results"},
                    }
                )

        return final_results

    async def _call_llm_batch(
        self, inputs: List[str]
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Call LLM with a batch of articles to calculate NQI metrics.
        """
        if not inputs:
            return []

        self.llm_calls_count += 1

        joined_inputs = ""
        for k, text in enumerate(inputs):
            joined_inputs += f"--- ITEM {k+1} ---\n{text}\n\n"

        system_prompt = (
            "You are a Senior Editor at 'Noticiencias'. Evaluate these science news items for the Latin American audience.\n"
            "For EACH item, output a JSON object with scores (0-5):\n"
            "1. substance (Scientific rigor, data density, evidence depth)\n"
            "2. narrative (Storytelling potential, tension, wow factor)\n"
            "3. relevance (Relevance for LatAm, universal appeal, accessibility)\n"
            "4. credibility (Trustworthiness, lack of hype)\n\n"
            "Return a JSON Object: { 'results': [ { 'item_index': 1, 'scores': {...}, 'reasoning': '...' }, ... ] }"
        )

        try:
            # Use async generation from OllamaProvider
            resp = await self.llm.generate_async(
                joined_inputs, system=system_prompt, json_mode=True
            )

            if not isinstance(resp, dict) or "results" not in resp:
                return None

            outputs = []
            res_list_obj = resp["results"]
            if not isinstance(res_list_obj, list):
                return None
            res_list = res_list_obj
            res_map = {r.get("item_index", i + 1): r for i, r in enumerate(res_list)}

            for i in range(len(inputs)):
                item_res = res_map.get(i + 1)
                if item_res and "scores" in item_res:
                    scores = item_res["scores"]

                    substance = float(scores.get("substance", 0))
                    narrative = float(scores.get("narrative", 0))
                    relevance = float(scores.get("relevance", 0))
                    credibility = float(scores.get("credibility", 0))

                    raw_nqi = (
                        substance * 0.35
                        + narrative * 0.30
                        + relevance * 0.20
                        + credibility * 0.15
                    )
                    norm_score = min(1.0, raw_nqi / 5.0)

                    details = scores.copy()
                    details["reasoning"] = item_res.get("reasoning", "")

                    outputs.append(
                        {
                            "score": norm_score,
                            "details": details,
                            "reasoning": item_res.get("reasoning", ""),
                        }
                    )
                else:
                    outputs.append(
                        {
                            "score": 0.0,
                            "details": {"error": "Missing in batch response"},
                            "reasoning": "Batch parsing error",
                        }
                    )
            return outputs

        except Exception as e:
            logger.warning(f"Batch LLM failed: {e}")
            return None

    def _finalize_score(
        self, article, cognitive_res, source_config, is_heuristic=False
    ) -> Dict[str, Any]:
        """
        Combine metrics into Final NQI Score.
        Mapping NQI Dimensions to Config Keys to maintain schema compatibility:
        - content_quality     <-- Substance
        - engagement_potential <-- Narrative
        - recency             <-- Time Decay + Relevance (Hybrid)
        - source_credibility  <-- Source Reputation + Credibility (Hybrid)
        """

        # 1. Base Metrics from BasicScorer logic
        base_source = self._calculate_source_credibility_score(article, source_config)
        base_recency = self._calculate_recency_score(article)
        # base_content and base_engagement ignored if we have cognitive data

        # 2. Extract Cognitive Dimensions (Normalized 0-1)
        # If heuristic fallback, these come from HeuristicScorer (which already computed NQI)
        # If LLM, they come from "scores" dict.

        details = cognitive_res.get("details", {})

        if is_heuristic:
            # HeuristicScorer logic already fused everything into 'score'.
            # We can try to unpack if HeuristicScorer returned details?
            # Current HeuristicScorer returns float only.
            # So we trust the single score as the "Global NQI".
            # To fit the schema, we assign the global score to all comps or just use it.
            # Let's trust final_score directly.

            final_score = cognitive_res["score"]
            # Fill components with the same value for simplicity or re-calc heuristic components?
            # Re-running heuristic breakdowns is cheap.

            # Actually, to be clean, let's just assign:
            comp_substance = final_score
            comp_narrative = final_score
            comp_relevance = final_score
            comp_credibility = final_score

        else:
            # LLM output available
            # Normalize 0-5 to 0-1
            def to_norm(x):
                return min(1.0, float(x) / 5.0)

            comp_substance = to_norm(details.get("substance", 0))
            comp_narrative = to_norm(details.get("narrative", 0))
            comp_relevance = to_norm(details.get("relevance", 0))
            comp_credibility = to_norm(details.get("credibility", 0))

        # 3. Hybrid Usage (Blending LLM with deterministic signals)

        # A. Substance (35%): Blend LLM Substance (0.8) with Data Density/Length?
        # For now, trust LLM if available.
        final_content_quality = comp_substance

        # B. Narrative (30%): Trust LLM Narrative.
        final_engagement = comp_narrative

        # C. Relevance (20%): Blend Time Decay (Recency) with Semantic Relevance
        # If article is old (low recency), it kills relevance.
        # If Relevance is low (no LatAm/boring), it lowers score.
        final_recency = (base_recency * 0.5) + (comp_relevance * 0.5)

        # D. Credibility (15%): Blend Domain Authority (Source Score) with Content Credibility (LLM)
        final_source_cred = (base_source * 0.5) + (comp_credibility * 0.5)

        # 4. Final Weighted Sum using Config Weights
        # weights should be: content=0.35, engagement=0.30, recency=0.20, source=0.15
        final_score = (
            final_content_quality * self.weights["content_quality"]
            + final_engagement * self.weights["engagement_potential"]
            + final_recency * self.weights["recency"]
            + final_source_cred * self.weights["source_credibility"]
        )

        final_score = max(0.0, min(1.0, final_score))

        decision = "discard"
        if final_score >= 0.75:
            decision = "priority"
        elif final_score >= 0.60:
            decision = "publishable"

        return {
            "final_score": round(final_score, 4),
            "should_include": final_score >= 0.60,
            "decision_label": decision,
            "components": {
                "source_credibility": round(final_source_cred, 4),
                "recency": round(final_recency, 4),
                "content_quality": round(final_content_quality, 4),
                "engagement_potential": round(final_engagement, 4),
                "nqi_substance": round(comp_substance, 4),
                "nqi_narrative": round(comp_narrative, 4),
                "nqi_relevance": round(comp_relevance, 4),
                "nqi_credibility": round(comp_credibility, 4),
            },
            "cognitive_details": details,
            "weights": self.weights.copy(),
            "explanation": self._generate_cognitive_explanation(
                article,
                final_score,
                final_source_cred,
                final_recency,
                final_content_quality,
                final_engagement,
                cognitive_res,
            ),
            "version": self.version,
            "calculated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _generate_cognitive_explanation(
        self, article, final, source, recency, content, engagement, cognitive_res
    ):
        return {
            "overall_assessment": self._get_overall_assessment(final),
            "reasoning": cognitive_res.get("reasoning", ""),
        }

    # Override single score for compatibility (if called directly)
    def score_article(
        self, article: Article, source_config: Dict[str, Any] | None = None
    ) -> Dict[str, Any]:
        # Synchronous single item score - usually NOT used if batching enabled
        # But implemented for safety.
        # Use cache or heuristic fallback immediately to avoid blocking if LLM needed?
        # Or try LLM?
        # Let's try LLM if healthy.
        key = self._get_cache_key(article)
        cached = self._get_from_cache(key)
        if cached:
            return self._finalize_score(article, cached, source_config)

        if self._check_budget():
            # Try single LLM call ... reuse logic from original class ...
            # For now, just fallback to heuristic to encourage batching usage.
            pass

        # Fallback
        h_score = self.heuristic.calculate_score(article)
        res = {
            "score": h_score,
            "details": {"heuristic": True},
            "reasoning": "Single-item Fallback",
        }
        return self._finalize_score(article, res, source_config, is_heuristic=True)
