import unittest

from core.tools_impl import parse_duckduckgo_html


class TestWebSearchParsing(unittest.TestCase):
    def test_parse_duckduckgo_html(self):
        sample = (
            '<div class="results">'
            '<a class="result__a" rel="nofollow" href="https://example.com/a">Title A</a>'
            '<a class="result__a" rel="nofollow" href="https://example.com/b">Title B</a>'
            '</div>'
        )
        items = parse_duckduckgo_html(sample, max_results=5)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0][0], "Title A")
        self.assertEqual(items[0][1], "https://example.com/a")
        self.assertEqual(items[1][0], "Title B")
        self.assertEqual(items[1][1], "https://example.com/b")

    def test_parse_empty_html(self):
        items = parse_duckduckgo_html("", max_results=5)
        self.assertEqual(items, [])

    def test_parse_respects_max_results(self):
        sample = ''.join(
            f'<a class="result__a" href="https://example.com/{i}">Title {i}</a>'
            for i in range(10)
        )
        items = parse_duckduckgo_html(sample, max_results=3)
        self.assertEqual(len(items), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
