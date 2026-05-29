"""
Speech Engine — TTS playback, expression sync, motion, and voice barge-in.

Extracted from KageServer to reduce the god-class burden.
This module handles:
- mouth_speak: TTS request → expression → motion → audio playback
- _send_random_motion: select and send motion based on emotion
- _monitor_voice_barge_in: detect voice interruption during playback
- _sanitize_for_speech: clean text for TTS
"""

import asyncio
import contextlib
import logging
import random

from core.response_sanitizer import sanitize_for_speech_text

logger = logging.getLogger(__name__)


async def mouth_speak(
    kage_server,
    text: str,
    emotion: str = "neutral",
) -> None:
    """Speak and allow Frontend to sync lips and expression.

    Args:
        kage_server: The KageServer instance (needed for send_message, mouth, etc.)
        text: Text to speak.
        emotion: Emotion tag for expression/motion.
    """
    text = sanitize_for_speech_text(text)
    if not text:
        return
    kage_server._speech_revision += 1
    speech_revision = kage_server._speech_revision

    # Text-only benchmark mode: skip TTS playback and only emit speech message.
    if kage_server._text_only_mode or kage_server.mouth is None:
        await kage_server.send_message("speech", {"text": text, "emotion": emotion})
        if speech_revision == kage_server._speech_revision:
            await kage_server.send_state("IDLE")
        return

    try:
        logger.info("TTS request (%s): %s", emotion, text)
    except Exception:
        pass

    kage_server.avatar_animation.update_motion_cooldown(text)
    await _send_random_motion(kage_server, emotion)

    # 1. Send Expression (Emotion)
    exp_name = kage_server.avatar_animation.select_expression(emotion)
    await kage_server.send_message("expression", {
        "name": exp_name,
        "duration": kage_server.avatar_animation.calculate_expression_duration(text),
    })

    # 2. Send text to frontend (for speech bubble) with emotion field
    await kage_server.send_message("speech", {"text": text, "emotion": emotion})

    # 3. Audio Generation (Generating... not speaking yet)
    audio_path = await kage_server.mouth.generate_speech_file(text, emotion)
    if speech_revision != kage_server._speech_revision:
        return

    if audio_path:
        try:
            logger.info("Playing audio: %s", audio_path)
        except Exception:
            pass
        # 4. Now we are ready to play. Signal Frontend!
        await kage_server.send_state("SPEAKING")
        barge_task = None
        if kage_server.audio_orchestrator.should_enable_voice_barge_in(
            text_only_mode=kage_server._text_only_mode,
            ears=kage_server.ears,
        ):
            barge_task = asyncio.create_task(
                _monitor_voice_barge_in(kage_server, speech_revision)
            )
        # Blocking Playback
        try:
            await asyncio.to_thread(kage_server.mouth.play_audio_file, audio_path)
        finally:
            if barge_task is not None:
                barge_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await barge_task
        # Done
        if speech_revision == kage_server._speech_revision:
            await kage_server.send_state("IDLE")
    else:
        try:
            logger.warning("TTS generation failed (no audio_path)")
        except Exception:
            pass
        if speech_revision == kage_server._speech_revision:
            await kage_server.send_state("IDLE")


async def _send_random_motion(kage_server, emotion: str | None = None) -> None:
    """Send a random motion based on emotion."""
    emotion_key = emotion or ""
    motion_idx = kage_server.avatar_animation.select_motion(emotion_key)
    if motion_idx is None:
        return
    # Determine group from weights
    weights_map = kage_server.avatar_animation.expression.emotion_weights.get(
        emotion_key, kage_server.avatar_animation.motion.weights
    )
    groups = list(weights_map.keys())
    weights = list(weights_map.values())
    group = random.choices(groups, weights=weights, k=1)[0]
    await kage_server.send_message("motion", {"group": group, "index": motion_idx})


async def _monitor_voice_barge_in(kage_server, speech_revision: int) -> None:
    """Monitor voice input during playback for barge-in."""
    if kage_server.ears is None:
        return
    try:
        while speech_revision == kage_server._speech_revision:
            await asyncio.sleep(0.1)
            # Check if new voice input detected
            if kage_server.audio_orchestrator.check_voice_barge_in():
                logger.info("Voice barge-in detected, stopping playback")
                kage_server._speech_revision += 1
                break
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("Voice barge-in monitor error: %s", exc)
