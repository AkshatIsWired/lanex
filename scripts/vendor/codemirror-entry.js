// Entry for lanex/server/static/vendor/codemirror.js: the CodeMirror 6 pieces
// the RTL IDE's editor uses, bundled into one ES module that ships with LanEx
// (no network at run time). Rebuild with scripts/vendor.sh.
export { EditorState, Compartment, StateEffect, StateField, EditorSelection, Prec } from "@codemirror/state";
export {
  EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection,
  dropCursor, rectangularSelection, crosshairCursor, highlightSpecialChars, hoverTooltip, Decoration,
  ViewPlugin, placeholder, scrollPastEnd,
} from "@codemirror/view";
export {
  history, defaultKeymap, historyKeymap, indentWithTab, toggleComment, selectLine, cursorLineDown,
  moveLineUp, moveLineDown, copyLineDown, deleteLine, insertNewlineAndIndent,
} from "@codemirror/commands";
export {
  foldGutter, foldKeymap, indentOnInput, bracketMatching, syntaxHighlighting, HighlightStyle,
  StreamLanguage, indentUnit, foldService, codeFolding, syntaxTree,
} from "@codemirror/language";
export { tags } from "@lezer/highlight";
export {
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap, snippetCompletion,
  completeFromList, completeAnyWord, startCompletion,
} from "@codemirror/autocomplete";
export {
  searchKeymap, highlightSelectionMatches, openSearchPanel, closeSearchPanel, search, gotoLine,
} from "@codemirror/search";
export { setDiagnostics, lintGutter, forEachDiagnostic, lintKeymap, nextDiagnostic } from "@codemirror/lint";
export { verilog } from "@codemirror/legacy-modes/mode/verilog";
export { tcl } from "@codemirror/legacy-modes/mode/tcl";
export { yaml } from "@codemirror/legacy-modes/mode/yaml";
export { json } from "@codemirror/lang-json";
