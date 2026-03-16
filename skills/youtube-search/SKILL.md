---
name: youtube-search
description: Search YouTube for videos and optionally open the best match.
---

# YouTube Search

When the user asks to find a YouTube video, do this:

1) Call `smart_search` with query: `site:youtube.com <user query>`.
2) Present 3-5 results with titles and URLs.
3) If the user asks to open, call `open_url` with the selected URL (or use `search_and_open` if appropriate).

Notes:
- Prefer showing options first; do not open automatically unless the user says "open".
- Avoid fabricated URLs; only open URLs returned by tools.
