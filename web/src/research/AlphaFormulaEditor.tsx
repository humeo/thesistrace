import { autocompletion, type Completion } from "@codemirror/autocomplete";
import { bracketMatching } from "@codemirror/language";
import { setDiagnostics, type Diagnostic as CodeMirrorDiagnostic } from "@codemirror/lint";
import { EditorSelection, EditorState, RangeSetBuilder, StateField, type Extension } from "@codemirror/state";
import { Decoration, EditorView, keymap, lineNumbers, type DecorationSet } from "@codemirror/view";
import { useEffect, useRef } from "react";

import type { FormulaDiagnostic } from "./diagnostics";
import type { EditorState as StoredEditorState } from "./draft";

export type AlphaCatalog = {
  fields: Array<{
    identifier: string;
    field_id: string;
    value_type: "numeric_series";
    description: string;
    unit: string;
    family_id: string;
    availability: string;
    report_period_selection: string;
    applicable_company_types: string[];
    missingness: string;
    example: string;
  }>;
  builtins: Array<{
    identifier: string;
    parameters: Array<{ name: string; value_type: string; minimum: number | null; maximum: number | null }>;
    result_type: string;
    description: string;
    examples: string[];
    missing_value_behavior: string;
    numeric_behavior: string;
  }>;
};

type AlphaSyntaxKind = "field" | "function" | "number" | "operator";
export type AlphaSyntaxToken = { from: number; to: number; kind: AlphaSyntaxKind };

export function alphaSyntaxTokens(formula: string, catalog: AlphaCatalog): AlphaSyntaxToken[] {
  const fields = new Set(catalog.fields.map((field) => field.identifier));
  const builtins = new Set(catalog.builtins.map((builtin) => builtin.identifier));
  const tokens: AlphaSyntaxToken[] = [];
  const matcher = /[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[()+\-*/,]/g;

  for (const match of formula.matchAll(matcher)) {
    const from = match.index;
    const value = match[0];
    const to = from + value.length;
    let kind: AlphaSyntaxKind | null = null;
    if (/^\d/.test(value)) kind = "number";
    else if (/^[()+\-*/,]$/.test(value)) kind = "operator";
    else if (builtins.has(value) || formula.slice(to).trimStart().startsWith("(")) kind = "function";
    else if (fields.has(value)) kind = "field";
    if (kind !== null) tokens.push({ from, to, kind });
  }
  return tokens;
}

function alphaSyntaxHighlighting(catalog: AlphaCatalog): Extension {
  const build = (formula: string): DecorationSet => {
    const ranges = new RangeSetBuilder<Decoration>();
    for (const token of alphaSyntaxTokens(formula, catalog)) {
      ranges.add(token.from, token.to, Decoration.mark({ class: `cm-alpha-${token.kind}` }));
    }
    return ranges.finish();
  };
  return StateField.define<DecorationSet>({
    create: (state) => build(state.doc.toString()),
    update: (decorations, transaction) => transaction.docChanged
      ? build(transaction.state.doc.toString())
      : decorations,
    provide: (field) => EditorView.decorations.from(field),
  });
}

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
        bracketMatching(),
        alphaSyntaxHighlighting(catalog),
        EditorView.lineWrapping,
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
    view.current = new EditorView({ state, parent: host.current });
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
