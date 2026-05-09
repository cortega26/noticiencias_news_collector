from news_collector.validation.rules import (
    BlocklistPatternRule,
    MinContentLengthRule,
    NewsletterContentRule,
    TitleBodyRelevanceRule,
)
from news_collector.validation.validator import ContentValidator


class TestContentValidator:

    def test_min_content_length_rule(self):
        rule = MinContentLengthRule(min_words=5)

        # Valid article
        valid_article = {"content": "one two three four five six"}
        assert rule.validate(valid_article).is_valid is True

        # Invalid article
        invalid_article = {"content": "one two three"}
        result = rule.validate(invalid_article)
        assert result.is_valid is False
        assert "Content too short" in result.reason

    def test_blocklist_pattern_rule(self):
        rule = BlocklistPatternRule(patterns=[r"The Download:.*"])

        # Valid article
        valid_article = {"title": "Normal AI News"}
        assert rule.validate(valid_article).is_valid is True

        # Invalid article (The Download)
        invalid_article = {"title": "The Download: cut through AI coding hype"}
        result = rule.validate(invalid_article)
        assert result.is_valid is False
        assert "matches blocklist pattern" in result.reason

    def test_title_body_relevance_rule(self):
        rule = TitleBodyRelevanceRule(min_match_ratio=0.5)

        # Valid article (title words appear in content)
        valid_article = {
            "title": "Machine Learning",
            "content": "This article discusses machine learning concepts.",
        }
        assert rule.validate(valid_article).is_valid is True

        # Invalid article (irrelevant content)
        invalid_article = {
            "title": "Machine Learning",
            "content": "This article is about cooking pasta.",
        }
        result = rule.validate(invalid_article)
        assert result.is_valid is False
        assert "Title relevance too low" in result.reason

    def test_newsletter_content_rule(self):
        rule = NewsletterContentRule()

        # Valid article
        valid_article = {
            "content": "Just a normal news article content without patterns."
        }
        assert rule.validate(valid_article).is_valid is True

        # Invalid article (Newsletter pattern)
        invalid_article = {
            "content": "This is today's edition of The Download, our weekday newsletter."
        }
        result = rule.validate(invalid_article)
        assert result.is_valid is False
        assert "Content appears to be a newsletter" in result.reason

    def test_validator_batch(self):
        validator = ContentValidator()
        # Ensure default blocklist is present

        articles = [
            {
                "title": "Valid Article",
                "content": "This is a Valid Article with long enough content " * 10,
            },
            {
                "title": "The Download: Something bad",
                "content": "This is a long enough content " * 10,
            },
            {"title": "Short", "content": "Too short"},
        ]

        results = validator.validate_batch(articles)

        assert len(results["valid"]) == 1
        assert results["valid"][0]["title"] == "Valid Article"

        assert len(results["invalid"]) == 2
        titles = sorted([item["article"]["title"] for item in results["invalid"]])
        assert titles == ["Short", "The Download: Something bad"]

    def test_validator_rejects_commerce_title_patterns(self):
        validator = ContentValidator()

        article = {
            "title": "Prime Day deal: the best laptops to buy before the sale ends",
            "content": (
                "Prime Day deal coverage about the best laptops to buy before the sale ends. " * 12
            ),
        }

        result = validator.validate_article(article)

        assert result.is_valid is False
        assert result.rule_name == "blocklist_pattern"

    def test_validator_rejects_politics_and_lifestyle_title_patterns(self):
        validator = ContentValidator()

        politics_article = {
            "title": "Election campaign enters final week after candidate debate",
            "content": (
                "Election campaign coverage enters the final week after a candidate debate. " * 12
            ),
        }
        lifestyle_article = {
            "title": "Travel guide: the hotel deal and packing list you need this summer",
            "content": (
                "Travel guide coverage of a hotel deal and packing list for the summer. " * 12
            ),
        }

        politics_result = validator.validate_article(politics_article)
        lifestyle_result = validator.validate_article(lifestyle_article)

        assert politics_result.is_valid is False
        assert politics_result.rule_name == "blocklist_pattern"
        assert lifestyle_result.is_valid is False
        assert lifestyle_result.rule_name == "blocklist_pattern"
