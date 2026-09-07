export type InvitationStatus =
  | "consumed"
  | "delivered"
  | "delivery_failed"
  | "delivery_pending"
  | "expired"
  | "revoked";

export type OperatorInvitation = Readonly<{
  created_at: string;
  delivered_at: string | null;
  effective: boolean;
  email: string;
  expires_at: string;
  invitation_id: string;
  researcher_id: string | null;
  status: InvitationStatus;
  terminal_at: string | null;
}>;

export type OperatorResearcher = Readonly<{
  active: boolean;
  created_at: string;
  current_session_count: number;
  display_label: string;
  effective_invitation: OperatorInvitation | null;
  email: string;
  latest_successful_login_at: string | null;
  researcher_id: string;
}>;

export type OperatorPage<T> = Readonly<{
  items: readonly T[];
  next_cursor: string | null;
}>;

export class OperatorPageNotFoundError extends Error {}
export class OperatorPageUnavailableError extends Error {}

export function decodeResearcherPage(value: unknown): OperatorPage<OperatorResearcher> {
  if (!isPage(value)) throw new Error("Operator Researcher response is invalid");
  const items = value.items.map((item) => decodeResearcher(item));
  return { items, next_cursor: decodeCursor(value.next_cursor, "Researcher") };
}

export function decodeInvitationPage(value: unknown): OperatorPage<OperatorInvitation> {
  if (!isPage(value)) throw new Error("Operator Invitation response is invalid");
  const items = value.items.map((item) => decodeInvitation(item));
  return { items, next_cursor: decodeCursor(value.next_cursor, "Invitation") };
}

export async function loadResearcherPage(
  search: string,
  cursor: string | null,
  signal: AbortSignal,
): Promise<OperatorPage<OperatorResearcher>> {
  const query = new URLSearchParams();
  if (search.trim() !== "") query.set("search", search);
  if (cursor !== null) query.set("cursor", cursor);
  const suffix = query.size === 0 ? "" : `?${query.toString()}`;
  return decodeResearcherPage(await operatorJson(
    `/api/auth/operator/researchers${suffix}`,
    signal,
  ));
}

export async function loadInvitationPage(
  cursor: string | null,
  signal: AbortSignal,
): Promise<OperatorPage<OperatorInvitation>> {
  const suffix = cursor === null ? "" : `?cursor=${encodeURIComponent(cursor)}`;
  return decodeInvitationPage(await operatorJson(
    `/api/auth/operator/invitations${suffix}`,
    signal,
  ));
}

async function operatorJson(path: string, signal: AbortSignal): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(path, { credentials: "same-origin", signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new OperatorPageUnavailableError();
  }
  if (response.status === 404) throw new OperatorPageNotFoundError();
  if (!response.ok) throw new OperatorPageUnavailableError();
  try {
    return await response.json();
  } catch {
    throw new OperatorPageUnavailableError();
  }
}

function decodeResearcher(value: unknown): OperatorResearcher {
  const keys = [
    "active",
    "created_at",
    "current_session_count",
    "display_label",
    "effective_invitation",
    "email",
    "latest_successful_login_at",
    "researcher_id",
  ];
  if (
    !hasExactKeys(value, keys)
    || typeof value.active !== "boolean"
    || !isIsoTimestamp(value.created_at)
    || typeof value.current_session_count !== "number"
    || !Number.isSafeInteger(value.current_session_count)
    || value.current_session_count < 0
    || typeof value.display_label !== "string"
    || value.display_label.trim() === ""
    || typeof value.email !== "string"
    || !isEmail(value.email)
    || (value.latest_successful_login_at !== null
      && !isIsoTimestamp(value.latest_successful_login_at))
    || !isUuid(value.researcher_id)
  ) throw new Error("Operator Researcher response is invalid");
  let effectiveInvitation: OperatorInvitation | null = null;
  if (value.effective_invitation !== null) {
    try {
      effectiveInvitation = decodeInvitation(value.effective_invitation);
    } catch {
      throw new Error("Operator Researcher response is invalid");
    }
    if (!effectiveInvitation.effective) {
      throw new Error("Operator Researcher response is invalid");
    }
  }
  return {
    active: value.active,
    created_at: value.created_at,
    current_session_count: value.current_session_count,
    display_label: value.display_label,
    effective_invitation: effectiveInvitation,
    email: value.email,
    latest_successful_login_at: value.latest_successful_login_at,
    researcher_id: value.researcher_id,
  };
}

function decodeInvitation(value: unknown): OperatorInvitation {
  const keys = [
    "created_at",
    "delivered_at",
    "effective",
    "email",
    "expires_at",
    "invitation_id",
    "researcher_id",
    "status",
    "terminal_at",
  ];
  if (
    !hasExactKeys(value, keys)
    || !isIsoTimestamp(value.created_at)
    || (value.delivered_at !== null && !isIsoTimestamp(value.delivered_at))
    || typeof value.effective !== "boolean"
    || typeof value.email !== "string"
    || !isEmail(value.email)
    || !isIsoTimestamp(value.expires_at)
    || !isUuid(value.invitation_id)
    || (value.researcher_id !== null && !isUuid(value.researcher_id))
    || !isInvitationStatus(value.status)
    || (value.terminal_at !== null && !isIsoTimestamp(value.terminal_at))
  ) throw new Error("Operator Invitation response is invalid");
  return value as OperatorInvitation;
}

function isPage(value: unknown): value is Record<string, unknown> & {
  items: unknown[];
  next_cursor: unknown;
} {
  return hasExactKeys(value, ["items", "next_cursor"]) && Array.isArray(value.items);
}

function decodeCursor(value: unknown, resource: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > 1024) {
    throw new Error(`Operator ${resource} response is invalid`);
  }
  return value;
}

function hasExactKeys(
  value: unknown,
  keys: readonly string[],
): value is Record<string, unknown> {
  return isRecord(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString() === value;
}

function isUuid(value: unknown): value is string {
  return typeof value === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function isEmail(value: string): boolean {
  return value === value.trim().toLowerCase()
    && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function isInvitationStatus(value: unknown): value is InvitationStatus {
  return value === "consumed"
    || value === "delivered"
    || value === "delivery_failed"
    || value === "delivery_pending"
    || value === "expired"
    || value === "revoked";
}
