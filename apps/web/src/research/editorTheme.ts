import { EditorView } from "@codemirror/view";

/** Shared light treatment for formula and Python CodeMirror surfaces. */
export const researchEditorTheme = EditorView.theme({
  "&": {
    height: "100%",
    minHeight: "0",
    color: "var(--ink)",
    backgroundColor: "var(--surface-1)",
    font: "14px/1.65 var(--mono)",
  },
  "&.cm-focused": { outline: "0" },
  ".cm-scroller": { height: "100%", overflow: "auto" },
  ".cm-content": { padding: "14px 12px", caretColor: "var(--ink)" },
  ".cm-cursor": { borderLeftColor: "var(--primary)" },
  ".cm-gutters": {
    minWidth: "36px",
    color: "var(--ink-soft)",
    backgroundColor: "var(--surface-2)",
    borderRightColor: "var(--line)",
  },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 8px 0 6px" },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--primary) 5%, var(--surface-1))" },
  ".cm-activeLineGutter": { color: "var(--ink-muted)", backgroundColor: "var(--surface-2)" },
  ".cm-placeholder": { color: "var(--ink-soft)", fontStyle: "normal" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground, ::selection": {
    backgroundColor: "color-mix(in srgb, var(--primary) 22%, var(--surface-1)) !important",
  },
  ".cm-alpha-function": { color: "var(--syntax-function)", fontWeight: "500" },
  ".cm-alpha-field": { color: "var(--syntax-field)", fontWeight: "500" },
  ".cm-alpha-number": { color: "var(--syntax-number)" },
  ".cm-alpha-operator": { color: "var(--ink-muted)" },
  ".cm-tooltip": {
    color: "var(--ink-muted)",
    backgroundColor: "var(--surface-1)",
    borderColor: "var(--line-strong)",
    boxShadow: "0 12px 32px rgb(31 31 31 / .12)",
  },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": {
    color: "var(--ink)",
    backgroundColor: "var(--surface-2)",
  },
  ".cm-diagnostic": { color: "var(--ink)", backgroundColor: "var(--surface-1)" },
  ".cm-diagnostic-error": { borderLeftColor: "var(--danger)" },
  ".cm-lintRange-error": { backgroundImage: "none", borderBottom: "2px solid var(--danger)" },
}, { dark: false });
