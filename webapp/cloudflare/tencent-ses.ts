export type TencentSecrets = {
  TENCENT_SECRET_ID: string;
  TENCENT_SECRET_KEY: string;
  TENCENT_REGION: string;
  EMAIL_FROM_ADDRESS: string;
  EMAIL_REPLY_TO: string;
  EMAIL_TEMPLATE_ID: string;
};

export type TencentEmailStatus = {
  MessageId?: string;
  ToEmailAddress?: string;
  SendStatus?: number | string;
  DeliverStatus?: number | string;
  DeliverTime?: number | string;
  DeliverMessage?: string;
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

async function callTencentSes<T>(
  env: TencentSecrets,
  action: string,
  payloadValue: Record<string, unknown>,
): Promise<{ response: T; requestId: string | null }> {
  const timestamp = Math.floor(Date.now() / 1000);
  const date = new Date(timestamp * 1000).toISOString().slice(0, 10);
  const payload = JSON.stringify(payloadValue);
  const contentType = "application/json";
  const canonicalHeaders = `content-type:${contentType}\nhost:${ENDPOINT}\n`;
  const signedHeaders = "content-type;host";
  const canonicalRequest = [
    "POST", "/", "", canonicalHeaders, signedHeaders, toHex(await sha256(payload)),
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
  const httpResponse = await fetch(`https://${ENDPOINT}`, {
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
  const result = await httpResponse.json<{
    Response?: T & {
      RequestId?: string;
      Error?: { Code?: string; Message?: string };
    };
  }>();
  const error = result.Response?.Error;
  if (!httpResponse.ok || error || !result.Response) {
    throw new Error(
      `${error?.Code ?? `HTTP_${httpResponse.status}`}: ${error?.Message ?? "腾讯云邮件接口调用失败"}`,
    );
  }
  return {
    response: result.Response,
    requestId: result.Response.RequestId ?? null,
  };
}

export async function sendTencentTemplateEmail(
  env: TencentSecrets,
  recipient: string,
  subject: string,
  body: string,
  category = "场地提醒",
): Promise<{ messageId: string | null; requestId: string | null }> {
  const result = await callTencentSes<{ MessageId?: string }>(env, "SendEmail", {
    FromEmailAddress: env.EMAIL_FROM_ADDRESS,
    Destination: [recipient],
    Subject: subject,
    Template: {
      TemplateID: Number(env.EMAIL_TEMPLATE_ID),
      TemplateData: JSON.stringify({ COURT_NAME: category, FREE_TIME: body }),
    },
    ReplyToAddresses: env.EMAIL_REPLY_TO,
    TriggerType: 1,
  });
  return {
    messageId: result.response.MessageId ?? null,
    requestId: result.requestId,
  };
}

function shanghaiDate(offsetDays = 0, now = Date.now()): string {
  const shifted = new Date(now + 8 * 3_600_000 + offsetDays * 86_400_000);
  return shifted.toISOString().slice(0, 10);
}

export function tencentStatusRequestDates(
  messageId: string,
  now = Date.now(),
): string[] {
  const dates: string[] = [];
  const append = (value: string) => {
    if (/^\d{4}-\d{2}-\d{2}$/.test(value) && !dates.includes(value)) dates.push(value);
  };
  const embedded = messageId.match(/(?:^|-)date-(\d{4})(\d{2})(\d{2})\d{6}(?:-|$)/i);
  if (embedded) append(`${embedded[1]}-${embedded[2]}-${embedded[3]}`);
  for (const offsetDays of [0, -1, -2]) append(shanghaiDate(offsetDays, now));
  return dates;
}

async function queryTencentEmailStatus(
  env: TencentSecrets,
  requestDate: string,
  filter: { MessageId: string } | { ToEmailAddress: string },
): Promise<TencentEmailStatus[]> {
  const result = await callTencentSes<{
    EmailStatusList?: TencentEmailStatus[];
  }>(env, "GetSendEmailStatus", {
    RequestDate: requestDate,
    Offset: 0,
    Limit: 100,
    ...filter,
  });
  return result.response.EmailStatusList ?? [];
}

export async function getTencentEmailStatus(
  env: TencentSecrets,
  messageId: string,
  recipient?: string,
): Promise<TencentEmailStatus | null> {
  const requestDates = tencentStatusRequestDates(messageId);

  // Tencent's documented examples use either MessageId or ToEmailAddress as the
  // query filter. Query by MessageId first instead of combining both optional
  // filters, which is also sufficient to identify one provider delivery.
  for (const requestDate of requestDates) {
    const match = (await queryTencentEmailStatus(env, requestDate, { MessageId: messageId }))
      .find((item) => item.MessageId === messageId);
    if (match) return match;
  }

  // Some older/partial provider records can fail to match the MessageId index.
  // Fall back to the recipient-only query and still require the exact MessageId
  // in the returned list before accepting the record.
  if (recipient) {
    for (const requestDate of requestDates) {
      const match = (await queryTencentEmailStatus(
        env,
        requestDate,
        { ToEmailAddress: recipient },
      )).find((item) => item.MessageId === messageId);
      if (match) return match;
    }
  }
  return null;
}
