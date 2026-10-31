import { test } from "node:test";
import assert from "node:assert/strict";
import { Requests, escapeHtml, executeCommand, redact } from "../control.mjs";

function fixture() {
  const events = [], executions = [];
  let now = 1000;
  const store = new Requests({ now: () => now, audit: event => events.push(event), execute: async (...args) => {
    executions.push(args); return { exitCode: 0, output: "isolated" };
  }});
  const item = store.create("alice", "printf isolated", "test", 1);
  return { store, item, events, executions, expire: () => { now += 300001; } };
}
test("request does not execute; another identity cannot inspect or approve", () => {
  const { store, item, executions } = fixture();
  assert.equal(executions.length, 0);
  assert.throws(() => store.get(item.id, "bob"));
  assert.throws(() => store.challenge(item.id, "bob"));
  assert.throws(() => store.approve(item.id, "bob", "x", "x"));
});
test("approval requires matching unpredictable browser challenge and cookie", () => {
  const { store, item } = fixture();
  const { nonce } = store.challenge(item.id, "alice");
  assert.throws(() => store.approve(item.id, "alice", nonce, "different"));
  assert.throws(() => store.approve(item.id, "alice", "a".repeat(64), "a".repeat(64)));
  assert.equal(store.get(item.id, "alice").state, "pending");
});
test("one approval executes exactly once and records no raw command", async () => {
  const { store, item, events, executions } = fixture();
  const { nonce } = store.challenge(item.id, "alice");
  store.approve(item.id, "alice", nonce, nonce);
  assert.throws(() => store.approve(item.id, "alice", nonce, nonce));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(executions.length, 1);
  assert.equal(item.state, "finished");
  assert.ok(!JSON.stringify(events).includes("printf isolated"));
});
test("expired requests cannot be approved or read", () => {
  const { store, item, expire } = fixture();
  const { nonce } = store.challenge(item.id, "alice"); expire();
  assert.throws(() => store.approve(item.id, "alice", nonce, nonce));
  assert.throws(() => store.get(item.id, "alice"));
});
test("a second confirmation page invalidates the first nonce", () => {
  const { store, item } = fixture();
  const first = store.challenge(item.id, "alice");
  store.challenge(item.id, "alice");
  assert.throws(() => store.approve(item.id, "alice", first.nonce, first.nonce));
});
test("restarts invalidate pending requests and do not replay", () => {
  const { item } = fixture();
  const fresh = new Requests({ audit: () => {}, execute: () => assert.fail("must not run") });
  assert.throws(() => fresh.get(item.id, "alice"));
});
test("audit failure prevents execution", () => {
  const { store, item, executions } = fixture();
  const { nonce } = store.challenge(item.id, "alice");
  store.audit = () => { throw Error("disk full"); };
  assert.throws(() => store.approve(item.id, "alice", nonce, nonce));
  assert.equal(executions.length, 0);
});
test("unknown execution is not retryable with same approval", async () => {
  const { store, item } = fixture();
  store.execute = async () => { throw Error("uncertain"); };
  const { nonce } = store.challenge(item.id, "alice");
  store.approve(item.id, "alice", nonce, nonce);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(item.state, "unknown");
  assert.throws(() => store.approve(item.id, "alice", nonce, nonce));
});
test("pending request count is bounded", () => {
  const { store } = fixture(); store.maximum = 1;
  assert.throws(() => store.create("bob", "x", "x", 1));
});
test("confirmation HTML cannot execute commands as markup", () => {
  assert.equal(escapeHtml('<script>"x" & \'</script>'), "&lt;script&gt;&quot;x&quot; &amp; &#39;&lt;/script&gt;");
});
test("obvious credentials and identities are redacted", () => {
  const result = redact("password=example secret: abc user@example.com eyJabc.def.ghi");
  assert.ok(!result.includes("example"));
  assert.ok(!result.includes("abc"));
});
test("isolated command has bounded timeout and scrubbed environment", async () => {
  process.env.REMOTE_OPS_TEST_SECRET = "never-forward";
  const result = await executeCommand("printf '%s' \"${REMOTE_OPS_TEST_SECRET-unset}\"", 1);
  assert.equal(result.output, "unset");
  const timeout = await executeCommand("sleep 10", 1);
  assert.equal(timeout.timedOut, true);
});
