import { queryOptions } from "@tanstack/react-query";
import { coreFetch } from "../auth/coreFetch";

export type ResearchFolder = {
  id: string;
  name: string;
  is_default: boolean;
  created_at: string;
};

export const researchFoldersQuery = queryOptions({
  queryKey: ["workspace", "research-folders"],
  queryFn: async ({ signal }): Promise<ResearchFolder[]> => {
    const response = await coreFetch("/api/research-folders", { signal });
    if (!response.ok) throw new Error("Research Folders unavailable");
    const { items } = await response.json() as { items: ResearchFolder[]; next_cursor: null };
    if (items.filter(folder => folder.is_default).length !== 1) throw new Error("Default Folder unavailable");
    return items;
  },
});
