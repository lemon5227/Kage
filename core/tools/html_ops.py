"""HTML utilities — extract text, strip tags, truncate output."""

import re
from html.parser import HTMLParser

MAX_OUTPUT_LENGTH = 5000
TRUNCATION_MARKER = "[输出已截断]"

# Hoisted regex patterns for the strip_html_tags fallback path.
_RE_HTML_SCRIPT = re.compile(r'<script[^>]*>.*?</script>', re.DOTALL | re.IGNORECASE)
_RE_HTML_STYLE = re.compile(r'<style[^>]*>.*?</style>', re.DOTALL | re.IGNORECASE)
_RE_HTML_TAG = re.compile(r'<[^>]+>')


class HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML."""

    def __init__(self):
        super().__init__()
        self.text_parts = []
        self._skip_tags = {'script', 'style', 'head', 'meta', 'link', 'noscript'}
        self._current_skip = False

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self._skip_tags:
            self._current_skip = True

    def handle_endtag(self, tag):
        if tag.lower() in self._skip_tags:
            self._current_skip = False

    def handle_data(self, data):
        if not self._current_skip:
            text = data.strip()
            if text:
                self.text_parts.append(text)

    def get_text(self) -> str:
        return ' '.join(self.text_parts)


def strip_html_tags(html_text: str) -> str:
    """Extract plain text from HTML, removing tags, scripts, styles."""
    try:
        extractor = HTMLTextExtractor()
        extractor.feed(html_text)
        return extractor.get_text()
    except Exception:
        text = _RE_HTML_SCRIPT.sub('', html_text)
        text = _RE_HTML_STYLE.sub('', text)
        text = _RE_HTML_TAG.sub('', text)
        return ' '.join(text.split())


def truncate_output(text: str, max_length: int = MAX_OUTPUT_LENGTH) -> str:
    """Truncate output and add marker."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
