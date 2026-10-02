"""The background job pipeline.

One job, four stages, with the kill switch checked at every boundary:

1. ``pre``      — kill check, build the backend (the "model" proposes).
2. ``run``      — the lab-02 agent runs under a request timeout.
3. ``validate`` — kill check; the agent already validated the brief
                  deterministically (lab-02's post-validator), so this stage
                  just refuses to publish after a kill.
4. ``publish``  — persist the terminal outcome; add actual tokens to spend.

In-flight abort: a slow backend is expected to watch the kill event itself
(the test slow policy does), but even one that doesn't is caught at the next
boundary — nothing ships after the kill.

Timeouts: the agent runs on a child thread; the worker joins with the
configured timeout. On expiry the job fails with a timeout error and the
abandoned thread's eventual result is discarded (``finish_job`` only
transitions out of ``running``).
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from lab02.agent import Agent, AgentConfig, RunResult
from lab02.models import ModelBackend
from lab02.tools import build_registry

from .limits import JobAborted, JobKilled, JobTimeout

if TYPE_CHECKING:  # the App type; avoid an import cycle
    from .server import App


def default_registry_factory(packet):  # type: ignore[no-untyped-def]
    return build_registry(packet)


class Pipeline:
    def __init__(self, app: "App"):
        self.app = app

    # ------------------------------------------------------------ entry ---

    def run_job(self, job_id: str) -> None:
        """Run one job to a terminal state. Called on a worker thread."""
        app = self.app
        job = app.store.get_job(job_id)
        if job is None:
            return
        try:
            self._kill_check()                                   # stage: pre
            backend = app.policy_factory(app.ctx)
            app.executions += 1  # the counter the idempotency test watches
            result = self._run_agent(job["question"], backend)   # stage: run
            self._kill_check()                                   # stage: validate
            self._publish(job_id, result)                        # stage: publish
        except JobAborted:
            # Server stopping: leave the record untouched; a restart requeues it.
            app.logger.log("job_abandoned", job_id=job_id)
            return
        except JobKilled:
            self._fail_quietly(job_id, "aborted: kill switch engaged")
        except JobTimeout as e:
            self._fail_quietly(job_id, f"timeout: {e}")
        except Exception as e:  # model outage, tool outage, anything else
            self._fail_quietly(job_id, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------ stages ---

    def _kill_check(self) -> None:
        if self.app.kill_event.is_set():
            raise JobKilled("kill switch engaged")

    def _run_agent(self, question: str, backend: ModelBackend) -> RunResult:
        registry = self.app.registry_factory(self.app.packet)
        agent = Agent(backend, registry, self.app.packet, AgentConfig())
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["result"] = agent.run(question)
            except Exception as e:  # re-raised on the worker thread below
                box["error"] = e

        child = threading.Thread(target=target, daemon=True,
                                 name=f"lab11-run-{id(box)}")
        child.start()
        child.join(self.app.config.request_timeout_s)
        if child.is_alive():
            raise JobTimeout(
                f"request exceeded {self.app.config.request_timeout_s}s")
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _publish(self, job_id: str, result: RunResult) -> None:
        app = self.app
        if app.stopped.is_set():
            return
        if result.status == "completed" and result.brief is not None:
            brief = result.brief.model_dump()
            app.store.add_spend(result.total_tokens)
            ok = app.store.finish_job(job_id, "completed", brief=brief,
                                      tokens_used=result.total_tokens)
            if ok:
                app.logger.log("job_completed", job_id=job_id,
                               tokens=result.total_tokens)
        elif result.status == "declined" and result.decline is not None:
            # A decline is a valid terminal answer, not a failure.
            app.store.add_spend(result.total_tokens)
            ok = app.store.finish_job(job_id, "completed",
                                      declined=result.decline.model_dump(),
                                      tokens_used=result.total_tokens)
            if ok:
                app.logger.log("job_completed", job_id=job_id,
                               outcome="declined", tokens=result.total_tokens)
        else:
            self._fail_quietly(job_id, result.error or "unknown agent error",
                               tokens=result.total_tokens)

    def _fail_quietly(self, job_id: str, error: str, tokens: int = 0) -> None:
        app = self.app
        if app.stopped.is_set():
            return
        if tokens:
            app.store.add_spend(tokens)
        # finish_job refuses to clobber a job that already left "running"
        # (e.g. a timeout already failed it while the abandoned thread later
        # returns) — no partial result is ever published over a final one.
        ok = app.store.finish_job(job_id, "failed", error=error,
                                  tokens_used=tokens)
        if ok:
            app.logger.log("job_failed", job_id=job_id, error=error)
