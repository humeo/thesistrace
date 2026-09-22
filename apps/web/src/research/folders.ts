import { i18n, interfaceLocale, type InterfaceLocale } from "../i18n";

export function folderDisplayName(folder: { id: string; name: string }, locale: InterfaceLocale = interfaceLocale()): string {
  const t = i18n.getFixedT(locale, "research");
  if (folder.id === "folder_default") return t("defaultFolder");
  if (folder.id === "folder_batch_research") return t("batchFolder");
  return folder.name;
}

export type FolderError = "systemRename" | "systemDelete" | "nonempty" | "notFound" | "invalid" | "unavailable";

export async function folderMutationError(response: Response): Promise<FolderError> {
  if (response.status === 404) return "notFound";
  if (response.status === 422) return "invalid";
  if (response.status !== 409) return "unavailable";
  try {
    const payload = await response.json();
    switch (payload?.detail?.code) {
      case "SYSTEM_FOLDER_RENAME_FORBIDDEN": return "systemRename";
      case "SYSTEM_FOLDER_DELETE_FORBIDDEN": return "systemDelete";
      case "FOLDER_NOT_EMPTY": return "nonempty";
      default: return "unavailable";
    }
  } catch { return "unavailable"; }
}
