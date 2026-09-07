import { isChatThreadId } from "./chat-request.js";

export const SESSION_HISTORY_PAGE_SIZE = 30;
export const MAX_SESSION_TITLE_CHARACTERS = 80;
export const MAX_SESSION_RENAME_BODY_BYTES = 1_024;
export const UNTITLED_SESSION_TITLE = "Untitled";

const SESSION_TITLE_DEFAULT_IGNORABLE = /\p{Default_Ignorable_Code_Point}/u;
const SESSION_TITLE_VISIBLE_BASE = /[\p{L}\p{N}\p{S}]/u;

export type SessionCursor = Readonly<{
  activityAt: string;
  id: string;
}>;
export type RenameSessionInput = Readonly<{
  expectedVersion: Date;
  title: string;
}>;

export class SessionInputError extends Error {
  constructor() {
    super("CHAT_SESSION_INPUT_INVALID");
    this.name = "SessionInputError";
  }
}

export function encodeSessionCursor(cursor: SessionCursor): string {
  const activityAt = parseExactDatabaseUtc(cursor.activityAt);
  if (!isChatThreadId(cursor.id)) throw new SessionInputError();
  return Buffer.from(JSON.stringify({
    a: activityAt,
    i: cursor.id.toLowerCase(),
    v: 1,
  }), "utf8").toString("base64url");
}

export function decodeSessionCursor(value: string): SessionCursor {
  if (value.length === 0 || value.length > 512 || !/^[A-Za-z0-9_-]+$/.test(value)) {
    throw new SessionInputError();
  }
  let decoded: unknown;
  try {
    const bytes = Buffer.from(value, "base64url");
    if (bytes.toString("base64url") !== value) throw new SessionInputError();
    decoded = JSON.parse(bytes.toString("utf8")) as unknown;
  } catch {
    throw new SessionInputError();
  }
  if (
    decoded === null
    || typeof decoded !== "object"
    || Array.isArray(decoded)
    || Object.keys(decoded).length !== 3
  ) {
    throw new SessionInputError();
  }
  const record = decoded as Record<string, unknown>;
  if (
    record.v !== 1
    || typeof record.a !== "string"
    || typeof record.i !== "string"
    || !isChatThreadId(record.i)
  ) {
    throw new SessionInputError();
  }
  return {
    activityAt: parseExactDatabaseUtc(record.a),
    id: record.i.toLowerCase(),
  };
}

export function normalizeSessionTitle(value: unknown): string {
  if (typeof value !== "string") throw new SessionInputError();
  const normalized = value.trim().replace(/\s+/gu, " ");
  if (
    normalized.length === 0
    || /[\u0000-\u001f\u007f-\u009f]/u.test(normalized)
    || SESSION_TITLE_DEFAULT_IGNORABLE.test(normalized)
    || !SESSION_TITLE_VISIBLE_BASE.test(normalized)
    || [...normalized].length > MAX_SESSION_TITLE_CHARACTERS
  ) {
    throw new SessionInputError();
  }
  return normalized;
}

export function normalizeReplacementSessionTitle(value: unknown): string {
  const normalized = normalizeSessionTitle(value);
  if (normalized === UNTITLED_SESSION_TITLE) throw new SessionInputError();
  return normalized;
}

export function parseSessionVersion(value: unknown): Date {
  if (typeof value !== "string") throw new SessionInputError();
  return parseExactUtc(value);
}

export function readSessionCursor(request: Request): SessionCursor | undefined {
  const parameters = new URL(request.url).searchParams;
  const keys = [...parameters.keys()];
  const cursors = parameters.getAll("cursor");
  if (keys.some((key) => key !== "cursor") || cursors.length > 1) {
    throw new SessionInputError();
  }
  const cursor = cursors[0];
  return cursor === undefined ? undefined : decodeSessionCursor(cursor);
}

export async function readRenameSessionInput(
  request: Request,
): Promise<RenameSessionInput> {
  const mediaType = request.headers.get("content-type")
    ?.split(";", 1)[0]
    ?.trim()
    .toLowerCase();
  if (mediaType !== "application/json") {
    throw new SessionInputError();
  }
  let value: unknown;
  try {
    const body = await request.clone().text();
    if (Buffer.byteLength(body, "utf8") > MAX_SESSION_RENAME_BODY_BYTES) {
      throw new SessionInputError();
    }
    value = JSON.parse(body) as unknown;
  } catch {
    throw new SessionInputError();
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new SessionInputError();
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record).sort();
  if (keys.length !== 2 || keys[0] !== "title" || keys[1] !== "version") {
    throw new SessionInputError();
  }
  return {
    expectedVersion: parseSessionVersion(record.version),
    title: normalizeReplacementSessionTitle(record.title),
  };
}

function parseExactUtc(value: string): Date {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString() !== value) {
    throw new SessionInputError();
  }
  return parsed;
}

function parseExactDatabaseUtc(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/u.test(value)) {
    throw new SessionInputError();
  }
  const milliseconds = `${value.slice(0, 23)}Z`;
  const parsed = new Date(milliseconds);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString() !== milliseconds) {
    throw new SessionInputError();
  }
  return value;
}
