"""
Round 15 Unit Tests - TASK-6: Centralized Constants and Domain Exceptions
Verifies constants definitions, domain exception hierarchy, and module integration.
"""

import pytest
from core.constants import (
    SESSION_MAX_HISTORY,
    SESSION_IDLE_TIMEOUT_SEC,
    SESSION_CURRENT_FILENAME,
    AUDIO_SAMPLE_RATE,
    AUDIO_CHANNELS,
    AUDIO_SAMPLE_WIDTH,
    MEMORY_DEDUPLICATE_THRESHOLD,
    MEMORY_MERGE_THRESHOLD,
    DEFAULT_SERVER_PORT,
)
from core.exceptions import (
    KageError,
    ModelError,
    ModelCallError,
    ModelLoadError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolArgumentError,
    ProviderError,
    SessionError,
    SessionCorruptedError,
    NetworkError,
    ConfigError,
    MemoryError,
    AudioError,
    AvatarError,
    ServerError,
)
from core.session_manager import (
    MAX_HISTORY,
    IDLE_TIMEOUT_SEC,
    CURRENT_FILENAME,
)


class TestConstantsAndExceptions:
    def test_constants_values_and_types(self):
        assert SESSION_MAX_HISTORY == 20
        assert SESSION_IDLE_TIMEOUT_SEC == 1800
        assert SESSION_CURRENT_FILENAME == "current.jsonl"
        assert AUDIO_SAMPLE_RATE == 16000
        assert AUDIO_CHANNELS == 1
        assert AUDIO_SAMPLE_WIDTH == 2
        assert MEMORY_DEDUPLICATE_THRESHOLD == 0.85
        assert MEMORY_MERGE_THRESHOLD == 0.75
        assert DEFAULT_SERVER_PORT == 12345

    def test_session_manager_constants_integration(self):
        assert MAX_HISTORY == SESSION_MAX_HISTORY
        assert IDLE_TIMEOUT_SEC == SESSION_IDLE_TIMEOUT_SEC
        assert CURRENT_FILENAME == SESSION_CURRENT_FILENAME

    def test_exception_inheritance_tree(self):
        # Base
        assert issubclass(ModelError, KageError)
        assert issubclass(ToolExecutionError, KageError)
        assert issubclass(SessionError, KageError)
        assert issubclass(NetworkError, KageError)
        assert issubclass(ConfigError, KageError)
        assert issubclass(MemoryError, KageError)
        assert issubclass(AudioError, KageError)
        assert issubclass(AvatarError, KageError)
        assert issubclass(ServerError, KageError)

        # Specialized child exceptions
        assert issubclass(ModelCallError, ModelError)
        assert issubclass(ModelLoadError, ModelError)
        assert issubclass(ProviderError, ModelError)
        assert issubclass(ToolNotFoundError, ToolExecutionError)
        assert issubclass(ToolArgumentError, ToolExecutionError)
        assert issubclass(SessionCorruptedError, SessionError)

    def test_raise_and_catch_typed_exceptions(self):
        with pytest.raises(SessionCorruptedError) as exc_info:
            raise SessionCorruptedError("Corrupted current.jsonl")
        assert isinstance(exc_info.value, SessionError)
        assert isinstance(exc_info.value, KageError)
