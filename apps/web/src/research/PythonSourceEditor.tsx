import { autocompletion, closeBrackets, closeBracketsKeymap, completionKeymap, type CompletionContext } from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { python, pythonLanguage } from "@codemirror/lang-python";
import { bracketMatching, HighlightStyle, indentOnInput, indentUnit, syntaxHighlighting } from "@codemirror/language";
import { setDiagnostics } from "@codemirror/lint";
import { Compartment, EditorState, Transaction } from "@codemirror/state";
import { drawSelection, EditorView, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { useEffect, useImperativeHandle, useRef, type Ref } from "react";

import { i18n, interfaceLocale } from "../i18n";
import { researchEditorTheme } from "./editorTheme";

const pythonHighlighting = syntaxHighlighting(HighlightStyle.define([
  { tag: [tags.keyword, tags.operatorKeyword], color: "var(--syntax-function)", fontWeight: "600" },
  { tag: [tags.function(tags.variableName), tags.definition(tags.variableName)], color: "var(--syntax-function)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--syntax-field)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--syntax-number)" },
  { tag: tags.comment, color: "var(--ink-soft)", fontStyle: "italic" },
  { tag: tags.operator, color: "var(--ink-muted)" },
]));

/** The owning module keeps this mounted while hidden, preserving selection and history. */
export type PythonSourceEditorHandle = { insertAtSelection: (text: string) => void; focus: () => void };

export function PythonSourceEditor({ id, label, describedBy, source, error, errorLine, onChange, editorRef }: {
  editorRef?: Ref<PythonSourceEditorHandle>;
  id: string;
  label: string;
  describedBy: string;
  source: string;
  error?: string;
  errorLine?: number | null;
  onChange: (source: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const presentation = useRef(new Compartment());
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const applyingExternal = useRef(false);
  const locale = interfaceLocale();
  useImperativeHandle(editorRef, () => ({
    insertAtSelection(text) {
      const editor = view.current;
      if (editor) editor.dispatch(editor.state.replaceSelection(text), { userEvent: "input" });
    },
    focus() { view.current?.focus(); },
  }), []);

  useEffect(() => {
    if (!host.current) return;
    const editor = new EditorView({
      parent: host.current,
      state: EditorState.create({ doc: source, extensions: [
        python(), pythonHighlighting, researchEditorTheme, lineNumbers(), drawSelection(),
        highlightActiveLine(), highlightActiveLineGutter(), bracketMatching(), indentOnInput(),
        indentUnit.of("    "), closeBrackets(), autocompletion(), pythonLanguage.data.of({ autocomplete: (context: CompletionContext) => {
          const word = context.matchBefore(/[\w.]+/);
          if (!word || (!context.explicit && word.from === word.to)) return null;
          return { from: word.from, options: [
            "Strategy", "UniverseSelection", "Alpha", "PortfolioConstruction", "RiskManagement",
            "data.close_prices", "data.history", "data.candidates", "data.session",
            "data.completed_sessions", "data.candidate_details", "data.framework",
            "account.positions", "account.cash_cny", "account.fills", "account.rejections",
            "account.post_open_net_nav_cny", "account.close_risk_nav_cny",
            "self.target_weights", "self.limit_positions", "self.limit_exposure", "self.state",
            "self.increase_to_weights", "self.reduce_exposure", "self.with_limits",
            "self.select", "self.signals", "self.replace", "on_close",
          ].map(label => ({ label, type: "property" })) };
        } }), history(),
        keymap.of([...closeBracketsKeymap, ...completionKeymap, ...defaultKeymap, ...historyKeymap]),
        presentation.current.of([]),
        EditorView.updateListener.of(update => {
          if (update.docChanged && !applyingExternal.current) onChangeRef.current(update.state.doc.toString());
        }),
      ] }),
    });
    view.current = editor;
    return () => { editor.destroy(); view.current = null; };
  }, []);

  useEffect(() => {
    const editor = view.current;
    if (!editor || editor.state.doc.toString() === source) return;
    applyingExternal.current = true;
    try {
      editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: source },
        annotations: Transaction.addToHistory.of(false) });
    } finally { applyingExternal.current = false; }
  }, [source]);

  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    editor.dispatch({ effects: presentation.current.reconfigure([
      EditorState.phrases.of(i18n.getFixedT(locale, "editor")("phrases", { returnObjects: true })),
      EditorView.contentAttributes.of({ id, "aria-label": label, "aria-describedby": describedBy,
        "aria-invalid": String(Boolean(error)), spellcheck: "false", autocapitalize: "off", autocorrect: "off" }),
    ]) });
    const line = errorLine && errorLine <= editor.state.doc.lines ? editor.state.doc.line(errorLine) : null;
    editor.dispatch(setDiagnostics(editor.state, error ? [{ from: line?.from ?? 0,
      to: line?.to ?? 0, severity: "error", message: error }] : []));
  }, [id, label, describedBy, error, errorLine, locale, source]);

  return <div ref={host} className="h-[480px] min-w-0 overflow-hidden rounded-md border border-input bg-card focus-within:ring-2 focus-within:ring-ring/30" />;
}
