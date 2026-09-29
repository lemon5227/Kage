"""Tests for Round 14 ISSUE-6: Audio temporary file isolation and audioop compatibility."""

import os
import struct
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from core.mouth import KageMouth
from core.ears import _AudioOpFallback


class TestMouthAudioIsolation:
    @pytest.mark.anyio
    async def test_generate_speech_file_produces_unique_paths(self):
        with patch("pygame.mixer.init"):
            mouth = KageMouth()
            with patch("edge_tts.Communicate") as mock_comm:
                mock_instance = AsyncMock()
                mock_comm.return_value = mock_instance
                
                path1 = await mouth.generate_speech_file("第一句语音")
                path2 = await mouth.generate_speech_file("第二句语音")
                
                assert path1 is not None
                assert path2 is not None
                assert path1 != path2
                assert path1 in mouth._active_temp_files
                assert path2 in mouth._active_temp_files
                
                # Cleanup
                mouth.cleanup_temp_files()
                assert len(mouth._active_temp_files) == 0

    def test_play_audio_file_unlinks_on_completion(self):
        with patch("pygame.mixer.init"), \
             patch("pygame.mixer.music.load"), \
             patch("pygame.mixer.music.play"), \
             patch("pygame.mixer.music.get_busy", side_effect=[True, False]), \
             patch("pygame.mixer.music.unload"):
            
            mouth = KageMouth()
            # Create a real temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(b"fake audio data")
                temp_path = f.name
                
            mouth._active_temp_files.add(temp_path)
            assert os.path.exists(temp_path)
            
            mouth.play_audio_file(temp_path)
            
            # Should have deleted the file
            assert not os.path.exists(temp_path)
            assert temp_path not in mouth._active_temp_files


class TestAudioopFallbackRMS:
    def test_rms_calculation_exactness(self):
        # Generate 100 samples of 16-bit PCM (signed 16-bit)
        # E.g., alternating between 1000 and -1000 -> RMS should be 1000
        samples = [1000, -1000] * 50
        pcm_bytes = struct.pack(f"<{len(samples)}h", *samples)
        
        rms = _AudioOpFallback.rms(pcm_bytes, 2)
        assert rms == 1000

    def test_rms_empty_or_invalid(self):
        assert _AudioOpFallback.rms(b"", 2) == 0
        assert _AudioOpFallback.rms(b"123", 1) == 0
