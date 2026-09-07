import {
  createCipheriv,
  createDecipheriv,
  createHash,
  randomBytes as cryptoRandomBytes,
} from "node:crypto";

import { z } from "zod";

const CURSOR_VERSION = 1;
const CURSOR_IV_BYTES = 12;
const CURSOR_TAG_BYTES = 16;
const CURSOR_AAD = Buffer.from(
  "thesistrace:operator-directory-cursor:v1",
  "utf8",
);
const directoryIdSchema = z.uuid();

type CursorCollection = "invitations" | "researchers";

export type OperatorCursorPosition = Readonly<{
  createdAt: Date;
  id: string;
}>;

export class OperatorCursorInvalidError extends Error {
  readonly code = "OPERATOR_CURSOR_INVALID";

  constructor() {
    super("OPERATOR_CURSOR_INVALID");
    this.name = "OperatorCursorInvalidError";
  }
}

export class OperatorCursorCodec {
  readonly #key: Buffer;
  readonly #randomBytes: (size: number) => Buffer;

  constructor(dependencies: Readonly<{
    authSecret: string;
    randomBytes?: (size: number) => Buffer;
  }>) {
    this.#key = createHash("sha256")
      .update("thesistrace:operator-directory-cursor\0", "utf8")
      .update(dependencies.authSecret, "utf8")
      .digest();
    this.#randomBytes = dependencies.randomBytes ?? cryptoRandomBytes;
  }

  encode(
    collection: CursorCollection,
    row: Readonly<{ created_at: Date; id: string }>,
    search: string | null,
  ): string {
    const iv = this.#randomBytes(CURSOR_IV_BYTES);
    if (iv.length !== CURSOR_IV_BYTES) {
      throw new Error("OPERATOR_CURSOR_RANDOM_INVALID");
    }
    const cipher = createCipheriv("aes-256-gcm", this.#key, iv);
    cipher.setAAD(CURSOR_AAD);
    const plaintext = Buffer.from(
      JSON.stringify({
        collection,
        createdAt: isoDate(row.created_at),
        id: row.id,
        order: "created_at_desc_id_desc",
        search,
      }),
      "utf8",
    );
    const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
    return Buffer.concat([
      Buffer.from([CURSOR_VERSION]),
      iv,
      cipher.getAuthTag(),
      ciphertext,
    ]).toString("base64url");
  }

  decode(
    cursor: string | null,
    collection: CursorCollection,
    search: string | null,
  ): OperatorCursorPosition | null {
    if (cursor === null) return null;
    try {
      if (cursor.length === 0 || cursor.length > 1024 || !/^[A-Za-z0-9_-]+$/.test(cursor)) {
        throw new Error("invalid cursor encoding");
      }
      const encoded = Buffer.from(cursor, "base64url");
      if (
        encoded.toString("base64url") !== cursor
        || encoded.length <= 1 + CURSOR_IV_BYTES + CURSOR_TAG_BYTES
        || encoded[0] !== CURSOR_VERSION
      ) {
        throw new Error("invalid cursor envelope");
      }
      const ivStart = 1;
      const tagStart = ivStart + CURSOR_IV_BYTES;
      const ciphertextStart = tagStart + CURSOR_TAG_BYTES;
      const decipher = createDecipheriv(
        "aes-256-gcm",
        this.#key,
        encoded.subarray(ivStart, tagStart),
      );
      decipher.setAAD(CURSOR_AAD);
      decipher.setAuthTag(encoded.subarray(tagStart, ciphertextStart));
      const plaintext = Buffer.concat([
        decipher.update(encoded.subarray(ciphertextStart)),
        decipher.final(),
      ]).toString("utf8");
      const value: unknown = JSON.parse(plaintext);
      if (
        !isRecord(value)
        || Object.keys(value).sort().join(",")
          !== "collection,createdAt,id,order,search"
        || value.collection !== collection
        || value.order !== "created_at_desc_id_desc"
        || value.search !== search
        || typeof value.createdAt !== "string"
        || typeof value.id !== "string"
        || !directoryIdSchema.safeParse(value.id).success
      ) {
        throw new Error("invalid cursor payload");
      }
      const createdAt = new Date(value.createdAt);
      if (!Number.isFinite(createdAt.getTime()) || createdAt.toISOString() !== value.createdAt) {
        throw new Error("invalid cursor position");
      }
      return { createdAt, id: value.id };
    } catch {
      throw new OperatorCursorInvalidError();
    }
  }
}

function isoDate(value: Date): string {
  if (!(value instanceof Date) || !Number.isFinite(value.getTime())) {
    throw new Error("OPERATOR_CURSOR_ROW_INVALID");
  }
  return value.toISOString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
