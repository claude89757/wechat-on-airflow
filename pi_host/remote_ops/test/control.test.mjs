import { test } from "node:test";
import assert from "node:assert/strict";
import { Operations, executeCommand, redact } from "../control.mjs";

function fixture(execute = async () => ({ exitCode: 0, output: "isolated" })) {
  const events = [], executions = [];
  let now = 1000;
  const store = new Operations({ now: () => now, audit: event => events.push(event), execute: async (...args) => {
    executions.push(args); return execute(...args);
  }});
  return { store, events, executions, advance: ms => { now += ms; } };
}
test("a command runs immediately, exactly once, and only its owner can read it", async () => {
  const { store, executions } = fixture();
  const item = store.start("alice", "printf isolated", "test", 1);
  await item.done;
  assert.equal(executions.length, 1);
  assert.equal(store.get(item.id, "alice").state, "finished");
  assert.equal(store.get(item.id, "alice").result.output, "isolated");
  assert.throws(() => store.get(item.id, "bob"));
});
test("the audit log records who ran what, with credentials redacted", async () => {
  const { store, events } = fixture();
  await store.start("alice", "login password=example", "why token=abc", 5).done;
  const started = events.find(event => event.event === "started");
  assert.equal(started.principal, "alice");
  assert.equal(started.command, "login password=[redacted]");
  assert.equal(started.reason, "why token=[redacted]");
  assert.ok(events.some(event => event.event === "finished" && event.exitCode === 0));
});
test("audit failure prevents execution", () => {
  const { store, executions } = fixture();
  store.audit = () => { throw Error("disk full"); };
  assert.throws(() => store.start("alice", "x", "", 1));
  assert.equal(executions.length, 0);
});
test("audit failure after the command does not hide its result", async () => {
  const { store } = fixture();
  const item = store.start("alice", "x", "", 1);
  store.audit = () => { throw Error("disk full"); };
  await item.done;
  assert.equal(item.state, "finished");
});
test("an interrupted command becomes unknown and is not replayed", async () => {
  const { store, executions } = fixture(async () => { throw Error("uncertain"); });
  const item = store.start("alice", "x", "", 1);
  await item.done;
  assert.equal(item.state, "unknown");
  assert.equal(executions.length, 1);
});
test("results expire, but a running command does not", async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const { store, advance } = fixture(async () => { await gate; return { exitCode: 0, output: "" }; });
  const item = store.start("alice", "x", "", 1);
  advance(3600000);
  store.sweep();
  assert.equal(store.get(item.id, "alice").state, "running");
  release(); await item.done;
  assert.equal(store.get(item.id, "alice").state, "finished");
  advance(900001);
  assert.throws(() => store.get(item.id, "alice"));
});
test("parallel commands are allowed up to a bound", async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const { store } = fixture(async () => { await gate; return { exitCode: 0, output: "" }; });
  store.maxRunning = 2;
  const first = store.start("alice", "a", "", 1), second = store.start("bob", "b", "", 1);
  assert.throws(() => store.start("alice", "c", "", 1), /host_operation_busy/);
  release(); await Promise.all([first.done, second.done]);
  assert.equal(store.running(), 0);
});
test("restarts discard results and do not replay", () => {
  const { store } = fixture();
  const item = store.start("alice", "x", "", 1);
  const fresh = new Operations({ audit: () => {}, execute: () => assert.fail("must not run") });
  assert.throws(() => fresh.get(item.id, "alice"));
});
test("obvious credentials and identities are redacted", () => {
  const result = redact("password=example secret: abc user@example.com eyJabc.def.ghi");
  assert.ok(!result.includes("example"));
  assert.ok(!result.includes("abc"));
});
test("command has bounded timeout and scrubbed environment", async () => {
  process.env.REMOTE_OPS_TEST_SECRET = "never-forward";
  const result = await executeCommand("printf '%s' \"${REMOTE_OPS_TEST_SECRET-unset}\"", 1);
  assert.equal(result.output, "unset");
  const timeout = await executeCommand("sleep 10", 1);
  assert.equal(timeout.timedOut, true);
});
test("long output keeps its end, where failures are reported", async () => {
  const result = await executeCommand("head -c 400000 /dev/zero | tr '\\0' x; echo; echo FAILED-HERE", 10);
  assert.equal(result.truncated, true);
  assert.ok(result.output.endsWith("FAILED-HERE\n"));
  assert.ok(result.output.length <= 262144);
});
