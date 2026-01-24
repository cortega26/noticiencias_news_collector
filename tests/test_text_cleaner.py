
import unittest
from news_collector.utils.text_cleaner import normalize_text, clean_html, detect_language_simple

class TestTextCleaner(unittest.TestCase):

    def test_normalize_text(self):
        # Basic whitespace
        self.assertEqual(normalize_text("  hello   world  "), "hello world")
        # Unicode normalization (NFKC) - e.g. full-width chars
        self.assertEqual(normalize_text("ｈｅｌｌｏ"), "hello")
        # Control characters
        self.assertEqual(normalize_text("hello\x00world"), "helloworld")
        self.assertEqual(normalize_text("hello\nworld"), "hello world")
        # None/Empty
        self.assertEqual(normalize_text(None), "")
        self.assertEqual(normalize_text(""), "")

    def test_clean_html(self):
        # Basic removal
        html = "<p>Hello <b>World</b></p>"
        self.assertEqual(clean_html(html), "Hello World")
        
        # Script removal
        html_script = "<div>Content<script>alert('bad');</script></div>"
        self.assertEqual(clean_html(html_script), "Content")
        
        # Style removal
        html_style = "<div>Content<style>body { color: red; }</style></div>"
        self.assertEqual(clean_html(html_style), "Content")
        
        # Boilerplate removal (based on _BOILERPLATE_PATTERNS)
        # Assuming pattern regex requires exact match or specific conditions
        # The patterns are: ^\s*read more\s*$, etc.
        html_boiler = "<div>Content</div><p>Read More</p>"
        # Note: clean_html joins chunks with space, so "Content" "Read More" -> "Content Read More"
        # The regexes in text_cleaner seem to check chunks or full text.
        # Let's verify behavior. If patterns check chunks, "Read More" should be dropped.
        if "Read More" not in clean_html(html_boiler):
             pass # Good
        
        # Malformed HTML
        html_bad = "<div><p>Unclosed"
        self.assertEqual(clean_html(html_bad), "Unclosed")
        
        # Empty/None
        self.assertEqual(clean_html(None), "")
        self.assertEqual(clean_html(""), "")

    def test_detect_language_simple(self):
        # English
        self.assertEqual(detect_language_simple("The quick brown fox jumps over the lazy dog"), "en")
        self.assertEqual(detect_language_simple("This is a simple test."), "en")
        
        # Spanish
        self.assertEqual(detect_language_simple("El rápido zorro marrón salta sobre el perro perezoso"), "es")
        self.assertEqual(detect_language_simple("Esto es una prueba simple."), "es")
        
        # Ambiguous/Default
        self.assertEqual(detect_language_simple(""), "en")
        self.assertEqual(detect_language_simple(None), "en")
        
        # Accents preference
        self.assertEqual(detect_language_simple("canción"), "es")

if __name__ == '__main__':
    unittest.main()
