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

    def _build_formatting_instructions(self) -> str:
        instructions = self._load_formatting_instructions()
        return instructions if instructions else _DEFAULT_FORMATTING_INSTRUCTIONS

    def _load_formatting_instructions(self) -> str:
        try:
            content = _FORMATTING_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            logger.warning(
                "Formatting instructions file missing: %s", _FORMATTING_PATH
            )
            return ""
        except Exception as exc:
            logger.warning(
                "Error reading formatting instructions: %s", exc
            )
            return ""

        if not content:
            logger.warning("Formatting instructions file is empty: %s", _FORMATTING_PATH)
            return ""

        return content + "\n\n"

    def _strip_emojis(self, text: str) -> str:
        return self._emoji_re.sub("", text)

    def _strip_tldr_visual(self, text: str) -> str:
        lines = text.splitlines()
        output = []
        skipping = False

        for line in lines:
            if not skipping and re.search(r"TL;DR Visual", line, flags=re.IGNORECASE):
                skipping = True
                continue

            if skipping:
                if re.match(r"^\s*\*\*.+\*\*\s*$", line):
                    skipping = False
                    output.append(line)
                else:
                    continue
            else:
                output.append(line)

        return "\n".join(output)

    def _inject_frontmatter_field(self, text: str, key: str, value: str) -> str:
        if not text.startswith("---"):
            return text

        lines = text.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is None:
            return text

        for line in lines[1:end_idx]:
            if line.strip().lower().startswith(f"{key.lower()}:"):
                return text

        insert_line = f'{key}: "{value}"'
        lines.insert(end_idx, insert_line)
        return "\n".join(lines)

    def _normalize_frontmatter_keys(self, text: str) -> str:
        if not text.startswith("---"):
            return text

        lines = text.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is None:
            return text

        normalized = []
        for line in lines[1:end_idx]:
            if ":" not in line:
                normalized.append(line)
                continue
            key, rest = line.split(":", 1)
            normalized.append(f"{key.strip().lower()}:{rest}")

        return "\n".join([lines[0], *normalized, *lines[end_idx:]])

    def _remove_frontmatter_field(self, text: str, key: str) -> str:
        if not text.startswith("---"):
            return text

        lines = text.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is None:
            return text

        key_lower = key.lower()
        filtered = [
            line
            for line in lines[1:end_idx]
            if not line.strip().lower().startswith(f"{key_lower}:")
        ]

        return "\n".join([lines[0], *filtered, *lines[end_idx:]])

    def _upsert_frontmatter_field(self, text: str, key: str, value: str) -> str:
        if not text.startswith("---"):
            return text

        lines = text.splitlines()
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is None:
            return text

        key_lower = key.lower()
        updated = False
        for idx in range(1, end_idx):
            if lines[idx].strip().lower().startswith(f"{key_lower}:"):
                lines[idx] = f'{key_lower}: "{value}"'
                updated = True
                break

        if not updated:
            lines.insert(end_idx, f'{key_lower}: "{value}"')

        return "\n".join(lines)

    def _send_prompt(self, prompt: str) -> str:
        """Helper to send prompt to Ollama with streaming handling."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True
        }

        logger.info(f"Sending prompt to Ollama ({self.model})...")
        print("Processing", end="", flush=True)
        
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
                            if len(full_text) % 5 == 0:
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

    def process_article(self, raw_text: str | dict) -> str:
        """
        Sends the content to Ollama for translation and refinement.
        Accepts either a raw text string or an article dictionary.
        """
        # Default prompt if not specified in .env
        # "Future Translator v1" Strategy
        default_instruction = (
            "Eres el Editor Visionario de 'Noticiencias'. Tu misión no es solo traducir, sino 'traducir el futuro'. "
            "Toma el siguiente texto técnico y conviértelo en una narrativa apasionante en ESPAÑOL que explique por qué esto cambia nuestras vidas.\n\n"
            + self._build_formatting_instructions()
            + "Output ONLY the final Markdown content with a YAML Frontmatter block containing "
            "title, author (AI), date (use today's date in YYYY-MM-DD format), and image (if provided). "
            "Use lowercase frontmatter keys (title, author, date, image, source_url). "
            "Ensure the frontmatter starts and ends with '---'. "
            "Do not include any preamble, just the markdown."
        )
        
        instruction = os.getenv("OLLAMA_PROMPT", default_instruction)
        
        content_to_process = ""
        image_info = ""
        source_info = ""
        has_image = False
        source_url = None

        if isinstance(raw_text, dict):
            # It's an article dictionary
            title = raw_text.get("title", "")
            summary = raw_text.get("summary", "")
            content = raw_text.get("content", "")
            image_url = raw_text.get("image_url")
            source_url = (
                raw_text.get("url")
                or (raw_text.get("metadata") or {}).get("original_url")
                or ((raw_text.get("metadata") or {}).get("source_metadata") or {}).get("entry_id")
            )
            
            content_to_process = f"Title: {title}\\n\\nSummary: {summary}\\n\\nContent: {content}"
            if image_url:
                image_info = f"\\n\\nIMPORTANT: The article has an associated image URL: {image_url}. Include this exact URL in the YAML frontmatter as 'image: {image_url}'."
                has_image = True
            if source_url:
                source_info = (
                    "\\n\\nIMPORTANT: Add a final line with the original source "
                    f"link formatted as 'Fuente original: [{source_url}]({source_url})'."
                )
        else:
            # It's just a string
            content_to_process = raw_text

        prompt = f"{instruction}{image_info}{source_info}\\n\\n---\\n\\n{content_to_process}"
        
        result_text = self._send_prompt(prompt)
        
        # Post-processing: Validate and Fix YAML Frontmatter
        if result_text.startswith("---"):
            delimiter_count = result_text.count("---")
            if delimiter_count == 1:
                lines = result_text.split('\\n')
                fixed_lines = []
                closed = False
                for i, line in enumerate(lines):
                    fixed_lines.append(line)
                    if i > 0 and not closed:
                        if line.strip() == "" or line.startswith("#"):
                            fixed_lines.insert(-1, "---")
                            closed = True
                
                if not closed:
                    fixed_lines.append("---")
                
                result_text = "\\n".join(fixed_lines)
        
        result_text = self._normalize_frontmatter_keys(result_text)

        if source_url:
            result_text = self._upsert_frontmatter_field(
                result_text, "source_url", source_url
            )

        if has_image and image_url:
            result_text = self._upsert_frontmatter_field(
                result_text, "image", image_url
            )
        else:
            result_text = self._remove_frontmatter_field(result_text, "image")

        if not has_image:
            result_text = self._strip_tldr_visual(result_text)

        if source_url and not re.search(
            r"Fuente original:", result_text, flags=re.IGNORECASE
        ):
            result_text = (
                result_text.rstrip()
                + f"\\n\\nFuente original: [{source_url}]({source_url})\\n"
            )

        result_text = self._strip_emojis(result_text)
        return result_text

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
