import { autocompletion, type Completion } from "@codemirror/autocomplete";
import { bracketMatching } from "@codemirror/language";
import { setDiagnostics, type Diagnostic as CodeMirrorDiagnostic } from "@codemirror/lint";
import { EditorSelection, EditorState } from "@codemirror/state";
import {
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  placeholder,
} from "@codemirror/view";
import { useEffect, useRef } from "react";

import type { AlphaCatalog } from "../alphaCatalog";
import { alphaLanguageExtensions } from "./alpha-language";
import type { FormulaDiagnostic } from "./diagnostics";
import type { EditorState as StoredEditorState } from "./draft";

const alphaEditorTheme = EditorView.theme({
  "&": {
    height: "100%",
    minHeight: "0",
    color: "var(--ink)",
    backgroundColor: "var(--canvas)",
    font: "14px/1.65 var(--mono)",
  },
  "&.cm-focused": { outline: "0" },
  ".cm-scroller": { height: "100%", overflow: "auto" },
  ".cm-content": { padding: "14px 10px", caretColor: "var(--ink)" },
  ".cm-gutters": {
    minWidth: "36px",
    color: "var(--ink-faint)",
    backgroundColor: "var(--surface-1)",
    borderRightColor: "var(--line)",
  },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 8px 0 6px" },
  ".cm-activeLine": { backgroundColor: "rgb(94 106 210 / .06)" },
  ".cm-activeLineGutter": {
    color: "var(--ink-soft)",
    backgroundColor: "var(--surface-2)",
  },
  ".cm-placeholder": { color: "var(--ink-faint)", fontStyle: "normal" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "rgb(94 106 210 / .28) !important",
  },
  ".cm-alpha-function": { color: "#aab3ff", fontWeight: "500" },
  ".cm-alpha-field": { color: "#8bd5ca", fontWeight: "500" },
  ".cm-alpha-number": { color: "#7cc4ff" },
  ".cm-alpha-operator": { color: "var(--ink-soft)" },
  ".cm-tooltip": {
    color: "var(--ink-muted)",
    backgroundColor: "var(--surface-3)",
    borderColor: "var(--line-strong)",
  },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": {
    color: "var(--ink)",
    backgroundColor: "var(--primary)",
  },
}, { dark: true });

export function AlphaFormulaEditor({
  catalog,
  diagnostics,
  formula,
  selection,
  onChange,
}: {
  catalog: AlphaCatalog;
  diagnostics: FormulaDiagnostic[];
  formula: string;
  selection: StoredEditorState;
  onChange: (formula: string, selection: StoredEditorState) => void;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  const applyingExternalValue = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (host.current === null) return;
    const root = host.current.shadowRoot ?? host.current.attachShadow({ mode: "open" });
    const options: Completion[] = [
      ...catalog.fields.map((field) => ({
        label: field.identifier,
        type: "variable",
        detail: `${field.value_type} · ${field.unit}`,
        info: `${field.description}\nCanonical field: ${field.field_id}`,
      })),
      ...catalog.builtins.map((builtin) => ({
        label: builtin.identifier,
        type: "function",
        detail: `(${builtin.parameters.map((parameter) => parameter.name).join(", ")})`,
        info: [builtin.description, ...builtin.examples, builtin.missing_value_behavior, builtin.numeric_behavior].join("\n"),
      })),
    ];
    const initialAnchor = Math.min(selection.anchor, formula.length);
    const initialHead = Math.min(selection.head, formula.length);
    const state = EditorState.create({
      doc: formula,
      selection: EditorSelection.single(initialAnchor, initialHead),
      extensions: [
        lineNumbers(),
        highlightActiveLine(),
        highlightActiveLineGutter(),
        bracketMatching(),
        alphaLanguageExtensions,
        alphaEditorTheme,
        EditorView.lineWrapping,
        EditorView.contentAttributes.of({ "aria-labelledby": "alpha-formula-title", spellcheck: "false" }),
        placeholder("Start with a field or function"),
        keymap.of([]),
        autocompletion({
          override: [(context) => {
            const token = context.matchBefore(/[A-Za-z_][A-Za-z0-9_]*/);
            if (token === null && !context.explicit) return null;
            return { from: token?.from ?? context.pos, options, validFor: /^[A-Za-z_][A-Za-z0-9_]*$/ };
          }],
        }),
        EditorView.updateListener.of((update) => {
          if (applyingExternalValue.current) return;
          if (!update.docChanged && !update.selectionSet) return;
          const main = update.state.selection.main;
          onChangeRef.current(update.state.doc.toString(), { anchor: main.anchor, head: main.head });
        }),
      ],
    });
    view.current = new EditorView({ root, state, parent: root });
    return () => {
      view.current?.destroy();
      view.current = null;
    };
  }, [catalog]);

  useEffect(() => {
    const editor = view.current;
    if (editor === null || editor.state.doc.toString() === formula) return;
    const anchor = Math.min(selection.anchor, formula.length);
    const head = Math.min(selection.head, formula.length);
    applyingExternalValue.current = true;
    try {
      editor.dispatch({
        changes: { from: 0, to: editor.state.doc.length, insert: formula },
        selection: EditorSelection.single(anchor, head),
      });
    } finally {
      applyingExternalValue.current = false;
    }
  }, [formula, selection.anchor, selection.head]);

  useEffect(() => {
    const editor = view.current;
    if (editor === null) return;
    const maximum = editor.state.doc.length;
    const mapped: CodeMirrorDiagnostic[] = diagnostics.map((diagnostic) => ({
      from: Math.min(diagnostic.range.start.offset, maximum),
      to: Math.min(Math.max(diagnostic.range.end.offset, diagnostic.range.start.offset), maximum),
      severity: diagnostic.severity,
      message: diagnostic.message,
      source: diagnostic.code,
    }));
    editor.dispatch(setDiagnostics(editor.state, mapped));
  }, [diagnostics]);

  return <div aria-label="Alpha formula editor" className="alpha-formula-editor" ref={host} />;
}
