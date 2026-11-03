import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { DeviceGuard, acquireDeviceLock, error, result } from "../guard.mjs";

function fixture() {
  let now = 1000;
  const entries = new Map();
  const locks = new Set();
  const devices = [1, 2].map(n => ({ alias: `phone_${n}`, serial: `fake-${n}`,
    appiumUrl: `http://127.0.0.1:600${n}`, systemPort: 8199 + n }));
  let count = 0;
  let deleteFails = false;
  const guard = new DeviceGuard({ devices, sessions: () => [...entries.values()], clock: () => now,
    inspectRemote: async device => [...entries.values()].filter(e => e.capabilities["appium:udid"] === device.serial).map(e => e.sessionId),
    acquire: async serial => {
      if (locks.has(serial)) return null;
      locks.add(serial);
      return { alive: () => locks.has(serial), release: async () => locks.delete(serial) };
    },
    invokeSession: async args => {
      if (args.action === "create") {
        const caps = JSON.parse(args.capabilities);
        assert.equal(caps["appium:noReset"], true);
        assert.equal(caps["appium:fullReset"], false);
        assert.equal(caps["appium:autoLaunch"], false);
        assert.equal(caps["appium:autoGrantPermissions"], false);
        const id = `session-${++count}`;
        entries.set(id, { sessionId: id, capabilities: caps });
        return result({ sessionId: id });
      }
      if (deleteFails) return error("cleanup_failed");
      entries.delete(args.sessionId);
      return result({ success: true });
    },
  });
  return { guard, locks, entries, tick: ms => now += ms, failDelete: () => deleteFails = true };
}
const read = response => JSON.parse(response.content[0].text);

test("two phones have independent leases and mandatory session IDs", async () => {
  const { guard, locks } = fixture();
  const a = read(await guard.manage({ action: "create", device: "phone_1" }, {}));
  const b = read(await guard.manage({ action: "create", device: "phone_2" }, {}));
  assert.equal(locks.size, 2);
  assert.notEqual(a.sessionId, b.sessionId);
  assert.equal((await guard.execute({}, () => assert.fail(), {})).isError, true);
  assert.equal((await guard.execute({ sessionId: "foreign" }, () => assert.fail(), {})).isError, true);
  assert.equal((await guard.manage({ action: "create", device: "phone_1" }, {})).isError, true);
  assert.equal((await guard.manage({ action: "attach", sessionId: a.sessionId }, {})).isError, true);
  await guard.shutdown();
  assert.equal(locks.size, 0);
});

test("in-flight calls hold the phone; another phone can run and throwing calls release accounting", async () => {
  const { guard, tick, locks } = fixture();
  const a = read(await guard.manage({ action: "create", device: "phone_1" }, {}));
  const b = read(await guard.manage({ action: "create", device: "phone_2" }, {}));
  let finish;
  const running = guard.execute({ sessionId: a.sessionId }, () => new Promise(resolve => finish = resolve), {});
  assert.equal((await guard.execute({ sessionId: a.sessionId }, () => assert.fail(), {})).isError, true);
  assert.equal(read(await guard.execute({ sessionId: b.sessionId }, () => result("other-phone"), {})), "other-phone");
  tick(31000);
  await guard.sweep();
  assert.equal(locks.size, 1);
  finish(result("complete"));
  await running;
  await assert.rejects(guard.execute({ sessionId: a.sessionId }, () => { throw new Error("fake failure"); }, {}));
  assert.equal((await guard.execute({ sessionId: a.sessionId }, () => result(true), {})).isError, false);
  await guard.shutdown();
});

test("idle cleanup retains the lock until the actual session has gone", async () => {
  const { guard, locks, tick, failDelete } = fixture();
  await guard.manage({ action: "create", device: "phone_1" }, {});
  failDelete();
  tick(31000);
  await guard.sweep();
  assert.equal(locks.size, 1);
  assert.equal(guard.owned.size, 1);
});

test("expired leases cannot keep issuing actions", async () => {
  const { guard, tick, locks } = fixture();
  const a = read(await guard.manage({ action: "create", device: "phone_1" }, {}));
  tick(120000);
  assert.equal((await guard.execute({ sessionId: a.sessionId }, () => assert.fail(), {})).isError, true);
  await guard.sweep();
  assert.equal(locks.size, 0);
});

test("real subprocess flock interoperates across independent holders", async () => {
  const directory = await mkdtemp(join(tmpdir(), "pi-mcp-test-"));
  let first;
  let second;
  try {
    first = await acquireDeviceLock("fake-phone", directory);
    assert.ok(first?.alive());
    assert.equal(await acquireDeviceLock("fake-phone", directory), null);
    await first.release();
    second = await acquireDeviceLock("fake-phone", directory);
    assert.ok(second?.alive());
  } finally {
    await first?.release();
    await second?.release();
    await rm(directory, { recursive: true, force: true });
  }
});

test("a foreign Appium session is never overridden even if no cooperative lock is held", async () => {
  const { guard, locks } = fixture();
  guard.inspectRemote = async () => ["foreign-session"];
  guard.invokeSession = () => assert.fail("must not create or delete a foreign session");
  assert.equal((await guard.manage({ action: "create", device: "phone_1" }, {})).content[0].text, "foreign_session_busy");
  assert.equal(locks.size, 0);
});

test("ambiguous creation retains the phone and fences future tools", async () => {
  const { guard, locks } = fixture();
  let queries = 0;
  guard.inspectRemote = async () => queries++ ? ["unregistered-session"] : [];
  guard.invokeSession = async () => error("upstream failed after remote creation");
  const response = await guard.manage({ action: "create", device: "phone_1" }, {});
  assert.equal(response.content[0].text, "session_creation_unknown_recovery_required");
  assert.equal(locks.size, 1);
  assert.equal(guard.closing, true);
  assert.equal((await guard.manage({ action: "create", device: "phone_2" }, {})).isError, true);
});

test("failed creation is ambiguous even while the remote session list is empty", async () => {
  const failed = fixture();
  failed.guard.invokeSession = async () => error("definitive rejection");
  assert.equal((await failed.guard.manage({ action: "create", device: "phone_1" }, {})).content[0].text, "session_creation_unknown_recovery_required");
  assert.equal(failed.locks.size, 1);
  assert.equal(failed.guard.closing, true);
});

test("already-expired remote sessions release cleanly", async () => {
  const expired = fixture();
  const session = read(await expired.guard.manage({ action: "create", device: "phone_1" }, {}));
  expired.entries.clear();
  assert.equal((await expired.guard.close(session.sessionId, {})).isError, false);
  assert.equal(expired.locks.size, 0);
});

test("session listing includes creates still awaiting Appium, so deployment cannot mistake them for idle", async () => {
  const { guard } = fixture();
  const original = guard.invokeSession;
  let finish;
  guard.invokeSession = async args => {
    if (args.action === "create") await new Promise(resolve => finish = resolve);
    return original(args);
  };
  const pending = guard.manage({ action: "create", device: "phone_1" }, {});
  while (!finish) await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(read(await guard.manage({ action: "list" }, {})), [
    { device: "phone_1", busy: true, creating: true },
  ]);
  finish();
  await pending;
  await guard.shutdown();
});
