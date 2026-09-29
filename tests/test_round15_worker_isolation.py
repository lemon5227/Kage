"""
Round 15 Unit Tests - TASK-4: Concurrency Context Isolation
Verifies BackgroundWorker execution context isolation from foreground AgenticLoop,
thread-safe _pending_facts synchronization, and session isolation.
"""

import asyncio
from unittest.mock import MagicMock
from core.agentic_loop import AgenticLoop
from core.background_lane import BackgroundLane
from core.background_worker import BackgroundWorker
from core.session_state import SessionState


class TestAgenticLoopIsolation:
    def test_create_isolated_runner_has_independent_state(self):
        parent_session = SessionState()
        parent_session.add_turn("user", "parent message")

        parent_loop = AgenticLoop(
            model_provider=MagicMock(),
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
            session_manager=parent_session,
        )
        parent_loop._pending_facts.append({"content": "parent fact"})

        isolated_loop = parent_loop.create_isolated_runner()

        # Isolated runner has its own empty pending facts and empty session
        assert len(isolated_loop._pending_facts) == 0
        assert len(isolated_loop.session.as_history_list()) == 0

        # Mutating isolated runner does not pollute parent
        isolated_loop._pending_facts.append({"content": "isolated fact"})
        isolated_loop.session.add_turn("user", "isolated message")

        assert len(parent_loop._pending_facts) == 1
        assert parent_loop._pending_facts[0]["content"] == "parent fact"
        assert len(parent_session.as_history_list()) == 1
        assert parent_session.as_history_list()[0]["content"] == "parent message"

    def test_pending_facts_lock_thread_safety(self):
        loop = AgenticLoop(
            model_provider=MagicMock(),
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
            session_manager=SessionState(),
            memory_system=MagicMock(),
        )

        async def _test():
            # Concurrently append facts from multiple tasks
            async def _append_batch(n):
                for i in range(10):
                    with loop._pending_facts_lock:
                        loop._pending_facts.append({"content": f"fact-{n}-{i}"})
                    await asyncio.sleep(0.001)

            await asyncio.gather(*[_append_batch(j) for j in range(5)])
            assert len(loop._pending_facts) == 50

            # Flush clears under lock cleanly
            loop.flush_pending_facts()
            assert len(loop._pending_facts) == 0

        asyncio.run(_test())


class TestBackgroundWorkerContextIsolation:
    def test_worker_uses_context_factory(self):
        lane = BackgroundLane()
        lane.submit(
            task_type="deep_search",
            input_text="search query",
        )

        created_contexts = []

        def context_factory():
            ctx = {"id": len(created_contexts) + 1, "runner": MagicMock()}
            created_contexts.append(ctx)
            return ctx

        processed_contexts = []

        async def dummy_processor(job, context=None):
            processed_contexts.append(context)
            return {"status": "ok"}

        worker = BackgroundWorker(
            lane=lane,
            processor=dummy_processor,
            context_factory=context_factory,
        )

        done = asyncio.run(worker.process_next())
        assert done is True
        assert len(created_contexts) == 1
        assert len(processed_contexts) == 1
        assert processed_contexts[0] is created_contexts[0]

    def test_worker_failure_does_not_corrupt_foreground_state(self):
        lane = BackgroundLane()
        lane.submit(
            task_type="error_job",
            input_text="will fail",
        )

        foreground_session = SessionState()
        foreground_session.add_turn("user", "foreground hello")

        async def failing_processor(job, context=None):
            raise RuntimeError("Task crashed")

        worker = BackgroundWorker(
            lane=lane,
            processor=failing_processor,
        )

        done = asyncio.run(worker.process_next())
        assert done is True
        assert len(foreground_session.as_history_list()) == 1
        assert foreground_session.as_history_list()[0]["content"] == "foreground hello"
