/** Product answer envelope. Mastra receives the formatted text, not this object. */
export function isChatAnswer(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === 2
    && typeof value.text === "string"
    && Array.isArray(value.selections)
    && value.selections.length <= 20
    && value.selections.every((label) => typeof label === "string"
      && label.trim().length > 0 && new TextEncoder().encode(label).byteLength <= 200)
    && new Set(value.selections).size === value.selections.length
    && (value.selections.length > 0 || value.text.trim().length > 0);
}

export function formatChatAnswer(answer) {
  return [answer.selections.join(", "), answer.text.trim()].filter(Boolean).join("\n\n");
}
