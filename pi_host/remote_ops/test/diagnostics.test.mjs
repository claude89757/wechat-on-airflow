import { test } from "node:test";
import assert from "node:assert/strict";
import { diagnose } from "../diagnostics.mjs";

test("diagnostics expose only allowlisted states, never raw output or secrets", async () => {
  const calls = [];
  const report = await diagnose("vps", async (command, args, options) => {
    calls.push({ command, args });
    assert.ok(options.timeout <= 3000);
    assert.equal(options.shell, undefined);
    if (command === "systemctl") return { stdout: "LoadState=loaded\nActiveState=active\nNRestarts=0\nSECRET=never-return\n" };
    return { stdout: JSON.stringify({ Labels: "com.docker.compose.service=zacks-api,secret=never-return", State: "running", Status: "Up 1 minute (healthy)", Secret: "never-return" }) + "\n" + JSON.stringify({ Labels: "com.docker.compose.service=private", State: "running" }) };
  });
  assert.equal(report.readOnly, true);
  assert.deepEqual(report.containers, [{ service: "zacks-api", state: "running", health: "healthy" }]);
  assert.equal(JSON.stringify(report).includes("never-return"), false);
  assert.equal(JSON.stringify(report).includes("private"), false);
  assert.ok(calls.every(x => ["systemctl", "docker"].includes(x.command)));
});
test("failed diagnostic probes are unavailable, not successful", async () => {
  const report = await diagnose("pi", async () => { throw Error("secret-error"); });
  assert.ok(report.units.every(x => x.state === "unavailable"));
  assert.equal(report.containers, null);
  assert.equal(JSON.stringify(report).includes("secret-error"), false);
  await assert.rejects(diagnose("untrusted", () => assert.fail("must not execute")));
});
