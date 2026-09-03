import { isUuid } from "../uuid";

export const MAX_STAGED_INPUTS = 20;
export const MAX_STAGED_INPUT_BYTES = 16 * 1024;
const DATABASE_NAME = "thesistrace-chat-stage";
const STORE_NAME = "items";
const LEASE_MS = 15_000;

export type StagedInput = Readonly<{
  content: string;
  createdAt: string;
  inputId: string;
  leaseOwner: string | null;
  leaseUntil: number | null;
  researcherId: string;
  sequence: number;
  sessionId: string;
  status: "staged" | "submitting";
}>;

export class StagedInputStoreError extends Error {
  constructor(readonly code: "STAGE_LIMIT" | "STAGE_STORAGE_CORRUPT" | "STAGE_STORAGE_FAILED") {
    super(code);
    this.name = "StagedInputStoreError";
  }
}

export class StagedInputStore {
  private databasePromise: Promise<IDBDatabase> | null = null;

  constructor(private readonly factory: IDBFactory = window.indexedDB) {}

  async list(researcherId: string, sessionId: string): Promise<readonly StagedInput[]> {
    const database = await this.database();
    const transaction = database.transaction(STORE_NAME, "readonly");
    const values = await request(transaction.objectStore(STORE_NAME).index("scope").getAll(scope(researcherId, sessionId)));
    await transactionDone(transaction);
    try {
      return values.map(readItem).sort((left, right) => left.sequence - right.sequence);
    } catch {
      throw new StagedInputStoreError("STAGE_STORAGE_CORRUPT");
    }
  }

  async stage(researcherId: string, sessionId: string, content: string, inputId = crypto.randomUUID()): Promise<StagedInput> {
    validateIdentity(researcherId, sessionId, inputId);
    validateContent(content);
    const database = await this.database();
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const count = await request(store.index("scope").count(scope(researcherId, sessionId)));
    if (count >= MAX_STAGED_INPUTS) {
      transaction.abort();
      throw new StagedInputStoreError("STAGE_LIMIT");
    }
    const createdAt = new Date().toISOString();
    const key = await request(store.add({
      content,
      createdAt,
      inputId,
      leaseOwner: null,
      leaseUntil: null,
      researcherId,
      scope: scope(researcherId, sessionId),
      sessionId,
      status: "staged",
    }));
    await transactionDone(transaction);
    if (typeof key !== "number") throw new StagedInputStoreError("STAGE_STORAGE_CORRUPT");
    return {
      content,
      createdAt,
      inputId,
      leaseOwner: null,
      leaseUntil: null,
      researcherId,
      sequence: key,
      sessionId,
      status: "staged",
    };
  }

  async delete(item: StagedInput): Promise<void> {
    await this.mutate(item, (stored, store) => {
      if (stored.status !== "staged") throw new StagedInputStoreError("STAGE_STORAGE_FAILED");
      store.delete(item.sequence);
    });
  }

  async claimHead(
    researcherId: string,
    sessionId: string,
    inputId: string,
    owner: string,
    now = Date.now(),
  ): Promise<StagedInput | null> {
    const database = await this.database();
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const values = await request(store.index("scope").getAll(scope(researcherId, sessionId)));
    let items: readonly StagedInput[];
    try {
      items = values.map(readItem).sort((left, right) => left.sequence - right.sequence);
    } catch {
      transaction.abort();
      throw new StagedInputStoreError("STAGE_STORAGE_CORRUPT");
    }
    const head = items[0];
    if (
      head === undefined
      || head.inputId !== inputId
      || (head.status === "submitting" && (head.leaseUntil ?? Number.POSITIVE_INFINITY) > now)
    ) {
      transaction.abort();
      return null;
    }
    const claimed: StagedInput = {
      ...head,
      leaseOwner: owner,
      leaseUntil: now + LEASE_MS,
      status: "submitting",
    };
    store.put({ ...claimed, scope: scope(researcherId, sessionId) });
    await transactionDone(transaction);
    return claimed;
  }

  async markSubmitting(item: StagedInput, owner: string): Promise<StagedInput> {
    let updated: StagedInput | undefined;
    await this.mutate(item, (stored, store) => {
      if (stored.status !== "staged") throw new StagedInputStoreError("STAGE_STORAGE_FAILED");
      updated = {
        ...stored,
        leaseOwner: owner,
        leaseUntil: Date.now() + LEASE_MS,
        status: "submitting",
      };
      store.put({ ...updated, scope: scope(item.researcherId, item.sessionId) });
    });
    if (updated === undefined) throw new StagedInputStoreError("STAGE_STORAGE_FAILED");
    return updated;
  }

  async release(item: StagedInput): Promise<void> {
    await this.mutate(item, (stored, store) => {
      if (stored.status !== "submitting") return;
      if (stored.leaseOwner !== item.leaseOwner) return;
      store.put({
        ...stored,
        leaseOwner: null,
        leaseUntil: null,
        scope: scope(item.researcherId, item.sessionId),
        status: "staged",
      });
    });
  }

  async removeAccepted(item: StagedInput): Promise<void> {
    await this.mutate(item, (stored, store) => {
      if (
        stored.status === "submitting"
        && item.leaseOwner !== null
        && stored.leaseOwner !== item.leaseOwner
      ) return;
      store.delete(item.sequence);
    });
  }

  private async mutate(
    item: StagedInput,
    change: (stored: StagedInput, store: IDBObjectStore) => void,
  ): Promise<void> {
    const database = await this.database();
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    const raw = await request(store.get(item.sequence));
    let stored: StagedInput;
    try {
      stored = readItem(raw);
    } catch {
      transaction.abort();
      throw new StagedInputStoreError("STAGE_STORAGE_CORRUPT");
    }
    if (
      stored.inputId !== item.inputId
      || stored.researcherId !== item.researcherId
      || stored.sessionId !== item.sessionId
    ) {
      transaction.abort();
      throw new StagedInputStoreError("STAGE_STORAGE_CORRUPT");
    }
    change(stored, store);
    await transactionDone(transaction);
  }

  private database(): Promise<IDBDatabase> {
    if (this.databasePromise !== null) return this.databasePromise;
    const openingPromise = new Promise<IDBDatabase>((resolve, reject) => {
      const opening = this.factory.open(DATABASE_NAME, 1);
      opening.onupgradeneeded = () => {
        const database = opening.result;
        const store = database.createObjectStore(STORE_NAME, { autoIncrement: true, keyPath: "sequence" });
        store.createIndex("scopeInput", ["scope", "inputId"], { unique: true });
        store.createIndex("scope", "scope", { unique: false });
      };
      opening.onerror = () => reject(new StagedInputStoreError("STAGE_STORAGE_FAILED"));
      opening.onblocked = () => reject(new StagedInputStoreError("STAGE_STORAGE_FAILED"));
      opening.onsuccess = () => {
        opening.result.onversionchange = () => opening.result.close();
        resolve(opening.result);
      };
    });
    this.databasePromise = openingPromise;
    void openingPromise.catch(() => {
      if (this.databasePromise === openingPromise) this.databasePromise = null;
    });
    return openingPromise;
  }
}

export function createStagedInputChannel(
  researcherId: string,
  sessionId: string,
  onChange: () => void,
): Readonly<{ close: () => void; notify: () => void }> {
  const channel = new BroadcastChannel(`thesistrace-stage:${scope(researcherId, sessionId)}`);
  channel.addEventListener("message", onChange);
  return {
    close: () => channel.close(),
    notify: () => channel.postMessage({ type: "changed" }),
  };
}

export async function withStagedDeliveryLock<T>(
  researcherId: string,
  sessionId: string,
  operation: () => Promise<T>,
): Promise<T> {
  if (!isUuid(researcherId) || !isUuid(sessionId)) {
    throw new StagedInputStoreError("STAGE_STORAGE_FAILED");
  }
  return navigator.locks.request(
    `thesistrace-stage-delivery:${researcherId}:${sessionId}`,
    { mode: "exclusive" },
    operation,
  );
}

function readItem(value: unknown): StagedInput {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new StagedInputStoreError("STAGE_STORAGE_CORRUPT");
  }
  const item = value as Record<string, unknown>;
  if (
    typeof item.content !== "string"
    || typeof item.createdAt !== "string"
    || Number.isNaN(Date.parse(item.createdAt))
    || typeof item.inputId !== "string"
    || !isUuid(item.inputId)
    || !(item.leaseOwner === null || (typeof item.leaseOwner === "string" && isUuid(item.leaseOwner)))
    || !(item.leaseUntil === null || (
      typeof item.leaseUntil === "number"
      && Number.isSafeInteger(item.leaseUntil)
      && item.leaseUntil > 0
    ))
    || typeof item.researcherId !== "string"
    || !isUuid(item.researcherId)
    || typeof item.sequence !== "number"
    || !Number.isSafeInteger(item.sequence)
    || typeof item.sessionId !== "string"
    || !isUuid(item.sessionId)
    || (item.status !== "staged" && item.status !== "submitting")
    || (item.status === "staged" && (item.leaseOwner !== null || item.leaseUntil !== null))
    || (item.status === "submitting" && (item.leaseOwner === null || item.leaseUntil === null))
    || item.scope !== scope(item.researcherId, item.sessionId)
  ) throw new StagedInputStoreError("STAGE_STORAGE_CORRUPT");
  validateContent(item.content);
  return item as unknown as StagedInput;
}

function validateContent(content: string): void {
  const bytes = new TextEncoder().encode(content).byteLength;
  if (content.trim().length === 0 || bytes > MAX_STAGED_INPUT_BYTES) {
    throw new StagedInputStoreError("STAGE_STORAGE_FAILED");
  }
}

function validateIdentity(researcherId: string, sessionId: string, inputId: string): void {
  if (!isUuid(researcherId) || !isUuid(sessionId) || !isUuid(inputId)) {
    throw new StagedInputStoreError("STAGE_STORAGE_FAILED");
  }
}

function scope(researcherId: string, sessionId: string): string {
  return `${researcherId}:${sessionId}`;
}

function request<T>(value: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    value.onsuccess = () => resolve(value.result);
    value.onerror = () => reject(new StagedInputStoreError("STAGE_STORAGE_FAILED"));
  });
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(new StagedInputStoreError("STAGE_STORAGE_FAILED"));
    transaction.onerror = () => reject(new StagedInputStoreError("STAGE_STORAGE_FAILED"));
  });
}
