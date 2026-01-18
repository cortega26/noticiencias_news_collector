from typing import Any, Dict
import re
from news_collector.storage.models import Article

class HeuristicScorer:
    """
    Deterministic fallback scorer using text statistics and heuristics
    to proxy cognitive signals (NQI v2.0) without LLM.
    """
    
    def calculate_score(self, article: Article) -> float:
        """
        Calculate a heuristic cognitive score [0, 1] based on NQI pillars.
        Weights: Substance (35%), Narrative (30%), Relevance (20%), Credibility (15%).
        """
        text = f"{article.title} {article.summary or ''} {article.content or ''}"
        
        # 1. Substance (35%) - Data Density as proxy
        substance_score = self._calculate_data_density(text)
        
        # 2. Narrative (30%) - Wow Factor + Length
        wow_score = self._evaluate_wow_factor(text)
        # Length proxy: > 1000 chars is better
        length_score = min(1.0, len(text) / 2000) 
        narrative_score = (wow_score * 0.6) + (length_score * 0.4)
        
        # 3. Relevance (20%) - LatAm Affinity + Readability
        latam_score = self._calculate_latam_affinity(text)
        # Readability proxy (sentence length)
        sentences = [s for s in text.split('.') if len(s.strip()) > 10]
        avg_len = sum(len(s.split()) for s in sentences) / max(1, len(sentences))
        readability_score = 1.0 if 15 <= avg_len <= 25 else 0.5
        
        relevance_score = max(latam_score, readability_score * 0.5) 
         # If LatAm is high, relevance is high. Else fall back to generic readability.
        
        # 4. Credibility (15%) - Structure + Title Hygiene
        # Heuristic proxy: Structure (HTML tags if present, quotes) + Title Quality
        structure_score = 0.5
        if '"' in text or '“' in text: structure_score += 0.2
        if '<p>' in text or '\n\n' in text: structure_score += 0.2
        if 'http' in text: structure_score += 0.1 # references?
        
        credibility_score = structure_score
        
        # Weighted Combination (NQI Formula)
        final_score = (
            (substance_score * 0.35) +
            (narrative_score * 0.30) +
            (relevance_score * 0.20) +
            (credibility_score * 0.15)
        )
        
        return round(max(0.0, min(1.0, final_score)), 4)
        
    def _calculate_data_density(self, text: str) -> float:
        """
        Calculate Data Density Index (DDI).
        Ratio of 'data tokens' (numbers, %, units) to total words.
        """
        if not text: return 0.0
        
        # Count data patterns
        # Years (19XX, 20XX)
        years = len(re.findall(r'\b(19|20)\d{2}\b', text))
        # Percentages
        percents = len(re.findall(r'\d+(\.\d+)?%', text))
        # Scientific notation/p-values/n=
        scientific = len(re.findall(r'n\s*=|p\s*[<>=]|×10', text, re.I))
        # General numbers (excluding single digits)
        numbers = len(re.findall(r'\b\d{2,}\b', text))
        
        total_data_points = years + percents + (scientific * 2) + numbers
        total_words = len(text.split())
        
        if total_words == 0: return 0.0
        
        # Density threshold: 2% data density is very high for news
        density = total_data_points / total_words
        
        # Normalize: 0.02 (2%) => 1.0 score
        score = min(1.0, density / 0.02)
        return score

    def _calculate_latam_affinity(self, text: str) -> float:
        """
        Calculate affinity with Latin America.
        """
        text_lower = text.lower()
        latam_keywords = [
            "méxico", "mexico", "argentina", "chile", "colombia", "brasil", "brazil",
            "perú", "peru", "uruguay", "paraguay", "bolivia", "ecuador", "venezuela",
            "costa rica", "panamá", "panama", "españa", "spain", "latinoamérica",
            "unam", "conicet", "fapesp", "tec de monterrey", "santiago", "buenos aires",
            "bogotá", "cdmx", "amazonas"
        ]
        
        hits = sum(1 for w in latam_keywords if w in text_lower)
        if hits > 0:
            return 1.0 # High relevance if even mentioned once (likely a regional study)
        return 0.0

    def _evaluate_wow_factor(self, text: str) -> float:
        text_lower = text.lower()
        idx = [
            "breakthrough", "discovery", "first", "new", "revolutionary",
            "unexpected", "major", "significant", "study", "research",
            "evidence", "found", "identified", "milestone", "record"
        ]
        hits = sum(1 for w in idx if w in text_lower)
        return min(1.0, hits / 4.0)
