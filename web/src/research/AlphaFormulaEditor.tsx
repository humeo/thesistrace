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

const editorStylesheetUrl = new URL("./alpha-formula-editor.css?no-inline", import.meta.url).href;

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
    if (root.querySelector("link[data-alpha-editor-styles]") === null) {
      const stylesheet = document.createElement("link");
      stylesheet.dataset.alphaEditorStyles = "";
      stylesheet.href = editorStylesheetUrl;
      stylesheet.rel = "stylesheet";
      root.append(stylesheet);
    }
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
