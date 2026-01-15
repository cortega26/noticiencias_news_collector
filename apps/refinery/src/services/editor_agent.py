import requests
import json
import time
import os
import re
from pathlib import Path
from src.utils.logger import setup_logger

logger = setup_logger("EditorAgent")

_FORMATTING_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "editor_formatting.md"
)

_DEFAULT_FORMATTING_INSTRUCTIONS = (
    "## 1. Reglas de Estilo (La Voz)\n"
    "- **Tono**: Visionario pero accesible. Piensa en un documental de alta gama.\n"
    "- **Prohibido**: No uses jerga académica sin explicarla. No uses 'voz pasiva' (e.g. 'fue descubierto').\n"
    "- **Obligatorio**: Usa analogías cotidianas para conceptos complejos.\n"
    "- **Prohibido**: No uses emojis en ninguna parte del texto.\n\n"
    "## 2. El Titular (Gancho Cognitivo)\n"
    "Escribe un título que combine BENFFICIO + CURIOSIDAD. Nada de 'Nuevo estudio revela...'.\n"
    "- Malo: 'Avance en fusión nuclear en NIF'\n"
    "- Bueno: 'Adiós a la factura de luz: La fusión nuclear ya es rentable'\n\n"
    "## 3. Estructura del Artículo (Estricta)\n"
    "Tu output debe seguir este orden:\n\n"
    "Si hay URL de imagen, incluye una sección '**TL;DR Visual**' con 3 puntos bala. Si no hay imagen, omite esta sección por completo.\n\n"
    "**El Impacto (Lead)**\n"
    "- Empieza con el futuro. ¿Cómo se ve el mundo con esto? No empieces con 'Científicos de la universidad de...'.\n\n"
    "**La Anomalía (El Problema)**\n"
    "- ¿Por qué no teníamos esto antes? ¿Cuál era el obstáculo?\n\n"
    "**La Solución (El Hallazgo)**\n"
    "- Explica el 'cómo' usando una analogía simple.\n\n"
    "**Lo Que No Sabemos (Honestidad)**\n"
    "- ¿Qué falta? ¿Cuándo llegará a mi casa? Sé brutalmente honesto.\n\n"
)

class EditorAgent:
    def __init__(self, api_url: str, model: str):
        self.api_url = api_url
        self.model = model
        self._emoji_re = re.compile(
            r"[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U00002600-\U000026FF]",
            flags=re.UNICODE,
        )
        self.prompts = self._load_prompts()

    def _load_prompts(self) -> dict:
        """Loads prompt templates from yaml config."""
        prompts_path = Path(__file__).resolve().parents[2] / "config" / "prompts.yaml"
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

    # ... (Keep helper methods _strip_emojis, _inject_frontmatter_field etc. if needed) ...
    # Re-implementing helper methods locally to ensure they are available within the class scope
    
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
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True
        }
        if system:
            payload["system"] = system

        logger.info(f"Sending prompt to Ollama ({self.model})...")
        print(f"Processing ({system[:20]}...)", end="", flush=True)
        
        try:
            start_time = time.time()
            response = requests.post(self.api_url, json=payload, stream=True, timeout=900)
            response.raise_for_status()
            
            full_text = []
            
            for line in response.iter_lines():
                if line:
                    try:
                        json_response = json.loads(line)
                        if 'response' in json_response:
                            chunk = json_response['response']
                            full_text.append(chunk)
                            # Feedback dot every 5 chunks
                            if len(full_text) % 20 == 0:
                                print(".", end="", flush=True)
                        if json_response.get('done', False):
                            break
                    except json.JSONDecodeError:
                        continue
            
            print(" Done!")
            duration = time.time() - start_time
            logger.info(f"Ollama processing complete in {duration:.2f} seconds.")
            
            return "".join(full_text).strip()
            
        except requests.exceptions.RequestException as e:
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

    def _generate_headlines(self, adapted_content: str) -> dict:
        """Stage 3: Headline Generation"""
        system_prompt = self.prompts.get("headline", {}).get("system", "")
        # Prompt explicitly for JSON in the message body as well to be safe
        prompt = f"Analyze this article and generate headlines keys: direct, question, benefit.\n\n{adapted_content[:2000]}"
        response = self._send_prompt(prompt, system=system_prompt)
        
        try:
            # Try to find JSON block
            match = re.search(r"\{.*\}", response, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(response)
        except:
            return {"direct": "Error generating headline", "question": "", "benefit": ""}

    def process_article(self, raw_text: str | dict) -> str:
        """
        Orchestrate the 3-stage pipeline: Translate -> Adapt -> Metadata.
        """
        # 1. Extract Info
        title = ""
        summary = ""
        content = ""
        image_url = None
        source_url = None
        
        if isinstance(raw_text, dict):
            title = raw_text.get("title", "")
            summary = raw_text.get("summary", "")
            content = raw_text.get("content", "")
            image_url = raw_text.get("image_url")
            source_url = (
                raw_text.get("url")
                or (raw_text.get("metadata") or {}).get("original_url")
                or ((raw_text.get("metadata") or {}).get("source_metadata") or {}).get("entry_id")
            )
        else:
            content = raw_text

        input_text = f"Title: {title}\nSummary: {summary}\nContent: {content}"
        
        # 2. Pipeline Execution
        print("\n--- STAGE 1: Scientific Translation ---")
        translated_text = self._translate_scientific(input_text)
        
        print("\n--- STAGE 2: Editorial Adaptation ---")
        # We pass the translated text to the editor
        final_content = self._adapt_editorial(translated_text)
        final_content = self._extract_markdown_content(final_content) # Cleanup
        
        print("\n--- STAGE 3: Metadata & Headlines ---")
        headlines = self._generate_headlines(final_content)
        
        # 3. Assemble Final Artifact
        # Choose the 'direct' headline by default or a combination
        final_title = headlines.get("direct", title) # Fallback to original if fail
        
        # Construct Frontmatter
        metadata_block = [
            "---",
            f"title: \"{final_title}\"",
            f"date: \"{time.strftime('%Y-%m-%d')}\"",
            "author: \"Noticiencias AI\"",
        ]
        
        if image_url:
            metadata_block.append(f"image: \"{image_url}\"")
        if source_url:
            metadata_block.append(f"source_url: \"{source_url}\"")
            
        # Add generated headlines as hidden metadata for A/B testing potential
        metadata_block.append(f"headlines_variants:")
        metadata_block.append(f"  question: \"{headlines.get('question', '')}\"")
        metadata_block.append(f"  benefit: \"{headlines.get('benefit', '')}\"")
        
        metadata_block.append("---\n")
        
        full_article = "\n".join(metadata_block) + "\n" + final_content
        
        # Append source link footer if missing
        if source_url and "Fuente original" not in full_article:
             full_article += f"\n\nFuente original: [{source_url}]({source_url})"
             
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
        
        # Safe JSON parsing
        try:
            # Strip markdown code blocks if present
            clean_result = result.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_result)
            return data
        except json.JSONDecodeError:
            logger.error(f"Failed to parse visual analysis JSON: {result}")
            return {
                "visual_category": "OTHER",
                "visual_keywords": [],
                "visual_prompt": ""
            }
