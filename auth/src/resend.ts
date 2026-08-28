export type ResendSettings = Readonly<{
  apiKey: string;
  apiUrl: string;
  fromEmail: string;
}>;

export type ResendEmail = Readonly<{
  html: string;
  subject: string;
  text: string;
  to: string;
}>;

export class ResendDeliveryError extends Error {
  constructor() {
    super("RESEND_DELIVERY_FAILED");
    this.name = "ResendDeliveryError";
  }
}

export async function sendResendEmail(
  settings: ResendSettings,
  email: ResendEmail,
  fetcher: typeof fetch = fetch,
): Promise<void> {
  try {
    const response = await fetcher(`${settings.apiUrl}/emails`, {
      body: JSON.stringify({
        from: settings.fromEmail,
        html: email.html,
        subject: email.subject,
        text: email.text,
        to: [email.to],
      }),
      headers: {
        authorization: `Bearer ${settings.apiKey}`,
        "content-type": "application/json",
      },
      method: "POST",
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) {
      throw new ResendDeliveryError();
    }
  } catch (error) {
    if (error instanceof ResendDeliveryError) {
      throw error;
    }
    throw new ResendDeliveryError();
  }
}
