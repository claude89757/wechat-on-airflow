import { describe, expect, it } from "vitest";

import { hostSecretEnvelope } from "./host-migration-export";

function encode(value: ArrayBuffer): string {
  let binary = "";
  for (const byte of new Uint8Array(value)) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function decode(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/")
    + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function migrationEnv() {
  return {
    AIRFLOW_PUSH_TOKEN: "migration-token",
    TENCENT_SECRET_ID: "secret-id",
    TENCENT_SECRET_KEY: "secret-key",
    TENCENT_REGION: "ap-guangzhou",
    EMAIL_FROM_ADDRESS: "sender@example.com",
    EMAIL_REPLY_TO: "reply@example.com",
    EMAIL_TEMPLATE_ID: "12345",
  };
}

describe("host secret migration envelope", () => {
  it("requires the migration bearer token", async () => {
    const response = await hostSecretEnvelope(
      new Request("https://example.com/api/internal/host-secret-envelope", {
        method: "POST",
        body: JSON.stringify({ publicKeySpki: "invalid" }),
      }),
      migrationEnv() as never,
    );

    expect(response.status).toBe(401);
  });

  it("transfers the mail configuration only inside an authenticated envelope", async () => {
    const pair = await crypto.subtle.generateKey(
      {
        name: "RSA-OAEP",
        modulusLength: 2048,
        publicExponent: new Uint8Array([1, 0, 1]),
        hash: "SHA-256",
      },
      true,
      ["encrypt", "decrypt"],
    ) as CryptoKeyPair;
    const spki = await crypto.subtle.exportKey("spki", pair.publicKey);
    const response = await hostSecretEnvelope(
      new Request("https://example.com/api/internal/host-secret-envelope", {
        method: "POST",
        headers: {
          Authorization: "Bearer migration-token",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ publicKeySpki: encode(spki) }),
      }),
      migrationEnv() as never,
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    const envelope = await response.json<{
      algorithm: string;
      encryptedKey: string;
      iv: string;
      ciphertext: string;
    }>();
    expect(envelope.algorithm).toBe("RSA-OAEP-256+A256GCM");

    const rawKey = await crypto.subtle.decrypt(
      { name: "RSA-OAEP" },
      pair.privateKey,
      decode(envelope.encryptedKey),
    );
    const aesKey = await crypto.subtle.importKey(
      "raw",
      rawKey,
      { name: "AES-GCM" },
      false,
      ["decrypt"],
    );
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: decode(envelope.iv) },
      aesKey,
      decode(envelope.ciphertext),
    );

    expect(JSON.parse(new TextDecoder().decode(plaintext))).toEqual({
      tencent_secret_id: "secret-id",
      tencent_secret_key: "secret-key",
      tencent_region: "ap-guangzhou",
      email_from_address: "sender@example.com",
      email_reply_to: "reply@example.com",
      email_template_id: "12345",
    });
  });
});
