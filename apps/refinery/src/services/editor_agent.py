import requests
import json
import time
import os
from src.utils.logger import setup_logger

logger = setup_logger("EditorAgent")

class EditorAgent:
    def __init__(self, api_url: str, model: str):
        self.api_url = api_url
        self.model = model

    def process_article(self, raw_text: str | dict) -> str:
        """
        Sends the content to Ollama for translation and refinement.
        Accepts either a raw text string or an article dictionary.
        """
        # Default prompt if not specified in .env
        default_instruction = (
            "You are a science communicator for 'Noticiencias'. "
            "Translate the following technical text to Spanish. "
            "Then, rewrite it to be punchy, engaging, and easy to understand for a general audience. "
            "Maintain accuracy but improve flow. "
            "Output ONLY the final Markdown content with a YAML Frontmatter block containing "
            "title, author (AI), date (use today's date in YYYY-MM-DD format), and image (if provided). "
            "Ensure the frontmatter starts and ends with '---'. "
            "Do not include any preamble, just the markdown."
        )
        
        instruction = os.getenv("OLLAMA_PROMPT", default_instruction)
        
        content_to_process = ""
        image_info = ""

        if isinstance(raw_text, dict):
            # It's an article dictionary
            title = raw_text.get("title", "")
            summary = raw_text.get("summary", "")
            content = raw_text.get("content", "")
            image_url = raw_text.get("image_url")
            
            content_to_process = f"Title: {title}\n\nSummary: {summary}\n\nContent: {content}"
            if image_url:
                image_info = f"\n\nIMPORTANT: The article has an associated image URL: {image_url}. Include this exact URL in the YAML frontmatter as 'image: {image_url}'."
        else:
            # It's just a string
            content_to_process = raw_text

        prompt = f"{instruction}{image_info}\n\n---\n\n{content_to_process}"

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
        default_instruction = (
            "You are a science communicator for 'Noticiencias'. "
            "Translate the following technical text to Spanish. "
            "Then, rewrite it to be punchy, engaging, and easy to understand for a general audience. "
            "Maintain accuracy but improve flow. "
            "Output ONLY the final Markdown content with a YAML Frontmatter block containing "
            "title, author (AI), date (use today's date in YYYY-MM-DD format), and image (if provided). "
            "Ensure the frontmatter starts and ends with '---'. "
            "Do not include any preamble, just the markdown."
        )
        
        instruction = os.getenv("OLLAMA_PROMPT", default_instruction)
        
        content_to_process = ""
        image_info = ""

        if isinstance(raw_text, dict):
            # It's an article dictionary
            title = raw_text.get("title", "")
            summary = raw_text.get("summary", "")
            content = raw_text.get("content", "")
            image_url = raw_text.get("image_url")
            
            content_to_process = f"Title: {title}\\n\\nSummary: {summary}\\n\\nContent: {content}"
            if image_url:
                image_info = f"\\n\\nIMPORTANT: The article has an associated image URL: {image_url}. Include this exact URL in the YAML frontmatter as 'image: {image_url}'."
        else:
            # It's just a string
            content_to_process = raw_text

        prompt = f"{instruction}{image_info}\\n\\n---\\n\\n{content_to_process}"
        
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
        
        return result_text

    def generate_social_content(self, article_content: str, url: str = "") -> str:
        """Generates social media posts (Twitter/LinkedIn) for the refined article."""
        
        prompt = (
            "You are a social media manager for the science news site 'Noticiencias'. "
            "Based on the following article content (which is in Spanish), generate two social media posts:\\n\\n"
            "1. **Twitter/X Post**: Engaging, under 280 characters, includes emojis and hashtags. Language: Spanish.\\n"
            "2. **LinkedIn Post**: Professional but engaging, summarizes the key finding. Language: Spanish.\\n\\n"
            f"Article Content:\\n{article_content[:3000]}...\\n\\n"
            f"Include this link if possible: {url}\\n\\n"
            "Output format:\\n"
            "### Twitter\\n[Content]\\n\\n"
            "### LinkedIn\\n[Content]"
        )
        
        return self._send_prompt(prompt)
