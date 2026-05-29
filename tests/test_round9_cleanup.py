"""Round 9 regression tests: avatar_animation bug fix + hot-path regex hoisting."""

import re


# ---------------------------------------------------------------------------
# AvatarAnimation.select_motion AttributeError fix
# ---------------------------------------------------------------------------

class TestAvatarAnimationSelectMotion:
    """`select_motion` was previously accessing self.motion.emotion_weights,
    but emotion_weights is on ExpressionConfig (self.expression). This caused
    an AttributeError on the first call after cooldown expired.
    """

    def test_select_motion_does_not_crash(self):
        from core.avatar_animation import AvatarAnimation
        av = AvatarAnimation()
        # Default cooldown is 4s but _last_motion_time = 0.0 so first call
        # should be unconstrained.
        out = av.select_motion("happy")
        # Should return an int index, not raise AttributeError
        assert out is None or isinstance(out, int)

    def test_select_motion_returns_index_for_known_emotion(self):
        from core.avatar_animation import AvatarAnimation
        av = AvatarAnimation()
        out = av.select_motion("happy")
        assert isinstance(out, int)
        # Must be a valid Tap or Idle index
        assert 0 <= out < max(av.motion.groups.values())

    def test_select_motion_for_unknown_emotion_uses_default_weights(self):
        """An emotion not in expression.emotion_weights should fall back to
        motion.weights without raising."""
        from core.avatar_animation import AvatarAnimation
        av = AvatarAnimation()
        out = av.select_motion("nonexistent")
        assert out is None or isinstance(out, int)


# ---------------------------------------------------------------------------
# realtime_handlers — hoisted regex patterns
# ---------------------------------------------------------------------------

class TestRealtimeHandlersHoistedPatterns:
    def test_module_level_patterns_exist(self):
        from core import realtime_handlers as rh
        for name in (
            "_RE_NVQ_TRAILING_OPEN_LONG", "_RE_NVQ_TRAILING_OPEN_SHORT",
            "_RE_NVQ_TRAILING_OPEN_PLAIN", "_RE_EVS_PREFIX_NEGATION",
            "_RE_EVS_PREFIX_REQUEST", "_RE_EVS_PREFIX_VERB",
            "_RE_EVS_SUFFIX_VIDEO", "_RE_EVS_SUFFIX_PLATFORM",
            "_RE_HAS_CJK", "_RE_CORRECTION_PREFIX",
        ):
            pat = getattr(rh, name)
            assert isinstance(pat, re.Pattern), f"{name} should be precompiled"

    def test_normalize_video_query_strips_trailing_open(self):
        from core.realtime_handlers import normalize_video_query_for_search
        assert normalize_video_query_for_search("张三的最新视频，然后打开") == "张三的最新视频"
        assert normalize_video_query_for_search("张三的视频 把它播放一下") == "张三的视频"

    def test_extract_video_subject_strips_prefixes_and_suffixes(self):
        from core.realtime_handlers import extract_video_subject
        out = extract_video_subject("帮我搜一下张三的最新视频")
        assert out == "张三", f"got {out!r}"

    def test_video_subject_match_score_uses_hoisted_cjk_pattern(self):
        from core.realtime_handlers import video_subject_match_score
        # CJK token in subject + matching title — should score 2.5
        score = video_subject_match_score("张三", {"title": "张三的频道", "url": "", "snippet": ""})
        assert score >= 2.5


# ---------------------------------------------------------------------------
# mouth — hoisted TTS cleanup patterns
# ---------------------------------------------------------------------------

class TestMouthHoistedPatterns:
    def test_module_patterns_exist(self):
        from core import mouth
        assert isinstance(mouth._RE_TTS_DISALLOWED_CHARS, re.Pattern)
        assert isinstance(mouth._RE_TTS_REPEATED_CHARS, re.Pattern)

    def test_disallowed_chars_pattern_strips_emoji(self):
        from core.mouth import _RE_TTS_DISALLOWED_CHARS
        # Emoji 🎵 is outside the whitelist
        assert _RE_TTS_DISALLOWED_CHARS.sub("", "你好 🎵 world") == "你好  world"

    def test_repeated_chars_pattern_collapses_runs(self):
        from core.mouth import _RE_TTS_REPEATED_CHARS
        assert _RE_TTS_REPEATED_CHARS.sub(r"\1", "haaaaha") == "haha"
        assert _RE_TTS_REPEATED_CHARS.sub(r"\1", "...!!!") == ".!"


# ---------------------------------------------------------------------------
# realtime_lane.extract_correction_text — hoisted
# ---------------------------------------------------------------------------

class TestExtractCorrectionTextHoisted:
    def test_pattern_hoisted(self):
        from core import realtime_lane
        assert isinstance(realtime_lane._RE_CORRECTION, re.Pattern)
        assert hasattr(realtime_lane, "_CORRECTION_STRIP_CHARS")

    def test_extracts_correction(self):
        from core.realtime_lane import extract_correction_text
        assert extract_correction_text("不是这个，是张三的视频") == "张三的视频"

    def test_returns_empty_when_no_correction(self):
        from core.realtime_lane import extract_correction_text
        assert extract_correction_text("hello") == ""


# ---------------------------------------------------------------------------
# router.KageRouter — hoisted patterns
# ---------------------------------------------------------------------------

class TestRouterHoistedPatterns:
    def test_patterns_hoisted(self):
        from core import router
        assert isinstance(router._RE_SCREENSHOT, re.Pattern)
        assert isinstance(router._RE_OPEN_APP, re.Pattern)
        assert isinstance(router._OPEN_APP_NEGATIVE_KEYWORDS, tuple)

    def test_classify_screenshot_intent(self):
        from core.router import KageRouter
        r = KageRouter()
        assert r.classify("帮我截屏") == "COMMAND"
        assert r.classify("截图") == "COMMAND"

    def test_classify_open_app_intent(self):
        from core.router import KageRouter
        r = KageRouter()
        assert r.classify("打开 Safari") == "COMMAND"

    def test_classify_open_website_falls_back_to_chat(self):
        from core.router import KageRouter
        r = KageRouter()
        # Has "打开" but also "网站"/"http" keywords → CHAT (let LLM decide)
        assert r.classify("打开网站 example.com") == "CHAT"

    def test_classify_default_is_chat(self):
        from core.router import KageRouter
        r = KageRouter()
        assert r.classify("你好啊") == "CHAT"


# ---------------------------------------------------------------------------
# tools/html_ops.strip_html_tags — hoisted fallback patterns
# ---------------------------------------------------------------------------

class TestHtmlOpsHoistedPatterns:
    def test_patterns_hoisted(self):
        from core.tools import html_ops
        assert isinstance(html_ops._RE_HTML_SCRIPT, re.Pattern)
        assert isinstance(html_ops._RE_HTML_STYLE, re.Pattern)
        assert isinstance(html_ops._RE_HTML_TAG, re.Pattern)

    def test_strip_html_tags_basic(self):
        from core.tools.html_ops import strip_html_tags
        out = strip_html_tags("<p>hello <b>world</b></p>")
        # Either parser path gives "hello world"
        assert "hello" in out and "world" in out

    def test_strip_html_tags_removes_script_blocks(self):
        from core.tools.html_ops import strip_html_tags
        out = strip_html_tags("<p>visible</p><script>alert(1)</script>")
        assert "visible" in out
        assert "alert" not in out
