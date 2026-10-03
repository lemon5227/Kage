# Task 1 report — managed browser experiment service

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
