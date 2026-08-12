export const BROWSER_DRAFT_STORAGE_KEY = "thesistrace.research-draft.v1";

export type ResearchBrowserDraft = {
  name: string;
  hypothesis: string;
  start_date: string;
  end_date: string;
  alpha: Record<string, unknown> | null;
  universe: "top300" | "top1000" | "top2000" | "top3000" | "";
  neutralization: "none" | "industry" | "";
  holdings_count: string;
  rebalance_every_sessions: string;
};

export type ResearchRunDraft = {
  name: string;
  hypothesis: string | null;
  start_date: string;
  end_date: string;
  alpha: Record<string, unknown>;
  universe: "top300" | "top1000" | "top2000" | "top3000";
  neutralization: "none" | "industry";
  holdings_count: number;
  rebalance_every_sessions: number;
};

export function browserDraftFromRun(draft: ResearchRunDraft): ResearchBrowserDraft {
  return {
    ...draft,
    hypothesis: draft.hypothesis ?? "",
    holdings_count: String(draft.holdings_count),
    rebalance_every_sessions: String(draft.rebalance_every_sessions),
  };
}

export function readResearchDraft(storage: Pick<Storage, "getItem">): ResearchBrowserDraft | null {
  const raw = storage.getItem(BROWSER_DRAFT_STORAGE_KEY);
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw) as ResearchBrowserDraft;
    return value && typeof value === "object" ? value : null;
  } catch {
    return null;
  }
}

export function storeResearchDraft(
  draft: ResearchBrowserDraft,
  storage: Pick<Storage, "getItem" | "setItem">,
  confirmOverwrite: () => boolean,
): boolean {
  if (!confirmDraftReplacement(storage, confirmOverwrite)) {
    return false;
  }
  storage.setItem(BROWSER_DRAFT_STORAGE_KEY, JSON.stringify(draft));
  return true;
}

export function persistResearchDraft(
  draft: ResearchBrowserDraft,
  storage: Pick<Storage, "setItem">,
): void {
  storage.setItem(BROWSER_DRAFT_STORAGE_KEY, JSON.stringify(draft));
}

export function confirmDraftReplacement(
  storage: Pick<Storage, "getItem">,
  confirmOverwrite: () => boolean,
): boolean {
  return storage.getItem(BROWSER_DRAFT_STORAGE_KEY) === null || confirmOverwrite();
}
