"""
Kage Constants — centralized magic numbers and configuration defaults.

All numeric/string constants that appear in multiple places should be
defined here instead of being hard-coded inline.
"""

# ============================================================================
# Server
# ============================================================================
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_SERVER_PORT = 12345

# ============================================================================
# Local Model Runtime
# ============================================================================
DEFAULT_LLM_HOST = "127.0.0.1"
DEFAULT_LLM_PORT = 8080
DEFAULT_LLM_CTX = 8192
DEFAULT_LLM_MAX_TOKENS = 1024
DEFAULT_LLM_TEMPERATURE = 0.7
DEFAULT_LLM_TOP_P = 0.8
DEFAULT_LLM_TOP_K = 20
DEFAULT_LLM_MIN_P = 0.0
DEFAULT_LLM_PRESENCE_PENALTY = 1.5
DEFAULT_LLM_NGL = 99
DEFAULT_LLM_TIMEOUT_SEC = 120

# ============================================================================
# Cache TTLs (seconds)
# ============================================================================
CACHE_TTL_ONE_DAY = 86400
CACHE_TTL_THIRTY_MIN = 1800
CACHE_TTL_FIVE_MIN = 300
CACHE_TTL_WEATHER = CACHE_TTL_THIRTY_MIN
CACHE_TTL_LOCATION = CACHE_TTL_ONE_DAY

# ============================================================================
# Memory
# ============================================================================
MEMORY_DEDUPLICATE_THRESHOLD = 0.85
MEMORY_MERGE_THRESHOLD = 0.75
MEMORY_BM25_WEIGHT = 0.3
MEMORY_VECTOR_WEIGHT = 0.7
MEMORY_FORGET_MAX_AGE_DAYS = 90
MEMORY_FORGET_MIN_IMPORTANCE = 2
MEMORY_KEEP_RECENT_DAYS = 7
MEMORY_FACT_BATCH_SIZE = 3

# ============================================================================
# Chat
# ============================================================================
CHAT_MAX_RESPONSE_LEN = 40

# ============================================================================
# Session
# ============================================================================
SESSION_MAX_HISTORY = 20
SESSION_IDLE_TIMEOUT_SEC = 1800
SESSION_CURRENT_FILENAME = "current.jsonl"

# ============================================================================
# Audio
# ============================================================================
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_SAMPLE_WIDTH = 2  # 16-bit PCM

# ============================================================================
# Agentic Loop
# ============================================================================
AGENTIC_MAX_STEPS = 10
AGENTIC_MAX_TOKENS_TEXT = 200
AGENTIC_MAX_TOKENS_TOOLS = 300

# ============================================================================
# Motion / Expression
# ============================================================================
MOTION_COOLDOWN_SEC = 4.0
MOTION_COOLDOWN_MIN_SEC = 2.5
MOTION_COOLDOWN_MAX_SEC = 6.0
EXPRESSION_DURATION_BASE_SEC = 2.5
EXPRESSION_DURATION_PER_CHAR = 0.04
EXPRESSION_DURATION_MIN_SEC = 2.0
EXPRESSION_DURATION_MAX_SEC = 6.0


