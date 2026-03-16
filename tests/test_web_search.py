import unittest


from core.tools_impl import parse_duckduckgo_html


class TestWebSearchParsing(unittest.TestCase):
    def test_parse_duckduckgo_html(self):
        sample = (
            '<div class="results">'
            '<a class="result__a" rel="nofollow" href="https://example.com/a">Title A</a>'
            '<a class="result__a" rel="nofollow" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fb">Title B</a>'
            '</div>'
        )
        items = parse_duckduckgo_html(sample, max_results=5)
        self.assertEqual(items[0][0], "Title A")
        self.assertEqual(items[0][1], "https://example.com/a")
        self.assertEqual(items[1][0], "Title B")
        self.assertEqual(items[1][1], "https://example.com/b")


if __name__ == "__main__":
    unittest.main(verbosity=2)
