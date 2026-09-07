import { describe, expect, it } from "vitest";

import {
  MAX_SESSION_TITLE_CHARACTERS,
  SESSION_HISTORY_PAGE_SIZE,
  SessionInputError,
  UNTITLED_SESSION_TITLE,
  decodeSessionCursor,
  encodeSessionCursor,
  normalizeReplacementSessionTitle,
  normalizeSessionTitle,
  readRenameSessionInput,
  readSessionCursor,
  parseSessionVersion,
} from "./session-management.js";

const cursor = {
  activityAt: "2026-08-30T02:03:04.567123Z",
  id: "00000000-0000-4000-8000-000000000123",
};

describe("Session management contract", () => {
  it("pins one bounded history page and a clear empty title", () => {
    expect(SESSION_HISTORY_PAGE_SIZE).toBe(30);
    expect(UNTITLED_SESSION_TITLE).toBe("Untitled");
    expect(MAX_SESSION_TITLE_CHARACTERS).toBe(80);
  });

  it("round-trips one versioned opaque keyset cursor", () => {
    const encoded = encodeSessionCursor(cursor);

    expect(encoded).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(encoded).not.toContain(cursor.id);
    expect(decodeSessionCursor(encoded)).toEqual(cursor);
  });

  it.each([
    "",
    "not-base64",
    "a".repeat(513),
    Buffer.from("{}", "utf8").toString("base64url"),
    Buffer.from(JSON.stringify({ v: 2, a: cursor.activityAt, i: cursor.id }))
      .toString("base64url"),
    Buffer.from(JSON.stringify({ v: 1, a: "2026-08-30", i: cursor.id }))
      .toString("base64url"),
    Buffer.from(JSON.stringify({
      v: 1,
      a: cursor.activityAt,
      i: "not-a-session",
    })).toString("base64url"),
  ])("rejects a malformed or unsupported cursor: %s", (encoded) => {
    expect(() => decodeSessionCursor(encoded)).toThrow(SessionInputError);
  });

  it("normalizes one manual title without creating another title shape", () => {
    expect(normalizeSessionTitle("  Low-volatility\n quality   Alpha  ")).toBe(
      "Low-volatility quality Alpha",
    );
    expect(normalizeSessionTitle("研究  Alpha"))
      .toBe("研究 Alpha");
    expect(normalizeSessionTitle("😀"))
      .toBe("😀");
  });

  it("rejects blank, non-string, control, and overlong titles", () => {
    expect(() => normalizeSessionTitle(" \n\t ")).toThrow(SessionInputError);
    expect(() => normalizeSessionTitle(42)).toThrow(SessionInputError);
    expect(() => normalizeSessionTitle("Alpha\u0000Research")).toThrow(SessionInputError);
    expect(() => normalizeSessionTitle("a".repeat(81))).toThrow(SessionInputError);
  });

  it.each([
    "\u200B",
    "Untitled\u200B",
    "\uFE0F",
    "\u0301",
    "Alpha\u200B",
    "!!!",
  ])("rejects a title without one visible base or with invisible code points: %s", (title) => {
    expect(() => normalizeSessionTitle(title)).toThrow(SessionInputError);
  });

  it("reserves the exact Untitled sentinel from manual rename", async () => {
    expect(() => normalizeReplacementSessionTitle(UNTITLED_SESSION_TITLE))
      .toThrow(SessionInputError);
    expect(normalizeReplacementSessionTitle("Research untitled signals"))
      .toBe("Research untitled signals");
    await expect(readRenameSessionInput(new Request("http://agent.test", {
      body: JSON.stringify({
        title: UNTITLED_SESSION_TITLE,
        version: "2026-08-30T02:03:04.567Z",
      }),
      headers: { "content-type": "Application/JSON; charset=utf-8" },
      method: "PATCH",
    }))).rejects.toBeInstanceOf(SessionInputError);
  });

  it("accepts only exact UTC Thread versions", () => {
    expect(parseSessionVersion("2026-08-30T02:03:04.567Z")).toEqual(
      new Date("2026-08-30T02:03:04.567Z"),
    );
    expect(() => parseSessionVersion("2026-08-30T02:03:04Z"))
      .toThrow(SessionInputError);
    expect(() => parseSessionVersion("2026-08-30"))
      .toThrow(SessionInputError);
  });

  it("reads either no cursor or one exact cursor and rejects every other query shape", () => {
    expect(readSessionCursor(new Request("http://agent.test/api/agent/sessions")))
      .toBeUndefined();
    expect(readSessionCursor(new Request(
      `http://agent.test/api/agent/sessions?cursor=${encodeSessionCursor(cursor)}`,
    ))).toEqual(cursor);
    expect(() => readSessionCursor(new Request(
      "http://agent.test/api/agent/sessions?cursor=a&cursor=b",
    ))).toThrow(SessionInputError);
    expect(() => readSessionCursor(new Request(
      "http://agent.test/api/agent/sessions?page=1",
    ))).toThrow(SessionInputError);
  });

  it("reads one strict bounded rename command", async () => {
    await expect(readRenameSessionInput(new Request("http://agent.test", {
      body: JSON.stringify({
        title: "  Quality Alpha  ",
        version: "2026-08-30T02:03:04.567Z",
      }),
      headers: { "content-type": "Application/JSON; charset=utf-8" },
      method: "PATCH",
    }))).resolves.toEqual({
      expectedVersion: new Date("2026-08-30T02:03:04.567Z"),
      title: "Quality Alpha",
    });

    await expect(readRenameSessionInput(new Request("http://agent.test", {
      body: JSON.stringify({
        extra: true,
        title: "Quality Alpha",
        version: "2026-08-30T02:03:04.567Z",
      }),
      headers: { "content-type": "application/json" },
      method: "PATCH",
    }))).rejects.toBeInstanceOf(SessionInputError);
    await expect(readRenameSessionInput(new Request("http://agent.test", {
      body: JSON.stringify({
        title: "a".repeat(1_100),
        version: "2026-08-30T02:03:04.567Z",
      }),
      headers: { "content-type": "application/json" },
      method: "PATCH",
    }))).rejects.toBeInstanceOf(SessionInputError);
    for (const contentType of ["application/jsonp", "application/json-patch+json"]) {
      await expect(readRenameSessionInput(new Request("http://agent.test", {
        body: JSON.stringify({
          title: "Quality Alpha",
          version: "2026-08-30T02:03:04.567Z",
        }),
        headers: { "content-type": contentType },
        method: "PATCH",
      }))).rejects.toBeInstanceOf(SessionInputError);
    }
  });
});
