# Task 1 report — managed browser experiment service

> Archived engineering history for C5.0. Final source: `e1e9fff`. Final full suite: **946 passed, 4 skipped, 1 xfailed, 1 existing pygame warning in 191.64s**, exit 0. Browser experiment notifications are **job events and Launcher panel only**; the earlier speech cancellation trial was reverted. Historical sections below retain the trials and intermediate test counts, not final capability claims. The actual model pilot and final conclusions are recorded separately in [C5.0 report](2026-10-04-browser-task-entry.md).

Implemented `BrowserTaskService` with a dedicated `BackgroundLane` and `BackgroundWorker`, serial execution, public job status derived from the independent task result, strict task/executor/payload validation, and indexed artifact lookup. `task_worker` receives the runtime configuration through stdin and executes the existing `EvolutionRunner` with inline steps inside a managed subprocess. The service enforces the 480-second deadline and stops the worker process group, including Chromium descendants. The external model service is outside that group.

Only `profile_dev`, `preferences_dev`, and `preferences_unchecked` are exposed. The unchecked task is the same preferences fixture without scoring criteria, and normal completion remains `unknown` even if the model says Done. `local_teacher` requires an independent checker. ModelBroker roles are explicitly set for each run with hybrid disabled, and the resolved modes are checked. Cloud requires a credential, a remote HTTPS OpenAI-compatible endpoint, and rejects all loopback IPs. Remote requests have the existing 12,000-byte wire and 1,024-output-token cap. No user settings file is changed.

The result includes the checker verdict, runner status, stop reason, executor/model identity, selected workflow bundle digest and unpromoted flag, per-call usage status, reservation, cost source, final text, and artifact hashes. Teacher selection and actual teacher use are separate fields. Missing or partial provider usage remains unknown/partial; cloud cost is unknown without configured rates. Request and raw response/error evidence is retained in JSONL with the credential redacted. Stopped and crashed runs retain files already written in the run directory. The public artifact method requires an indexed file in that run.

Red/green evidence:

- Initial end-to-end test failed during collection because `task_service` did not exist, then passed after implementation.
- The unchecked teacher guard failed with the cloud-credential error before the guard existed, then passed.
- Stopped-result regression failed because cancellation had no result payload, then passed.
- Remote request cap regression failed because `RecordedProvider` lacked the cap, then passed.
- Loopback regression failed because `127.0.0.2` was accepted, then passed.

The tests use only a scripted local HTTP model boundary; they launch a real separate Python worker, Chromium, and the controlled Page. They assert a real POST/readback, no POST for an unsaved model response, cancellation of queued work before model dispatch, termination of owned PIDs for a hung HTTP request, and the ability to run a following job. The original background worker completion/failure tests also pass, along with a new late-return cancellation test that verifies no completed event.

No actual local or cloud model was called. Live cloud behavior and configured price calculation were not exercised by this task's test gate; validation and request limits were tested without network calls to a cloud provider.

Final validation for code commit `0b78129` (no code changes after these checks):

- `.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py tests/test_background_worker.py -q` — exit 0, **11 passed in 8.41s**.
- `.venv-computer-use/bin/python -m py_compile core/computer_use/task_service.py core/computer_use/task_worker.py core/background_worker.py` — exit 0.
- `git diff --cached --check` — exit 0, no output, immediately before commit `0b78129`.

## Independent review fixes — code commit `4723aa4`

Resolved all five Important review items in one bounded round: startup task ownership is tracked until process creation settles and cancelled subprocesses are killed/reaped; a missing worker interpreter produces a structured failed result and `result.json`; provider `ModelResponse.error` is an execution failure with an unconfirmed checker verdict; local execution requires an explicit runtime host/port before queueing; and model responses, raised errors, tool arguments, and JSON-escaped credential echoes are redacted before entering the browser loop or context writers. Generated artifact URLs now use `/api/browser/tasks/{run_id}/artifacts/{name}` to match the approved Task 2 route.

Review regressions were first run against `bbae55b`: all four behavioral tests failed for the intended missing behavior, and the direct response-sanitization test failed because the returned `ModelResponse` still contained the synthetic credential. The JSON-escaped echo test likewise failed before its redaction fix. After changes, the final validation was:

- `.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py tests/test_background_worker.py -q` — exit 0, **16 passed in 11.48s**.
- `.venv-computer-use/bin/python -m py_compile core/computer_use/task_service.py core/computer_use/task_worker.py core/background_worker.py` — exit 0.
- `git diff --check` — exit 0, no output.
- `git diff --cached --check` — exit 0, no output, immediately before commit `4723aa4`.

The HTTP model in these tests was scripted, and the browser/worker/Page path was real. No actual local or cloud AI model or paid API was called. Live cloud billing remains outside this task's test gate.

## Re-review round 2 — code commit `0631c91`

The two new Important findings are resolved. Startup now consumes the same 480-second run deadline as execution; `stop()` waits at most one second for startup, and a process handle delivered later is killed and reaped by a registered cleanup callback. Cancellation of the background worker no longer waits indefinitely for startup. The final independent checker verdict now determines completion after recovery. Earlier provider errors remain in `model_errors`; a completed task has no current `error` or `model_error` stop reason. An unrecovered unchecked provider error remains failed with an unconfirmed checker verdict.

The new regressions first failed against `4723aa4`: a real HTTP-scripted model with a malformed first tool call still saved through a real worker and Page, but returned `check_passed=true` with `task_status=failed`; a delayed real subprocess made `stop()` exceed the test's three-second limit before the handle was released. Both passed after the fixes. A separate shortened-deadline test confirmed that startup times out before release, persists a failed result, and reaps the late child without model dispatch.

Final validation for `0631c91`:

- `.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py tests/test_background_worker.py -q` — exit 0, **19 passed in 14.43s**.
- `.venv-computer-use/bin/python -m py_compile core/computer_use/task_service.py core/computer_use/task_worker.py core/background_worker.py` — exit 0.
- `git diff --check` — exit 0, no output.
- `git diff --cached --check` — exit 0, no output, immediately before commit `0631c91`.

All provider calls in these tests used a scripted local HTTP boundary. No actual local AI model, cloud model, or paid API was called. Live cloud billing remains outside this gate.

## Re-review round 3 — source/test commit `a1f7838`

The remaining lifecycle gap is closed with a small worker bootstrap. It writes an atomic run-local PID/PGID ownership record before importing browser/model code or reading the private stdin request. Stop and timeout first write a run-local tombstone, then terminate the recorded process group even when `create_subprocess_exec` has spawned the child but has not delivered its handle. The worker checks the tombstone before import and again after reading stdin, so a child created only after stop exits before dispatch. Late handle delivery is still reaped. No credential appears in process arguments or the ownership record.

Red/green evidence against the prior `0631c91` implementation:

- `.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py -q -k 'stop_and_close_return_before_delayed_spawn or startup_consumes_overall_deadline'` — exit 1, **2 failed, 14 deselected in 2.21s**; both failed because `os.kill(pid, 0)` still found the worker before the spawn handle was released.
- `.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py -q -k 'stop_before_spawn'` — exit 1, **1 failed, 16 deselected in 1.68s**; the stop tombstone was absent.
- `.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py -q -k 'stop_and_close_return_before_delayed_spawn or startup_consumes_overall_deadline or stop_before_spawn'` — exit 0, **3 passed, 14 deselected in 5.72s** after the bootstrap and cancellation changes.

Final scoped validation after the last source edit:

- `.venv-computer-use/bin/python -m pytest tests/test_browser_task_service.py tests/test_background_worker.py -q` — exit 0, **20 passed in 17.92s**.
- `.venv-computer-use/bin/python -m py_compile core/computer_use/task_service.py core/computer_use/task_worker.py core/computer_use/task_bootstrap.py core/background_worker.py` — exit 0.
- `git diff --check` — exit 0, no output.
- `git diff --cached --check` — exit 0, no output, immediately before source/test commit `a1f7838`.

Tests still use only scripted local HTTP model responses. No actual local or cloud AI model or paid API was called. The OS-level ownership record depends on the bootstrap running to publish its PID; if a newly spawned process is prevented from executing at all past the bounded stop interval, the tombstone blocks work once it runs and late handle delivery remains reaped.
