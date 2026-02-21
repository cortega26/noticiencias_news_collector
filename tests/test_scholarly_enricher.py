from news_collector.enrichment.scholarly import ScholarlyMetadataEnricher


class TestScholarlyMetadataEnricher:

    def test_extract_doi(self):
        enricher = ScholarlyMetadataEnricher()

        # Test standard URL
        url1 = "https://science.org/doi/10.1126/science.ade7521"
        assert enricher.extract_doi(url1) == "10.1126/science.ade7521"

        # Test URL with trailing parameters
        url2 = "https://www.nature.com/articles/s41586-023-06000-0?rss=yes"
        # Note: Nature DOIs are often mapped from article paths, but let's test a direct DOI pattern
        # Actually Nature RSS uses http://dx.doi.org/10.1038/... or similar often.
        # Let's test a direct DOI string match which is what we built
        url3 = "http://dx.doi.org/10.1038/s41586-023-06000-0"
        assert enricher.extract_doi(url3) == "10.1038/s41586-023-06000-0"

        # Test URL where DOI is path param
        url4 = "https://nejm.org/doi/full/10.1056/NEJMoa2210000"
        assert enricher.extract_doi(url4) == "10.1056/NEJMoa2210000"

    def test_format_content_success(self):
        enricher = ScholarlyMetadataEnricher()
        metadata = {
            "title": ["A Breakthrough in Science"],
            "author": [
                {"given": "Jane", "family": "Doe"},
                {"given": "John", "family": "Smith"},
            ],
            "container-title": ["Journal of Testing"],
            "created": {"date-parts": [[2023, 10, 1]]},
            "DOI": "10.1000/123",
            "abstract": "<jats:p>This is a significant abstract that explains the breakthrough.</jats:p>",
        }

        content = enricher.format_content(metadata, "http://original.url")

        assert "# A Breakthrough in Science" in content
        # Author format might be different or ordered differently, flexible check
        assert "Jane Doe" in content
        assert "John Smith" in content
        assert "Journal of Testing (2023)" in content
        assert "http://original.url" in content
        assert "This is a significant abstract" in content
        # Check clean up
        assert "<jats:p>" not in content

        # Length check (we want it to be reasonably long,
        # though this mock text is short, the template adds boilerplate)
        assert len(content) > 200

    def test_format_content_no_abstract(self):
        enricher = ScholarlyMetadataEnricher()
        metadata = {"title": ["No Abstract Paper"], "DOI": "10.1000/noabs"}
        # Should return None if no abstract
        assert enricher.format_content(metadata, "url") is None

    def test_enrich_url_mocked(self):
        from unittest.mock import Mock, patch

        # Mock Session inside ScholarlyMetadataEnricher
        enricher = ScholarlyMetadataEnricher()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "message": {
                "title": ["Mocked Title"],
                "DOI": "10.1111/mocked",
                "abstract": "This is a mocked abstract needed to pass the length check"
                * 10,  # Make it long enough
                "author": [{"family": "Tester"}],
            }
        }

        # Patch the session.get method directly
        with patch.object(enricher.session, "get", return_value=mock_response):
            result = enricher.enrich_url("https://doi.org/10.1111/mocked")

            assert result["success"] is True
            assert "Mocked Title" in result["content"]
            assert result["metadata"]["DOI"] == "10.1111/mocked"
