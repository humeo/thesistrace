/** Public historical identity, independent of the current startup Catalog. */
export function readRunSelection(value) {
  if (value === null || typeof value !== "object"
    || typeof value.modelKey !== "string" || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(value.modelKey)
    || typeof value.providerModelId !== "string" || value.providerModelId.length < 1 || value.providerModelId.length > 200
    || !["none", "minimal", "low", "medium", "high", "xhigh", "max"].includes(value.reasoningEffort)) return null;
  return { modelKey: value.modelKey, providerModelId: value.providerModelId, reasoningEffort: value.reasoningEffort };
}
