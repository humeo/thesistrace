import { autocompletion, completionStatus, startCompletion, type Completion } from "@codemirror/autocomplete";
import { history, historyKeymap } from "@codemirror/commands";
import { bracketMatching } from "@codemirror/language";
import { setDiagnostics, type Diagnostic as CodeMirrorDiagnostic } from "@codemirror/lint";
import { Compartment, EditorSelection, EditorState } from "@codemirror/state";
import {
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  placeholder,
} from "@codemirror/view";
import { useEffect, useImperativeHandle, useRef, type Ref } from "react";

import type { AlphaCatalog } from "../alphaCatalog";
import { i18n, interfaceLocale, useTranslation, type InterfaceLocale } from "../i18n";
import { builtinDisplay, catalogLabel, fieldDisplay } from "../i18n/catalog";
import { alphaLanguageExtensions } from "./alpha-language";
import { formatFormulaDiagnostic, type FormulaDiagnostic } from "./diagnostics";
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

export type AlphaFormulaEditorHandle = { focus: () => void };

export function AlphaFormulaEditor({
  ref,
  catalog,
  context = "signal",
  diagnostics,
  formula,
  selection,
  onChange,
}: {
  ref?: Ref<AlphaFormulaEditorHandle>;
  catalog: AlphaCatalog;
  context?: "signal" | "exposure";
  diagnostics: FormulaDiagnostic[];
  formula: string;
  selection: StoredEditorState;
  onChange: (formula: string, selection: StoredEditorState) => void;
}) {
  const { t } = useTranslation("editor");
  const locale = interfaceLocale();
  const host = useRef<HTMLDivElement | null>(null);
  const view = useRef<EditorView | null>(null);
  const presentation = useRef(new Compartment());
  const presentationLocale = useRef<InterfaceLocale | null>(null);
  useImperativeHandle(ref, () => ({ focus: () => view.current?.focus() }), []);
  const applyingExternalValue = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    if (host.current === null) return;
    const root = host.current.shadowRoot ?? host.current.attachShadow({ mode: "open" });
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
        history(),
        keymap.of(historyKeymap),
        presentation.current.of(editorPresentation(catalog, context, interfaceLocale())),
        EditorView.updateListener.of((update) => {
          if (applyingExternalValue.current) return;
          if (!update.docChanged && !update.selectionSet) return;
          const main = update.state.selection.main;
          onChangeRef.current(update.state.doc.toString(), { anchor: main.anchor, head: main.head });
        }),
      ],
    });
    view.current = new EditorView({ root, state, parent: root });
    presentationLocale.current = interfaceLocale();
    return () => {
      view.current?.destroy();
      view.current = null;
    };
  }, [catalog, context]);

  useEffect(() => {
    const editor = view.current;
    if (editor === null || presentationLocale.current === locale) return;
    const completing = completionStatus(editor.state) !== null;
    editor.dispatch({ effects: presentation.current.reconfigure(editorPresentation(catalog, context, locale)) });
    presentationLocale.current = locale;
    if (completing) startCompletion(editor);
  }, [catalog, context, locale]);

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
    // Core ranges count Unicode code points; CodeMirror positions count UTF-16 units.
    const source = Array.from(editor.state.doc.toString());
    const position = (offset: number) => source.slice(0, Math.max(0, offset)).join("").length;
    const mapped: CodeMirrorDiagnostic[] = diagnostics.map((diagnostic) => ({
      from: Math.min(position(diagnostic.range.start.offset), maximum),
      to: Math.min(position(Math.max(diagnostic.range.end.offset, diagnostic.range.start.offset)), maximum),
      severity: diagnostic.severity,
      message: formatFormulaDiagnostic(diagnostic, locale),
      source: diagnostic.code,
    }));
    editor.dispatch(setDiagnostics(editor.state, mapped));
  }, [diagnostics, locale, formula]);

  return <div aria-label={t(context === "signal" ? "formulaEditor" : "exposureEditor")} className="alpha-formula-editor" ref={host} />;
}

function editorPresentation(catalog: AlphaCatalog, context: "signal" | "exposure", locale: InterfaceLocale) {
  const t = i18n.getFixedT(locale, "editor");
  const options: Completion[] = [
    ...["and", "or", "not"].map((label) => ({ label, type: "keyword", detail: t("booleanOperator") })),
    ...catalog.industries.map((industry) => ({
      label: String(industry.code), type: "constant",
      detail: `SW2021 L1 · ${catalogLabel("industries", industry.code, locale)}`, info: t("industryHelp"),
    })),
    ...(context === "signal" ? catalog.fields : []).map((field) => ({
      label: field.identifier, type: "variable", detail: `${t("numericSeries")} · ${catalogLabel("units", field.unit, locale)}`,
      info: `${fieldDisplay(field.field_id, locale).description}\n${t("canonicalField", { id: field.field_id })}`,
    })),
    ...catalog.builtins.filter((builtin) => context === "signal" || builtin.result_type !== "numeric_series").map((builtin) => {
      const display = builtinDisplay(builtin.identifier, locale);
      return {
        label: builtin.identifier, type: "function", detail: `(${builtin.parameters.map((parameter) => parameter.name).join(", ")})`,
        info: [display.description, ...builtin.examples, display.missing, display.numeric].join("\n"),
      };
    }),
  ];
  return [
    EditorState.phrases.of(t("phrases", { returnObjects: true })),
    EditorView.contentAttributes.of({ "aria-label": t(context === "signal" ? "formula" : "exposure"), spellcheck: "false" }),
    placeholder(t(context === "signal" ? "placeholder" : "exposurePlaceholder")),
    autocompletion({ override: [(completion) => {
      const token = completion.matchBefore(/[A-Za-z_][A-Za-z0-9_]*|[0-9]+/);
      if (token === null && !completion.explicit) return null;
      return { from: token?.from ?? completion.pos, options, validFor: /^(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+)$/ };
    }] }),
  ];
}
