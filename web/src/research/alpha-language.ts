import { HighlightStyle, LRLanguage, LanguageSupport, syntaxHighlighting } from "@codemirror/language";
import { styleTags, tags } from "@lezer/highlight";

import { parser } from "./alpha-language-parser";

const alphaParser = parser.configure({
  props: [
    styleTags({
      "FunctionName!": tags.function(tags.variableName),
      "FieldName!": tags.variableName,
      Number: tags.number,
      "UnaryOperator MultiplyOperator AddOperator": tags.arithmeticOperator,
    }),
  ],
});

export const alphaLanguage = LRLanguage.define({
  name: "alpha",
  parser: alphaParser,
  languageData: {
    closeBrackets: { brackets: ["("] },
  },
});

export const alphaHighlightStyle = HighlightStyle.define([
  { tag: tags.function(tags.variableName), class: "cm-alpha-function" },
  { tag: tags.variableName, class: "cm-alpha-field" },
  { tag: tags.number, class: "cm-alpha-number" },
  { tag: tags.arithmeticOperator, class: "cm-alpha-operator" },
]);

export const alphaLanguageExtensions = [
  new LanguageSupport(alphaLanguage),
  syntaxHighlighting(alphaHighlightStyle),
];
