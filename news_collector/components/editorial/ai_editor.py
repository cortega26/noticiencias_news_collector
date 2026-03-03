import json
import os
import re
import time
from datetime import date as dt_date
from datetime import datetime as dt_datetime
from pathlib import Path
from typing import Any

from news_collector.infrastructure.llm.model_registry import resolve_ollama_model_map
from news_collector.infrastructure.llm.provider import OllamaProvider
from news_collector.utils.logger import get_logger

# Use the centralized logger factory
logger = get_logger().create_module_logger("components.editorial.ai_editor")
import yaml
from news_collector.config.settings import TEXT_PROCESSING_CONFIG
from noticiencias.config_manager import load_config
from pydantic import BaseModel, Field, ValidationError

SOURCE_IDENTITY_COMMENT_RE = re.compile(
    r"<!--\s*source_identity:[\s\S]*?-->",
    flags=re.IGNORECASE,
)


class HeadlinesSchema(BaseModel):
    direct: str = Field(..., min_length=5)
    question: str = Field(..., min_length=5)
    benefit: str = Field(..., min_length=5)
    excerpt: str = Field(..., min_length=10, max_length=300)
    tags: list[str] = Field(default_factory=list, min_length=1, max_length=8)


class EditorAgent:
    def __init__(
        self,
        api_url: str,
        model: str,
        translator_model: str | None = None,
        editor_model: str | None = None,
        headlines_model: str | None = None,
    ):
        self.api_url = api_url
        self.model = model
        self._translator_model_cfg = translator_model
        self._editor_model_cfg = editor_model
        self._headlines_model_cfg = headlines_model

        # Configure regex early; cache directory will be resolved after config
        self._emoji_re = re.compile(
            r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]",
            flags=re.UNICODE,
        )
        try:
            cfg = load_config()
            self.min_content_length = cfg.text_processing.min_content_length
            # Resolve persistent data directory for stable checkpointing across runs
            paths = getattr(cfg, "paths", None) or {}
            if isinstance(paths, dict):
                data_dir = paths.get("data_dir", "./data")
            else:
                data_dir = getattr(paths, "data_dir", "./data")
        except Exception:
            # Fallbacks if config is unavailable early in boot
            self.min_content_length = 750
            data_dir = "./data"

        # Anchor cache to the configured data directory to avoid CWD-dependent paths
        # Use a dedicated subfolder to avoid collisions with other caches
        self.cache_dir = Path(data_dir) / "cache" / "editor"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.critic_threshold = TEXT_PROCESSING_CONFIG.get("critic_score_threshold", 70)

        self.prompts = self._load_prompts()

        resolved = resolve_ollama_model_map(
            {
                "ollama": {
                    "model": self.model,
                    "translator_model": self._translator_model_cfg,
                    "editor_model": self._editor_model_cfg,
                    "headlines_model": self._headlines_model_cfg,
                },
                "scoring": {},
            },
            logger=logger,
        )
        self.model = resolved["default"].model_id
        self.translator_model = resolved["translator"].model_id
        self.editor_model = resolved["editor"].model_id
        self.headlines_model = resolved["headlines"].model_id

        # Initialize unified provider
        # Note: ai_editor uses a higher timeout (900s) than default
        self.provider = OllamaProvider(
            api_url=self.api_url, model=self.model, timeout=3600
        )
        logger.info(
            "EditorAgent model routing resolved: default=%s, translator=%s, editor=%s, headlines=%s",
            self.model,
            self.translator_model,
            self.editor_model,
            self.headlines_model,
        )

    def _load_prompts(self) -> dict:
        """Loads prompt templates from yaml config."""
        # Config is expected to be in noticiencias_news_collector/config/prompts.yaml
        # This file is deep in news_collector/components/editorial/ai_editor.py
        # root is 3 levels up: ../../../
        project_root = Path(__file__).resolve().parents[3]
        prompts_path = project_root / "config" / "prompts.yaml"

        try:
            import yaml

            if prompts_path.exists():
                data = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except ImportError:
            logger.warning("PyYAML not installed, falling back to basic prompts.")
        except Exception as e:
            logger.error(f"Error loading prompts: {e}")

        # Fallback prompts if file missing or parse error
        return {
            "translator": {"system": "Translate to Spanish. Keep it neutral."},
            "editor": {"system": "Rewrite as a science journalist for LatAm. No hype."},
            "headline": {"system": "Generate 3 headlines (json)."},
        }

    def _strip_emojis(self, text: str) -> str:
        return self._emoji_re.sub("", text)

    def _inject_frontmatter_field(self, text: str, key: str, value: str) -> str:
        if not text.startswith("---"):
            return f'---\n{key}: "{value}"\n---\n\n{text}'

        lines = text.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break

        if end_idx is None:
            return f'---\n{key}: "{value}"\n---\n\n{text}'

        for line in lines[1:end_idx]:
            if line.strip().lower().startswith(f"{key.lower()}:"):
                return text

        lines.insert(end_idx, f'{key}: "{value}"')
        return "\n".join(lines)

    def _extract_markdown_content(self, text: str) -> str:
        """Helper to extract clean markdown from potential LLM chatter."""
        # If LLM wraps code in ```markdown ... ```
        match = re.search(r"```markdown\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        match = re.search(r"```\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        return text

    def _upsert_source_identity_comment(
        self, markdown: str, source_id: str | None, source_name: str | None
    ) -> str:
        """Ensure a single canonical source_identity comment is present."""
        cleaned = SOURCE_IDENTITY_COMMENT_RE.sub("", markdown).strip()
        source_id_text = str(source_id).strip() if source_id is not None else ""
        source_name_text = str(source_name).strip() if source_name is not None else ""

        if not source_id_text and not source_name_text:
            return cleaned

        safe_source_id = source_id_text.replace("--", "-").replace("\n", " ")
        safe_source_name = source_name_text.replace("--", "-").replace("\n", " ")
        canonical_comment = (
            f"<!-- source_identity: source_id={safe_source_id}; "
            f"source_name={safe_source_name} -->"
        )

        if not cleaned:
            return canonical_comment
        return f"{cleaned}\n\n{canonical_comment}"

    def _normalize_frontmatter_for_yaml(self, payload: dict) -> dict:
        """
        Normalize frontmatter payload before YAML serialization.
        Keeps date/datetime objects as native types so PyYAML emits
        unquoted YAML timestamps for schema-aligned fields like `date`.
        """

        def normalize_value(value):
            if isinstance(value, dict):
                return {str(k): normalize_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [normalize_value(item) for item in value]
            if isinstance(value, (dt_date, dt_datetime, bool, int, float, str)):
                return value
            if value is None:
                return None
            return str(value)

        return {str(key): normalize_value(val) for key, val in payload.items()}

    def _send_prompt(self, prompt: str, system: str | None = None, model: str | None = None) -> str:
        """Helper to send prompt to Ollama with streaming handling."""
        use_model = model or self.model
        logger.info(f"Sending prompt to Ollama ({use_model})...")
        sys_preview = (system or "")[:20]
        print(f"Processing ({sys_preview}...) [{use_model}]", end="", flush=True)

        try:
            start_time = time.time()
            # Use provider's sync iterator which handles retries
            generator = self.provider.generate_sync(
                prompt, system=system, stream=True, model=use_model
            )

            full_text = []
            count = 0
            for chunk in generator:
                full_text.append(chunk)
                count += 1  # noqa: SIM113
                if count % 20 == 0:
                    print(".", end="", flush=True)

            print(" Done!")
            duration = time.time() - start_time
            logger.info(f"Ollama processing complete in {duration:.2f} seconds.")

            return "".join(full_text).strip()

        except Exception as e:
            print("")
            logger.error(f"Error communicating with Ollama: {e}")
            raise

    def _load_scientific_entities(self) -> str:
        """Loads the canonical list of scientific entities for prompt injection."""
        try:
            path = (
                Path(__file__).resolve().parents[3]
                / "news_collector"
                / "data"
                / "scientific_entities.json"
            )
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                # Format as a readable list for the LLM
                entities_str = "\n".join(
                    [
                        f"- {k} -> {v.get('es_name', k)} ({v.get('type')})"
                        for k, v in data.items()
                    ]
                )
                return f"\n\nLISTA CANÓNICA DE ENTIDADES CIENTÍFICAS (USAR ESTAS TRADUCCIONES O MANTENER ORIGINAL):\n{entities_str}"
        except Exception as e:
            logger.warning(f"Failed to load scientific entities: {e}")
        return ""

    def _translate_scientific(self, content: str) -> str:
        """Stage 1: Scientific Translation"""
        system_prompt = self.prompts.get("translator", {}).get("system", "")

        # Inject Canonical List
        entities_context = self._load_scientific_entities()
        if entities_context:
            system_prompt += entities_context

        return self._send_prompt(
            content, system=system_prompt, model=self.translator_model
        )

    def _adapt_editorial(self, translated_content: str) -> str:
        """Stage 2: Editorial Adaptation"""
        system_prompt = self.prompts.get("editor", {}).get("system", "")
        return self._send_prompt(
            translated_content, system=system_prompt, model=self.editor_model
        )

    def _extract_json(self, text: str) -> dict:
        """
        Robustly extracts a JSON object using the provider's logic.
        """
        result = self.provider._extract_json(text)
        if not result and "{" in text:
            # If provider returned empty but there might be JSON, raise strict error
            # to match original behavior of raising ValueError?
            # Original raised ValueError if no JSON found.
            # Provider returns {}
            raise ValueError("No parsing valid JSON object found")
        return result

    def _critic_pass(self, content: str) -> tuple[bool, str | None]:
        """
        Stage 1.5: Critic Guardrail.
        Verifies that the content is in Spanish and relevant to science.
        """
        # Feature Flag: Kill Switch
        import os

        if os.getenv("ENABLE_TRANSLATION_GUARD", "true").lower() == "false":
            logger.info("Translation Guard Disabled (Critic Pass Skipped)")
            return True, None

        system_prompt = "You are a Quality Control Editor. Output ONLY JSON."

        # Load entities for the critic to check against
        entities_context = self._load_scientific_entities()

        prompt = (
            "Analyze the following text. \n"
            "1. Is it written in Spanish? \n"
            "2. Is it about science/technology? \n"
            "3. [CRITICAL] Does it respect proper nouns? Check for literal translations of scientific institutions/surveys.\n"
            f"   Specific check: Do NOT allow literal translations of these entities if they differ from the canonical list:\n{entities_context}\n"
            "   Example FAIL: 'Encuesta de Energía Oscura' (Should be 'Observatorio...' or 'Dark Energy Survey').\n"
            "   Example FAIL: 'Telescopio Muy Grande' (Should be 'Very Large Telescope' or 'VLT').\n\n"
            "Rate confidence 0-100. \n"
            "If a canonical entity name is malformed or literally translated, SCORE MUST BE 0.\n"
            'Output JSON: {"score": integer, "reason": "short string"}\n\n'
            f"{content[:2000]}"
        )

        try:
            # Use headlines model (usually faster/smarter) or editor model
            response = self._send_prompt(
                prompt, system=system_prompt, model=self.editor_model
            )
            result = self._extract_json(response)

            score = result.get("score", 0)
            reason = result.get("reason", "Unknown reason")  # Default reason

            if score < self.critic_threshold:
                logger.warning(
                    f"⛔ CRITIC REJECTED: Score {score}/{self.critic_threshold}. Reason: {reason}"
                )
                return False, reason

            logger.info(f"✅ Critic Pass Passed (Score: {score})")
            return True, None
        except Exception as e:
            logger.warning(f"Critic Pass Failed (Error): {e} - Failing Open (MVS)")
            # MVS Decision: If critic crashes, do we fail open or closed?
            # Plan says "Fail if invalid". But if LLM crashes...
            # Let's Fail Closed for safety as per "Do No Harm".
            # BUT implementation plan says "Discard article".
            # So return False.
            return False, f"Critic Exception: {e}"

    def _repair_editorial(self, base_content: str, feedback: str) -> str:
        """
        Stage 2.5 Repair: Re-run adaptation with specific feedback.
        """
        logger.info(f"🔧 Repairing Editorial Content based on feedback: {feedback}")
        system_prompt = self.prompts.get("editor", {}).get("system", "")
        repair_prompt = (
            f"The previous version was rejected by the Quality Control Editor for the following reason:\n"
            f"'{feedback}'\n\n"
            f"Please rewrite the article to address this specific issue while maintaining the original style and structure.\n"
            f"Base Content:\n{base_content}"
        )
        return self._send_prompt(
            repair_prompt, system=system_prompt, model=self.editor_model
        )

    def _generate_headlines(self, adapted_content: str) -> dict:
        """Stage 3: Headline Generation & Metadata"""
        system_prompt = self.prompts.get("headline", {}).get("system", "")
        # Prompt explicitly for JSON in the message body as well to be safe
        prompt = f"Analyze this article and generate JSON with keys: 'direct', 'question', 'benefit', 'excerpt' (max 140 chars summary for SEO), and 'tags' (list of 3-5 semantic keywords in Spanish. Rules: lowercase, singular, specific entities/concepts. NO generic tags like 'ciencia', 'tecnologia', 'salud', 'noticia').\n\n{adapted_content[:2000]}"
        response = self._send_prompt(
            prompt, system=system_prompt, model=self.headlines_model
        )

        try:
            data = self._extract_json(response)

            # Feature Flag: Kill Switch
            if os.getenv("ENABLE_TRANSLATION_GUARD", "true").lower() == "false":
                return data

            # Schema Enforcement (MVS)
            validated = HeadlinesSchema(**data)
            return validated.model_dump()
        except ValidationError as ve:
            logger.error(f"❌ Headline Schema Validation Failed: {ve}")
            raise ValueError(f"Schema Validation Failed: {ve}") from ve
        except Exception as e:
            logger.error(
                f"Failed to generate headlines: {e} | Response snippet: {response[:100]}..."
            )
            # Fallback to empty if fails
            raise ValueError(f"Failed to generate headlines: {e}") from e

    def _repair_output(  # noqa: C901
        self, content: str, headlines: dict, input_len: int
    ) -> tuple[str, dict]:
        """
        Deterministic Repair Layer.
        Enforces invariants without LLM calls.
        """
        logger.info("Running Deterministic Repair...")

        # 1. Headline Repair
        # Ensure mandatory keys exist (Map Spanish requirements to internal English keys)
        if "direct" not in headlines or not headlines["direct"]:
            headlines["direct"] = headlines.get("directo", "Noticia Científica")

        if "question" not in headlines or not headlines["question"]:
            # Deterministic fallback
            headlines["question"] = headlines.get(
                "pregunta", "¿Qué plantea este estudio y por qué es relevante?"
            )

        if "benefit" not in headlines or not headlines["benefit"]:
            headlines["benefit"] = headlines.get(
                "relevancia", "Importancia del hallazgo para el campo."
            )

        # 2. Section Normalization (Simple Mapping)
        # Normalize common variations to standard headers
        replacements = {
            "## Introducción": "## Apertura",
            "## Antecedentes": "## Contexto",
            "## Conclusión": "## Cierre",
            "**Introducción**": "**Apertura**",
            "**Conclusión**": "**Cierre**",
        }
        for old, new in replacements.items():
            content = content.replace(old, new)

        # 3. Length Repair
        # Target strict 2.5x ratio on FINAL output (Frontmatter + Body)
        # Frontmatter can be large (~600-800 chars). To be safe, target Body < 1.8x Input.
        max_chars = int(input_len * 1.8)
        if len(content) > max_chars:
            logger.warning(
                f"Output body too long ({len(content)} > {max_chars}). Applying deterministic trim."
            )

            # Rule 1: Remove trailing after Cierre
            if "Cierre" in content:
                match = re.search(r"(#{2,3} |[*]{2})Cierre", content, re.IGNORECASE)
                if match:
                    start_idx = match.start()
                    # Keep Cierre paragraph (assumed ~500 chars max)
                    # Find next double newline after start
                    cierre_end = content.find("\n\n", start_idx + 50)
                    if cierre_end == -1:
                        cierre_end = len(content)
                    else:
                        cierre_end = min(
                            len(content), cierre_end + 1000
                        )  # Keep a bit more context

                    potential_cut = content[:cierre_end]
                    if len(potential_cut) < len(content):
                        content = potential_cut

            # Rule 3 (Fail-safe): Hard truncate
            if len(content) > max_chars:
                content = content[:max_chars]
                last_period = content.rfind(".")
                if last_period > 0:
                    content = content[: last_period + 1]
                else:
                    content += "..."

        return content, headlines

    def _get_cache_path(self, article_id: str, stage: str) -> Path:
        """Returns the path for a cached stage artifact."""
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(article_id))
        return self.cache_dir / f"{safe_id}_{stage}.txt"

    def process_article(  # noqa: C901
        self, raw_text: str | dict, override_date: str | None = None
    ) -> str:
        """
        Orchestrate the 3-stage pipeline: Translate -> Adapt -> Metadata.
        Includes checkpointing to prevent data loss.
        """
        # 1. Extract Info
        title = ""
        summary = ""
        content = ""
        image_url = None
        source_url = None
        source_id = None
        source_name = None
        article_id = "unknown"

        if isinstance(raw_text, dict):
            title = raw_text.get("title", "") or ""
            summary = raw_text.get("summary", "") or ""
            content = raw_text.get("content", "") or ""

            # Fallback for RSS feeds where "content" is often in "summary"
            if not content and summary:
                content = summary

            image_url = raw_text.get("image_url")
            source_id = raw_text.get("source_id")
            source_name = raw_text.get("source_name")
            source_url = (
                raw_text.get("url")
                or (raw_text.get("metadata") or {}).get("original_url")
                or ((raw_text.get("metadata") or {}).get("source_metadata") or {}).get(
                    "entry_id"
                )
            )
            raw_category = (raw_text.get("metadata") or {}).get("category", "other")
            article_id = str(raw_text.get("id") or "unknown")
        else:
            content = raw_text
            import hashlib

            article_id = hashlib.md5(content.encode()).hexdigest()[:8]  # noqa: S324
            raw_category = "other"

        # Map source category to site category
        category_map = {
            "medicine": "Salud",
            "biology": "Salud",
            "technology": "Tecnología",
            "artificial_intelligence": "Tecnología",
            "engineering": "Tecnología",
            "space": "Ciencia",
            "physics": "Ciencia",
            "popular_science": "Ciencia",
            "community_science": "Ciencia",
            "multidisciplinary": "Ciencia",
        }

        final_category = category_map.get(raw_category, "Ciencia")

        input_text = f"Title: {title}\nContent: {content}"

        # Validation: content length
        if len(content.strip()) < self.min_content_length:
            raise ValueError(
                f"Content too short ({len(content)} chars). Likely paywalled or empty."
            )

        # 2. Pipeline Execution

        # --- STAGE 1: Scientific Translation ---
        print("\n--- STAGE 1: Scientific Translation ---")
        cache_s1 = self._get_cache_path(article_id, "stage1_translation")
        if cache_s1.exists():
            print(f"(Loaded from cache: {cache_s1})")
            translated_text = cache_s1.read_text(encoding="utf-8")
        else:
            translated_text = self._translate_scientific(input_text)
            cache_s1.write_text(translated_text, encoding="utf-8")

        # --- STAGE 2: Editorial Adaptation ---
        print("\n--- STAGE 2: Editorial Adaptation ---")
        cache_s2 = self._get_cache_path(article_id, "stage2_editorial")
        if cache_s2.exists():
            print(f"(Loaded from cache: {cache_s2})")
            final_content = cache_s2.read_text(encoding="utf-8")
        else:
            final_content = self._adapt_editorial(translated_text)
            final_content = self._extract_markdown_content(final_content)  # Cleanup
            cache_s2.write_text(final_content, encoding="utf-8")

        # --- STAGE 2.5: Critic Pass (Validation & Repair) ---
        print("\n--- STAGE 2.5: Critic Pass (Validation & Repair) ---")

        # Checkpoint: If we already passed the critic gate for this article, skip re-evaluation
        cache_s2_5 = self._get_cache_path(article_id, "stage2_5_critic_ok")
        if cache_s2_5.exists():
            print(f"(Loaded from cache: {cache_s2_5})")
        else:
            max_retries = 2
            for attempt in range(max_retries + 1):
                # We run this on the adapted content to be sure.
                is_valid, reason = self._critic_pass(final_content)

                if is_valid:
                    # Persist critic pass checkpoint to avoid re-running on resume
                    try:
                        cache_s2_5.write_text("ok", encoding="utf-8")
                    except Exception as _e:
                        logger.warning(f"Failed to persist critic checkpoint: {_e}")
                    break

                if attempt < max_retries:
                    print(
                        f"⚠️ Critic rejected content (Attempt {attempt+1}/{max_retries + 1}). Repairing..."
                    )
                    print(f"   Reason: {reason}")
                    # Repair using the Translated Text (Stage 1 output) as base to ensure fresh start
                    final_content = self._repair_editorial(translated_text, reason or "Unknown reason")
                    final_content = self._extract_markdown_content(
                        final_content
                    )  # Cleanup
                else:
                    raise ValueError(
                        f"Translation Guardrail: Content rejected by critic after {max_retries} retries. Reason: {reason}"
                    )

        # --- STAGE 3: Metadata & Headlines ---
        print("\n--- STAGE 3: Metadata & Headlines ---")
        # Stage 3 is fast enough relative to others, and depends on final content structure.
        # We could cache it, but usually we want to regenerate headlines if we tweak code.
        # For now, we won't cache Stage 3 to allow easier re-runs of the final formatting.
        headlines = self._generate_headlines(final_content)

        # --- DETERMINISTIC REPAIR LAYER ---
        final_content, headlines = self._repair_output(
            final_content, headlines, len(input_text)
        )

        # 3. Assemble Final Artifact
        # Choose the 'direct' headline by default or a combination
        final_title = headlines.get("direct", title)  # Fallback to original if fail

        # Sanitize title: ensure it's a string and not a list representation
        if isinstance(final_title, list):
            final_title = final_title[0] if final_title else "Untitled"
        final_title = str(final_title).replace('"', '\\"')

        # Sanitize excerpt
        final_excerpt = headlines.get("excerpt", "")
        if isinstance(final_excerpt, list):
            final_excerpt = final_excerpt[0] if final_excerpt else ""
        final_excerpt = str(final_excerpt).replace('"', '\\"')

        # Sanitize and Validate Tags (Repo-Truth Implementation)
        try:
            from news_collector.taxonomy.normalizer import TagNormalizer

            normalizer = TagNormalizer()

            raw_tags = headlines.get("tags") or []
            # Fallback if raw_tags is None or empty, use category if not 'other'
            if not raw_tags and raw_category.lower() != "other":
                raw_tags = [raw_category]

            # SANITIZE
            norm_result = normalizer.sanitize_tags(raw_tags)
            final_tags = norm_result.tags

            # VALIDATE
            val_result = normalizer.validate_tags(final_tags)
            if val_result.needs_review:
                logger.warning(f"⚠️ Tags require review: {val_result.errors}")
                # We could add a frontmatter flag 'needs_tag_review: true' here if desired
                # for now, we just log it.

            # Audit log
            if norm_result.replaced or norm_result.removed or norm_result.merged:
                logger.info(
                    f"Tag Audit: {norm_result.model_dump_json(exclude={'tags', 'warnings'})}"
                )

        except Exception as e:
            logger.error(f"Tag Normalization Failed: {e}")
            final_tags = headlines.get("tags") or []  # Fallback to raw

        # Construct Frontmatter using Strict Contract
        try:
            # Prepare optional fields
            hl_variants = None
            if headlines and headlines.get("question") and headlines.get("benefit"):
                hl_variants = {
                    "question": headlines.get("question", ""),
                    "benefit": headlines.get("benefit", ""),
                }

            # Categories is a list in schema, but currently single string. Wrap it.
            # Schema expects list[str].
            categories_list = [final_category] if final_category else []

            # Date parsing for PyYAML type coercion
            date_str = override_date or time.strftime("%Y-%m-%d")
            parsed_date_val: Any = date_str
            if isinstance(date_str, str):
                from datetime import datetime
                try:
                    if len(date_str) == 10:
                        parsed_date_val = datetime.strptime(date_str, "%Y-%m-%d").date()
                    else:
                        parsed_date_val = datetime.fromisoformat(date_str)
                except ValueError:
                    pass

            model_dict = {
                "title": final_title,
                "schema_version": 2,
                "date": parsed_date_val,
                "author": "Noticiencias AI",
                "categories": categories_list,
                "tags": final_tags,
                "excerpt": final_excerpt,
            }
            if image_url:
                model_dict["image"] = image_url
            if source_url:
                model_dict["source_url"] = source_url
            if article_id and article_id != "unknown":
                model_dict["refinery_id"] = article_id
            if hl_variants:
                model_dict["headlines_variants"] = hl_variants

            # Dump to YAML
            # Use python mode to preserve native date types and emit
            # YAML date tokens without quotes for Astro z.date() compatibility.
            model_dict = self._normalize_frontmatter_for_yaml(model_dict)

            # Custom dumper to ensure correct formatting (e.g. no aliases)
            # Safe dump usually avoids complex tags
            yaml_frontmatter = yaml.safe_dump(
                model_dict,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
                width=1000,  # Avoid wrapping long lines unnecessarily
            ).strip()

            # Prepare full article
            full_article = f"---\n{yaml_frontmatter}\n---\n\n{final_content}"

        except ValidationError as ve:
            logger.error(f"❌ AstroPost Contract Validation Failed: {ve}")
            # Fallback to manual construction or raise?
            # FAIL CLOSED: Raise error to prevent invalid content
            raise ValueError(f"Content Contract Violation: {ve}") from ve
        except Exception as e:
            logger.error(f"❌ Error generating frontmatter: {e}")
            raise

        # Append source link footer if missing
        # Logic update: explicit footer check because source_url is now in frontmatter too
        footer_link = f"Fuente original: [{source_url}]({source_url})"
        if source_url and footer_link not in full_article:
            full_article += f"\n\n{footer_link}"

        # Persist source identity metadata as a hidden comment to keep provenance
        # without widening the frontmatter schema contract.
        full_article = self._upsert_source_identity_comment(
            full_article, source_id=source_id, source_name=source_name
        )

        # Logic to strip Visual planning section if no image is present (Rule from tests)
        if not image_url:
            # Regex to remove **TL;DR Visual**... up to next **Header** or end of string
            # Using DOTALL to match newlines
            full_article = re.sub(
                r"\*\*TL;DR Visual\*\*.*?(?=\*\*|$)",
                "",
                full_article,
                flags=re.DOTALL | re.MULTILINE,
            )

        return self._strip_emojis(full_article)

    def generate_social_content(self, article_content: str, url: str = "") -> str:
        """Generates social media posts (Twitter/LinkedIn) for the refined article."""

        prompt = (
            "You are a social media manager for the science news site 'Noticiencias'. "
            "Based on the following article content (which is in Spanish), generate two social media posts:\\n\\n"
            "1. **Twitter/X Post**: Engaging, under 280 characters, no emojis, includes hashtags. Language: Spanish.\\n"
            "2. **LinkedIn Post**: Professional but engaging, summarizes the key finding. Language: Spanish.\\n\\n"
            f"Article Content:\\n{article_content[:3000]}...\\n\\n"
            f"Include this link if possible: {url}\\n\\n"
            "Output format:\\n"
            "### Twitter\\n[Content]\\n\\n"
            "### LinkedIn\\n[Content]"
        )

        return self._send_prompt(prompt)

    def analyze_visuals(self, article_content: str) -> dict:
        """
        Analyzes the article content to determine visual strategy metadata.
        Returns a dictionary with 'visual_category', 'visual_keywords', and 'visual_prompt'.
        """
        prompt = (
            "Eres el Director de Arte de 'Noticiencias'. Tu tarea es analizar el siguiente artículo y definir su estrategia visual.\n"
            "Output ONLY a valid JSON object with the following keys:\n"
            '- "visual_category": Choose exactly one from ["ENERGY", "TECH", "BIO", "SPACE", "PHYSICS", "OTHER"].\n'
            "- \"visual_keywords\": A list of 3 English keywords for finding stock images (e.g. ['laser', 'lab', 'startups']).\n"
            "- \"visual_prompt\": A high-quality GenAI prompt to generate an image (e.g. 'Cinematic shot of a fusion reactor core, blue plasma, dark sci-fi aesthetic, 8k').\n\n"
            "Article Content (Snippet):\n"
            f"{article_content[:4000]}...\n\n"
            "JSON Output:"
        )

        result = self._send_prompt(prompt)

        # Safe JSON parsing via robust extractor
        try:
            return self._extract_json(result)
        except Exception as e:
            logger.error(
                f"Failed to parse visual analysis JSON: {e} | Response snippet: {result[:100]}..."
            )
            return {
                "visual_category": "OTHER",
                "visual_keywords": [],
                "visual_prompt": "",
            }
