# ClearView PDF (prototype)

A local, reading-first PDF viewer built with Qt and MuPDF. No Electron, accounts,
ads, telemetry, cloud sync, or background service.

## Run the Windows build

Extract the whole ZIP, then double-click **ClearViewPDF.exe** inside the
**ClearViewPDF** folder. Keep the other files beside it; they are the app's
runtime and must not be moved away from the exe.

## Reading features

- Continuous scrolling and lazy rendering for large documents
- Middle-button auto-scroll: drag farther from the click point to scroll faster,
  return near the point to pause, and release to stop
- Compact, centered page, zoom, and fit controls directly above the document,
  with editable page-number and zoom-percentage fields; typed numeric zoom
  clamps to 20–500%, while nonnumeric input is left untouched
- Zoom, fit width (`⟷`), fit height (`↕`), actual size, and full screen
- The reader sidebar stays docked without floating or restore controls
- Text-only File/Edit/View/Go/Help menus
- Automatic light/dark chrome that follows the Windows theme; PDF colors stay unchanged
- Reversible 90-degree rotation from the View menu, shortcuts, or page right-click menu
- Page thumbnails, document outline, local bookmarks, recent files
- Remembers page, zoom, fit mode, and rotation per document
- Text selection/copy, drag-and-drop, password-protected PDFs
- Embedded web links and printed `http://…`, `https://…`, or `www.…` addresses open
  through the operating system's default browser; no browser is hardcoded
- Printing

Rotation shortcuts: **Ctrl++ / Ctrl+=** clockwise, **Ctrl+Shift++ /
Ctrl+Shift+=** counterclockwise, and **Ctrl+Shift+0** to reset. Zoom uses
**Ctrl+Up / Ctrl+Down** or the toolbar controls. **Ctrl+2** fits width and
**Ctrl+0** fits height. **Ctrl+W** closes the current document without quitting
the reader.

## Search

- Full-document highlighted matches with clickable page/snippet results
- Next/previous with wraparound (F3 / Shift+F3)
- Exact phrase, any-word, and all-word modes
- Match case, whole-words-only, bookmarks, and comments options
- **Fuzzy** combines spelling-tolerant text matching and local semantic matching
  in one mode; words of four characters or fewer stay strict for spelling edits
- Natural-language searches such as `talks about GQA` run in the same Fuzzy mode
- Quoted proximity expressions: `"X" near "Y"` (up to 50 intervening words) or
  `"X" near/20 "Y"` (custom limit). Unquoted `near` is ordinary search text.
  With Fuzzy enabled, quoted `near` finds conceptual operand matches and then
  independently enforces their actual word positions; embedding similarity alone
  cannot satisfy the distance constraint.
- Precise text/fuzzy hits are retained first, then non-overlapping semantic
  passages are added without returning duplicates for the same text.

The semantic portion of Fuzzy search uses a local FastEmbed/ONNX model. The first
Fuzzy search downloads approximately **67 MB** of model files from Hugging Face.
Document passages are not uploaded. After that download, searches run locally. The
two-resolution document index is reused across queries while the app remains
open and is rebuilt after an app restart.

Not yet implemented: folder-wide search, embedded-attachment search, stemming,
result export, editing, form filling, or digital signatures.

## Run from source (Windows)

Requires 64-bit Python 3.10 or later:

```powershell
py -m pip install -e ".[semantic]"
py -m clearview_pdf
```

You can pass a PDF path: `py -m clearview_pdf book.pdf`.

## Rebuild the Windows executable

From a Windows checkout with Python 3.10 available through `py`:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

Build output: `dist\ClearViewPDF\ClearViewPDF.exe`. Keep the entire
`dist\ClearViewPDF` folder together; the exe requires its adjacent runtime files.

## Tests

```bash
python -m pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen python -m pytest tests/ -q   # Linux/headless
python -m pytest tests/ -q                              # Windows
```
