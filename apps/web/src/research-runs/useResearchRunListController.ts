import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { researchFoldersQuery } from "../research/folderResources";
import { coreFetch } from "../auth/coreFetch";
import type { RunError } from "./errors";
import type { ResearchRun } from "./ResearchRunsPage";

export const RESEARCH_RUN_PAGE_SIZE = 20;
export type ResearchKindFilter = "" | ResearchRun["research_kind"];
type ResearchRunList = { items: ResearchRun[]; total_count: number };
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
  const [folderFilter, setFolderFilter] = useState("");
  const [researchKindFilter, setResearchKindFilter] = useState<ResearchKindFilter>("");
  const [pageIndex, setPageIndex] = useState(0);
  const [sort, setSort] = useState<ResearchRunSort>(DEFAULT_RESEARCH_RUN_SORT);
  const [metricFilters, setMetricFilters] = useState<ResearchMetricFilter[]>([]);
  const [search, setSearch] = useState("");
  const folderQuery = useQuery(researchFoldersQuery);
  const path = researchRunListPath({ page: pageIndex + 1, sort, metricFilters, folderId: folderFilter, researchKind: researchKindFilter, search });
  const listQuery = useQuery({
    queryKey: ["workspace", "research-runs", path],
    queryFn: async ({ signal }): Promise<ResearchRunList> => {
      const response = await coreFetch(path, { signal });
      if (!response.ok) throw new Error("ResearchRun unavailable");
      return await response.json() as ResearchRunList;
    },
    enabled: runId === undefined,
    // Runs may change through a detail, Batch or Chat. Keep cached rows visible
    // while revalidating each visit, rather than treating the list as static Data.
    staleTime: 0,
    refetchInterval: query => query.state.status !== "error" && query.state.data?.items.some(item => ["queued", "running", "cancelling"].includes(item.status)) ? 500 : false,
  });
  const items = listQuery.data?.items ?? null;
  const totalCount = listQuery.data?.total_count ?? null;
  const folders = folderQuery.data ?? [];
  const folderError = folderQuery.isError ? "folderError" as const : null;
  const error: RunError | null = listQuery.isError ? { code: "loadError" } : null;
  const loadState: LoadState = listQuery.isLoading ? "loading" : null;

  useEffect(() => {
    if (totalCount === null) return;
    const lastPageIndex = Math.max(0, Math.ceil(totalCount / RESEARCH_RUN_PAGE_SIZE) - 1);
    if (pageIndex > lastPageIndex) setPageIndex(lastPageIndex);
  }, [pageIndex, totalCount]);

  function refresh() { void listQuery.refetch(); }
  function refreshFolders() { void folderQuery.refetch(); }
  function changeSort(value: ResearchRunSort) { setSort(value); setPageIndex(0); }
  function changeFolderFilter(value: string) { setFolderFilter(value); setPageIndex(0); }
  function changeResearchKindFilter(value: ResearchKindFilter) {
    setResearchKindFilter(value); setMetricFilters([]); setSort(DEFAULT_RESEARCH_RUN_SORT); setPageIndex(0);
  }
  function showPreviousPage() { if (pageIndex > 0) setPageIndex(current => current - 1); }
  function showNextPage() {
    if (totalCount !== null && (pageIndex + 1) * RESEARCH_RUN_PAGE_SIZE < totalCount) setPageIndex(current => current + 1);
  }
  function applyMetricFilters(filters: ResearchMetricFilter[]) { setMetricFilters(filters); setPageIndex(0); }
  function applySearch(value: string) { setSearch(value.trim()); setPageIndex(0); }
  return { items, folders, folderFilter, researchKindFilter, pageIndex, sort, metricFilters, search, totalCount, folderError, error, loadState, refresh, refreshFolders, changeSort, changeFolderFilter, changeResearchKindFilter, showPreviousPage, showNextPage, applyMetricFilters, applySearch };
}

export function researchRunListPath({
  page,
  metricFilters = [],
  sort,
  folderId,
  researchKind,
  search = "",
}: {
  page: number;
  metricFilters?: ResearchMetricFilter[];
  sort: ResearchRunSort;
  folderId: string;
  researchKind: ResearchKindFilter;
  search?: string;
}): string {
  const parameters = new URLSearchParams({ page: String(page), page_size: String(RESEARCH_RUN_PAGE_SIZE), sort_by: sort.key, sort_direction: sort.direction });
  if (metricFilters.length) parameters.set("metric_filters", JSON.stringify(metricFilters));
  if (folderId !== "") parameters.set("folder_id", folderId);
  if (researchKind !== "") parameters.set("research_kind", researchKind);
  if (search.trim() !== "") parameters.set("search", search.trim());
  return `/api/research-runs?${parameters.toString()}`;
}

