import { useEffect, useRef, useState } from "react";
import { coreFetch } from "../auth/coreFetch";
import type { RunError } from "./errors";
import type { ResearchRun, ResearchFolderOption } from "./ResearchRunsPage";

export const RESEARCH_RUN_PAGE_SIZE = 20;
export type ResearchKindFilter = "" | ResearchRun["research_kind"];
type ResearchRunList = { items: ResearchRun[]; total_count: number };
type ResearchFolderList = { items: ResearchFolderOption[]; next_cursor: null };
type LoadState = "loading" | "refreshing" | null;
export type ResearchRunSortKey =
  | "created_at"
  | "annualized_excess_return"
  | "sharpe"
  | "maximum_drawdown"
  | "one_session_rank_ic"
  | "five_session_rank_ic"
  | "twenty_session_rank_ic";
export type ResearchRunSortDirection = "ascending" | "descending";
export type ResearchRunSort = {
  key: ResearchRunSortKey;
  direction: ResearchRunSortDirection;
};

export type ResearchMetricFilter = {
  metric: Exclude<ResearchRunSortKey, "created_at">;
  operator: "gt" | "gte" | "lt" | "lte";
  value: number;
};


const DEFAULT_RESEARCH_RUN_SORT: ResearchRunSort = { key: "created_at", direction: "descending" };

/** Owns server paging, filtering and ordering; pauses list reads while a detail is open. */
export function useResearchRunListController(runId: string | undefined) {
  const [items, setItems] = useState<ResearchRun[] | null>(null);
  const [folders, setFolders] = useState<ResearchFolderOption[]>([]);
  const [folderFilter, setFolderFilter] = useState("");
  const [researchKindFilter, setResearchKindFilter] = useState<ResearchKindFilter>("");
  const [pageIndex, setPageIndex] = useState(0);
  const [sort, setSort] = useState<ResearchRunSort>(DEFAULT_RESEARCH_RUN_SORT);
  const [metricFilters, setMetricFilters] = useState<ResearchMetricFilter[]>([]);
  const [totalCount, setTotalCount] = useState<number | null>(null);
  const [folderError, setFolderError] = useState<"folderError" | null>(null);
  const [error, setError] = useState<RunError | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const [folderRefreshGeneration, setFolderRefreshGeneration] = useState(0);
  const loadGeneration = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    setFolderError(null);
    void coreFetch("/api/research-folders", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Research Folders unavailable");
        const payload = (await response.json()) as ResearchFolderList;
        setFolders(payload.items);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setFolderError("folderError");
      });
    return () => controller.abort();
  }, [folderRefreshGeneration]);

  useEffect(() => {
    if (runId !== undefined) return;
    const controller = new AbortController();
    const generation = ++loadGeneration.current;
    let timeout: number | undefined;
    setError(null);
    setLoadState(items === null ? "loading" : "refreshing");
    const path = researchRunListPath({
      page: pageIndex + 1,
      sort,
      metricFilters,
      folderId: folderFilter,
      researchKind: researchKindFilter,
    });

    async function load(polling = false) {
      try {
        const response = await coreFetch(path, { signal: controller.signal });
        if (!response.ok) throw new Error("ResearchRun unavailable");
        if (generation !== loadGeneration.current) return;
        const payload = (await response.json()) as ResearchRunList;
        const nextItems = payload.items;
        if (generation !== loadGeneration.current) return;
        setItems(nextItems);
        setTotalCount(payload.total_count);
        const lastPageIndex = Math.max(0, Math.ceil(payload.total_count / RESEARCH_RUN_PAGE_SIZE) - 1);
        if (pageIndex > lastPageIndex) setPageIndex(lastPageIndex);
        if (nextItems.some((item) => ["queued", "running", "cancelling"].includes(item.status))) {
          timeout = window.setTimeout(() => void load(true), 500);
        }
        if (!polling) setLoadState(null);
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        if (generation !== loadGeneration.current) return;
        setLoadState(null);
        setError({ code: "loadError" });
      }
    }

    void load();
    return () => {
      if (generation === loadGeneration.current) loadGeneration.current += 1;
      if (timeout !== undefined) window.clearTimeout(timeout);
      controller.abort();
    };
  }, [pageIndex, folderFilter, refreshGeneration, researchKindFilter, runId, sort, metricFilters]);

  function refresh() {
    setRefreshGeneration((generation) => generation + 1);
  }

  function refreshFolders() {
    setFolderRefreshGeneration((generation) => generation + 1);
  }

  function resetListPage(): void {
    setItems([]);
    setLoadState("refreshing");
    setPageIndex(0);
    setTotalCount(null);
  }

  function changeSort(value: ResearchRunSort): void {
    setSort(value);
    resetListPage();
  }

  function changeFolderFilter(value: string): void {
    setFolderFilter(value);
    resetListPage();
  }

  function changeResearchKindFilter(value: ResearchKindFilter): void {
    setResearchKindFilter(value);
    setMetricFilters([]);
    setSort(DEFAULT_RESEARCH_RUN_SORT);
    resetListPage();
  }

  function showPreviousPage(): void {
    if (pageIndex === 0) return;
    setItems([]);
    setLoadState("refreshing");
    setPageIndex((current) => current - 1);
  }

  function showNextPage(): void {
    if (totalCount === null || (pageIndex + 1) * RESEARCH_RUN_PAGE_SIZE >= totalCount) return;
    setItems([]);
    setLoadState("refreshing");
    setPageIndex((current) => current + 1);
  }


  function applyMetricFilters(filters: ResearchMetricFilter[]) {
    setMetricFilters(filters);
    resetListPage();
  }
  return { items, folders, folderFilter, researchKindFilter, pageIndex, sort, metricFilters, totalCount, folderError, error, loadState, refresh, refreshFolders, changeSort, changeFolderFilter, changeResearchKindFilter, showPreviousPage, showNextPage, applyMetricFilters };
}

export function researchRunListPath({
  page,
  metricFilters = [],
  sort,
  folderId,
  researchKind,
}: {
  page: number;
  metricFilters?: ResearchMetricFilter[];
  sort: ResearchRunSort;
  folderId: string;
  researchKind: ResearchKindFilter;
}): string {
  const parameters = new URLSearchParams({ page: String(page), page_size: String(RESEARCH_RUN_PAGE_SIZE), sort_by: sort.key, sort_direction: sort.direction });
  if (metricFilters.length) parameters.set("metric_filters", JSON.stringify(metricFilters));
  if (folderId !== "") parameters.set("folder_id", folderId);
  if (researchKind !== "") parameters.set("research_kind", researchKind);
  return `/api/research-runs?${parameters.toString()}`;
}

