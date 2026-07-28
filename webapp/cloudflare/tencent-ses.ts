type TencentSecrets = {
  TENCENT_SECRET_ID: string;
  TENCENT_SECRET_KEY: string;
  TENCENT_REGION: string;
  EMAIL_FROM_ADDRESS: string;
  EMAIL_REPLY_TO: string;
  EMAIL_TEMPLATE_ID: string;
};

const ENDPOINT = "ses.tencentcloudapi.com";
const SERVICE = "ses";
const VERSION = "2020-10-02";
const encoder = new TextEncoder();

function toHex(value: ArrayBuffer): string {
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function sha256(value: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", encoder.encode(value));
}

async function hmac(key: string | ArrayBuffer, value: string): Promise<ArrayBuffer> {
  const imported = await crypto.subtle.importKey(
    "raw",
    typeof key === "string" ? encoder.encode(key) : key,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return crypto.subtle.sign("HMAC", imported, encoder.encode(value));
}

export async function sendTencentTemplateEmail(
  env: TencentSecrets,
  recipient: string,
  subject: string,
  body: string,
  category = "场地提醒",
): Promise<{ messageId: string | null; requestId: string | null }> {
  const timestamp = Math.floor(Date.now() / 1000);
  const date = new Date(timestamp * 1000).toISOString().slice(0, 10);
  const payload = JSON.stringify({
    FromEmailAddress: env.EMAIL_FROM_ADDRESS,
    Destination: [recipient],
    Subject: subject,
    Template: {
      TemplateID: Number(env.EMAIL_TEMPLATE_ID),
      TemplateData: JSON.stringify({
        COURT_NAME: category,
        FREE_TIME: body,
      }),
    },
    ReplyToAddresses: env.EMAIL_REPLY_TO,
    TriggerType: 1,
  });

  const contentType = "application/json";
  const action = "SendEmail";
  const canonicalHeaders = [
    `content-type:${contentType}`,
    `host:${ENDPOINT}`,
    "",
  ].join("\n");
  const signedHeaders = "content-type;host";
  const canonicalRequest = [
    "POST",
    "/",
    "",
    canonicalHeaders,
    signedHeaders,
    toHex(await sha256(payload)),
  ].join("\n");
  const credentialScope = `${date}/${SERVICE}/tc3_request`;
  const stringToSign = [
    "TC3-HMAC-SHA256",
    String(timestamp),
    credentialScope,
    toHex(await sha256(canonicalRequest)),
  ].join("\n");
  const secretDate = await hmac(`TC3${env.TENCENT_SECRET_KEY}`, date);
  const secretService = await hmac(secretDate, SERVICE);
  const secretSigning = await hmac(secretService, "tc3_request");
  const signature = toHex(await hmac(secretSigning, stringToSign));
  const authorization = [
    `TC3-HMAC-SHA256 Credential=${env.TENCENT_SECRET_ID}/${credentialScope}`,
    `SignedHeaders=${signedHeaders}`,
    `Signature=${signature}`,
  ].join(", ");

  const response = await fetch(`https://${ENDPOINT}`, {
    method: "POST",
    headers: {
      Authorization: authorization,
      "Content-Type": contentType,
      "X-TC-Action": action,
      "X-TC-Region": env.TENCENT_REGION,
      "X-TC-Timestamp": String(timestamp),
      "X-TC-Version": VERSION,
    },
    body: payload,
  });
  const result = await response.json<{
    Response?: {
      MessageId?: string;
      RequestId?: string;
      Error?: { Code?: string; Message?: string };
    };
  }>();
  const error = result.Response?.Error;
  if (!response.ok || error) {
    throw new Error(
      `${error?.Code ?? `HTTP_${response.status}`}: ${error?.Message ?? "邮件发送失败"}`,
    );
  }
  return {
    messageId: result.Response?.MessageId ?? null,
    requestId: result.Response?.RequestId ?? null,
  };
}
