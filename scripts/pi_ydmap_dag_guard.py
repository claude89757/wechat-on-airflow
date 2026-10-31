"""Run inside the existing Airflow API container; preserve exactly two DAGs' pause state."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import signal
import sys
import time
from contextlib import contextmanager

DAG_IDS = ("大沙河国际网球中心巡检", "宝安网球中心巡检")
ACTIVE_TASK_STATES = (
    "running",
    "queued",
    "scheduled",
    "restarting",
    "up_for_retry",
    "up_for_reschedule",
)
HOLD_SECONDS = 1620
PROOF_MARGIN_SECONDS = 90


class DrainBusy(RuntimeError):
    pass


@contextmanager
def restore_without_interrupts():
    protected = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    # Block the set atomically while replacing its handlers. Otherwise a second
    # SSH disconnect/signal could interrupt the restoration retry's sleep.
    prior_mask = signal.pthread_sigmask(signal.SIG_BLOCK, protected)
    previous = {signum: signal.signal(signum, signal.SIG_IGN) for signum in protected}
    signal.pthread_sigmask(signal.SIG_SETMASK, prior_mask)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_BLOCK, protected)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        signal.pthread_sigmask(signal.SIG_SETMASK, prior_mask)


class AirflowBackend:
    def __init__(self):
        from airflow.models.dag import DagModel
        from airflow.models.dagrun import DagRun
        from airflow.models.taskinstance import TaskInstance
        from airflow.utils.session import create_session
        from sqlalchemy import func, select, text

        self.DagModel = DagModel
        self.DagRun = DagRun
        self.TaskInstance = TaskInstance
        self.session = create_session
        self.func = func
        self.select = select
        self.text = text
        self.original = {}

    @contextmanager
    def bounded_session(self):
        with self.session() as session:
            session.execute(self.text("SET LOCAL statement_timeout = '10000'"))
            session.execute(self.text("SET LOCAL lock_timeout = '5000'"))
            yield session

    def pause(self) -> dict[str, bool]:
        with self.bounded_session() as session:
            rows = list(
                session.scalars(
                    self.select(self.DagModel)
                    .where(self.DagModel.dag_id.in_(DAG_IDS))
                    .with_for_update()
                )
            )
            state = {row.dag_id: bool(row.is_paused) for row in rows}
            if DAG_IDS[0] not in state:
                raise RuntimeError("dashah_dag_not_found")
            tasks, runs = self._counts(session, state)
            if tasks or runs:
                # Pausing first would prevent scheduled/retrying tasks and
                # queued DagRuns from draining. Acquire a real idle window.
                raise DrainBusy("affected_dags_busy")
            self.original = state
            for row in rows:
                row.is_paused = True
        return state

    def _counts(self, session, state: dict[str, bool]) -> tuple[int, int]:
        tasks = session.scalar(
            self.select(self.func.count())
            .select_from(self.TaskInstance)
            .where(
                self.TaskInstance.dag_id.in_(state),
                self.TaskInstance.state.in_(ACTIVE_TASK_STATES),
            )
        )
        runs = session.scalar(
            self.select(self.func.count())
            .select_from(self.DagRun)
            .where(self.DagRun.dag_id.in_(state), self.DagRun.state.in_(("running", "queued")))
        )
        return int(tasks or 0), int(runs or 0)

    def counts(self, state: dict[str, bool]) -> tuple[int, int]:
        with self.bounded_session() as session:
            paused = dict(
                session.execute(
                    self.select(self.DagModel.dag_id, self.DagModel.is_paused).where(
                        self.DagModel.dag_id.in_(state)
                    )
                ).all()
            )
            if set(paused) != set(state) or not all(paused.values()):
                raise RuntimeError("pause_state_changed")
            return self._counts(session, state)

    def restore(self, state: dict[str, bool]) -> bool:
        with self.bounded_session() as session:
            rows = list(
                session.scalars(
                    self.select(self.DagModel)
                    .where(self.DagModel.dag_id.in_(state))
                    .with_for_update()
                )
            )
            if {row.dag_id for row in rows} != set(state):
                raise RuntimeError("guard_dag_disappeared")
            for row in rows:
                row.is_paused = state[row.dag_id]
        with self.bounded_session() as session:
            restored = dict(
                session.execute(
                    self.select(self.DagModel.dag_id, self.DagModel.is_paused).where(
                        self.DagModel.dag_id.in_(state)
                    )
                ).all()
            )
        return restored == state


def wait_release(timeout: int) -> str:
    deadline = time.monotonic() + timeout
    value = b""
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            if not selector.select(max(0, deadline - time.monotonic())):
                return "timeout"
            chunk = os.read(sys.stdin.fileno(), 128)
            if not chunk:
                return "eof"
            value += chunk
            if len(value) > 128:
                return "invalid"
            if b"\n" in value:
                return "release" if value == b"release\n" else "invalid"
    return "timeout"


def run_guard(
    backend,
    commit: str,
    guard_id: str,
    *,
    emit,
    release=wait_release,
    monotonic=time.monotonic,
    now=time.time,
    sleep=time.sleep,
    drain_timeout: int = 600,
    hold_timeout: int = HOLD_SECONDS,
) -> int:
    original = {}
    ok = False
    restored = False
    hold_deadline = None

    def safe_emit(payload):
        try:
            emit(payload)
        except (OSError, BrokenPipeError):
            # Losing the SSH output must not shorten an already issued lease.
            pass

    try:
        deadline = monotonic() + drain_timeout
        empty_cycles = 0
        while monotonic() < deadline:
            if not original:
                try:
                    original = backend.pause()
                except DrainBusy:
                    sleep(2)
                    continue
            tasks, runs = backend.counts(original)
            if tasks or runs:
                # A scheduler transaction may have raced the idle acquisition.
                # Restore the flags so it can finish, then retry within the
                # same bounded drain window. No proof has been issued yet.
                if not backend.restore(original):
                    raise RuntimeError("drain_retry_restore_failed")
                original = {}
                if hasattr(backend, "original"):
                    backend.original = {}
                empty_cycles = 0
                sleep(2)
                continue
            empty_cycles = empty_cycles + 1 if tasks == 0 and runs == 0 else 0
            if empty_cycles >= 2:
                break
            sleep(2)
        else:
            raise TimeoutError("dag_drain_timeout")
        hold_deadline = monotonic() + hold_timeout
        issued_at = int(now())
        proof = {
            "schema_version": 1,
            "guard_id": guard_id,
            "target_commit": commit,
            "drained": True,
            "active_tasks": 0,
            "active_runs": 0,
            "issued_at": issued_at,
            "expires_at": issued_at + hold_timeout - PROOF_MARGIN_SECONDS,
            "dags": [
                {"dag_id": dag, "was_paused": original[dag], "paused": True}
                for dag in DAG_IDS
                if dag in original
            ],
        }
        safe_emit({"event": "drained", "ok": True, "proof": proof})
        ok = release(hold_timeout) == "release"
    except Exception as exc:
        safe_emit({"event": "failed", "ok": False, "errorClass": type(exc).__name__})
    finally:
        with restore_without_interrupts():
            # Only an explicit acknowledgement that the Pi command has ended
            # can release early. EOF, signals, timeout and lost connectivity
            # retain the full fence, including between individual sleeps.
            while hold_deadline is not None and not ok and monotonic() < hold_deadline:
                sleep(min(5, max(0, hold_deadline - monotonic())))
            original = original or getattr(backend, "original", {})
            if original:
                restore_deadline = monotonic() + 60
                while monotonic() < restore_deadline:
                    try:
                        restored = backend.restore(original)
                        if restored:
                            break
                    except Exception:
                        pass
                    sleep(5)
            else:
                restored = True
            safe_emit(
                {
                    "event": "restored",
                    "ok": restored,
                    "restored": restored,
                    "dags": [
                        {"dag_id": dag, "paused": original[dag]}
                        for dag in DAG_IDS
                        if dag in original
                    ],
                }
            )
    return 0 if ok and restored else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--guard-id", required=True)
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise InterruptedError("guard_interrupted")

    for signal_number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signal_number, interrupted)
    if not re.fullmatch(r"[0-9a-f]{40}", args.target_commit) or not re.fullmatch(
        r"[0-9a-f]{32}", args.guard_id
    ):
        return 2
    if not re.fullmatch(r"[0-9a-f]{40}", os.environ.get("DEPLOYMENT_COMMIT", "")):
        print(
            json.dumps({"event": "failed", "ok": False, "errorClass": "UnversionedAirflowRuntime"}),
            flush=True,
        )
        return 2
    return run_guard(
        AirflowBackend(),
        args.target_commit,
        args.guard_id,
        emit=lambda payload: print(json.dumps(payload, ensure_ascii=False), flush=True),
    )


if __name__ == "__main__":
    raise SystemExit(main())
