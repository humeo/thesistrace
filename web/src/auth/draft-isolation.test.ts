import { expect, test } from "vitest";

import {
  emptyResearchDraft,
  loadResearchDraft,
  persistResearchDraft,
  researchDraftKey,
} from "../research/draft";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, value); },
  };
}

test("Draft keys hard-cut to Researcher and Folder identity", () => {
  expect(researchDraftKey("researcher-a", "folder_default")).toBe(
    "thesistrace.research-draft.researcher-a.folder_default",
  );
});

test("never reads a legacy Draft and isolates the same system Folder between Researchers", () => {
  const storage = memoryStorage();
  storage.setItem(
    "thesistrace.research-draft.folder_default",
    JSON.stringify({ ...emptyResearchDraft(), formula: "legacy" }),
  );
  persistResearchDraft(storage, "researcher-a", "folder_default", {
    ...emptyResearchDraft(),
    formula: "close",
  });

  expect(
    loadResearchDraft(storage, "researcher-a", "folder_default").formula,
  ).toBe("close");
  expect(
    loadResearchDraft(storage, "researcher-b", "folder_default"),
  ).toEqual(emptyResearchDraft());
  expect(storage.getItem("thesistrace.research-draft.folder_default")).not.toBeNull();
});
