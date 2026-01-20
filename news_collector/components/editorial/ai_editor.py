import requests
import json
import time
import os
import re
from pathlib import Path
from news_collector.utils.logger import get_logger
from news_collector.infrastructure.llm.provider import OllamaProvider

# Use the centralized logger factory
logger = get_logger().create_module_logger("components.editorial.ai_editor")
from noticiencias.config_manager import load_config

class EditorAgent:
    def __init__(self, api_url: str, model: str):
        self.api_url = api_url
        self.model = model
        self.cache_dir = Path("temp/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._emoji_re = re.compile(
            r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]",
            flags=re.UNICODE,
        )
        try:
            self.min_content_length = load_config().text_processing.min_content_length
        except Exception:
            self.min_content_length = 750 # Fallback
            
        self.prompts = self._load_prompts()
        
        # Initialize unified provider
        # Note: ai_editor uses a higher timeout (900s) than default
        self.provider = OllamaProvider(
            api_url=self.api_url, 
            model=self.model,
            timeout=900
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
                return yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
        except ImportError:
            logger.warning("PyYAML not installed, falling back to basic prompts.")
        except Exception as e:
            logger.error(f"Error loading prompts: {e}")
        
        # Fallback prompts if file missing or parse error
        return {
            "translator": {"system": "Translate to Spanish. Keep it neutral."},
            "editor": {"system": "Rewrite as a science journalist for LatAm. No hype."},
            "headline": {"system": "Generate 3 headlines (json)."}
        }

    def _strip_emojis(self, text: str) -> str:
        return self._emoji_re.sub("", text)

    def _inject_frontmatter_field(self, text: str, key: str, value: str) -> str:
        if not text.startswith("---"):
            return f"---\n{key}: \"{value}\"\n---\n\n{text}"
            
        lines = text.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        
        if end_idx is None:
             return f"---\n{key}: \"{value}\"\n---\n\n{text}"

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


    def _send_prompt(self, prompt: str, system: str = None) -> str:
        """Helper to send prompt to Ollama with streaming handling."""
        logger.info(f"Sending prompt to Ollama ({self.model})...")
        sys_preview = (system or "")[:20]
        print(f"Processing ({sys_preview}...)", end="", flush=True)
        
        try:
            start_time = time.time()
            # Use provider's sync iterator which handles retries
            generator = self.provider.generate_sync(prompt, system=system, stream=True)
            
            full_text = []
            count = 0
            for chunk in generator:
                full_text.append(chunk)
                count += 1
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

    def _translate_scientific(self, content: str) -> str:
        """Stage 1: Scientific Translation"""
        system_prompt = self.prompts.get("translator", {}).get("system", "")
        return self._send_prompt(content, system=system_prompt)

    def _adapt_editorial(self, translated_content: str) -> str:
        """Stage 2: Editorial Adaptation"""
        system_prompt = self.prompts.get("editor", {}).get("system", "")
        return self._send_prompt(translated_content, system=system_prompt)

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

    def _generate_headlines(self, adapted_content: str) -> dict:
        """Stage 3: Headline Generation"""
        system_prompt = self.prompts.get("headline", {}).get("system", "")
        # Prompt explicitly for JSON in the message body as well to be safe
        prompt = f"Analyze this article and generate headlines keys: direct, question, benefit.\n\n{adapted_content[:2000]}"
        response = self._send_prompt(prompt, system=system_prompt)
        
        try:
            return self._extract_json(response)
        except Exception as e:
            logger.error(f"Failed to generate headlines: {e} | Response snippet: {response[:100]}...")
            # Fallback to empty if fails, don't crash the whole pipeline, 
            # OR raise if strictly required. The original code raised, so let's log and re-raise or return empty?
            # Original raised ValueError.
            raise ValueError(f"Failed to generate headlines: {e}") from e

    def _get_cache_path(self, article_id: str, stage: str) -> Path:
        """Returns the path for a cached stage artifact."""
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(article_id))
        return self.cache_dir / f"{safe_id}_{stage}.txt"

    def process_article(self, raw_text: str | dict) -> str:
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
        article_id = "unknown"
        
        if isinstance(raw_text, dict):
            title = raw_text.get("title", "") or ""
            summary = raw_text.get("summary", "") or ""
            content = raw_text.get("content", "") or ""
            
            # Fallback for RSS feeds where "content" is often in "summary"
            if not content and summary:
                 content = summary

            image_url = raw_text.get("image_url")
            source_url = (
                raw_text.get("url")
                or (raw_text.get("metadata") or {}).get("original_url")
                or ((raw_text.get("metadata") or {}).get("source_metadata") or {}).get("entry_id")
            )
            raw_category = (raw_text.get("metadata") or {}).get("category", "other")
            article_id = str(raw_text.get("id") or "unknown")
        else:
            content = raw_text
            import hashlib
            article_id = hashlib.md5(content.encode()).hexdigest()[:8]
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
            "multidisciplinary": "Ciencia"
        }
        
        final_category = category_map.get(raw_category, "Ciencia")

        input_text = f"Title: {title}\nContent: {content}"
        
        # Validation: content length
        if len(content.strip()) < self.min_content_length:
             raise ValueError(f"Content too short ({len(content)} chars). Likely paywalled or empty.")

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
             final_content = self._extract_markdown_content(final_content) # Cleanup
             cache_s2.write_text(final_content, encoding="utf-8")
        
        # --- STAGE 3: Metadata & Headlines ---
        print("\n--- STAGE 3: Metadata & Headlines ---")
        # Stage 3 is fast enough relative to others, and depends on final content structure.
        # We could cache it, but usually we want to regenerate headlines if we tweak code.
        # For now, we won't cache Stage 3 to allow easier re-runs of the final formatting.
        headlines = self._generate_headlines(final_content)
        
        # 3. Assemble Final Artifact
        # Choose the 'direct' headline by default or a combination
        final_title = headlines.get("direct", title) # Fallback to original if fail
        
        # Sanitize title: ensure it's a string and not a list representation
        if isinstance(final_title, list):
            final_title = final_title[0] if final_title else "Untitled"
        final_title = str(final_title).replace('"', '\\"')
        
        # Construct Frontmatter
        metadata_block = [
            "---",
            f"title: \"{final_title}\"",
            f"date: {time.strftime('%Y-%m-%d')}",
            "author: \"Noticiencias AI\"",
            f"categories: [\"{final_category}\"]",
            f"tags: [\"{raw_category}\"]"
        ]
        
        if image_url:
            metadata_block.append(f"image: \"{image_url}\"")
        if source_url:
            metadata_block.append(f"source_url: \"{source_url}\"")
        
        if article_id != "unknown":
             metadata_block.append(f"refinery_id: \"{article_id}\"")

        # Add generated headlines as hidden metadata for A/B testing potential
        metadata_block.append(f"headlines_variants:")
        metadata_block.append(f"  question: \"{headlines.get('question', '')}\"")
        metadata_block.append(f"  benefit: \"{headlines.get('benefit', '')}\"")
        
        metadata_block.append("---\n")
        
        full_article = "\n".join(metadata_block) + "\n" + final_content
        
        # Append source link footer if missing
        if source_url and "Fuente original" not in full_article:
             full_article += f"\n\nFuente original: [{source_url}]({source_url})"

        # Logic to strip Visual planning section if no image is present (Rule from tests)
        if not image_url:
            # Regex to remove **TL;DR Visual**... up to next **Header** or end of string
            # Using DOTALL to match newlines
            full_article = re.sub(
                r"\*\*TL;DR Visual\*\*.*?(?=\*\*|$)", 
                "", 
                full_article, 
                flags=re.DOTALL | re.MULTILINE
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
            "- \"visual_category\": Choose exactly one from [\"ENERGY\", \"TECH\", \"BIO\", \"SPACE\", \"PHYSICS\", \"OTHER\"].\n"
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
            logger.error(f"Failed to parse visual analysis JSON: {e} | Response snippet: {result[:100]}...")
            return {
                "visual_category": "OTHER",
                "visual_keywords": [],
                "visual_prompt": ""
            }
