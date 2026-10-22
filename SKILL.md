---
name: codesys-sync
description: Two-way sync between binary CODESYS projects (.project/.library) and plain-text source — tree export of every Application object to *.st plus a _project_info.txt summary; import via structure_ops.txt structure operations (create/rename/delete/move, task assignment, add library; renames auto-rewrite references project-wide) and per-object text write-back with automatic backup and write-back verification; also headless build with a structured report. CODESYS install is chosen from the project's last-saved compiler version (not "newest installed"). Use when a repo needs codesys-sync export/import, the user says "export project", "import ST", "build PLC project", "structure_ops", "codesys-sync", 导出工程 / 导入 ST / 编译工程, or for any CODESYS repo following the projects/ + src/plc/ layout.
---

# CODESYS project import/export/build

CODESYS `.project` / `.library` files are binary: git cannot track their contents and AI agents cannot read or write them. This tool converts between the binary project and text source via the official **CODESYS Scripting Engine** (IronPython 2.7, `CODESYS.exe --runscript`, headless):

- **Export** (project → text): mirrors the directory tree starting at each Application; textual objects are written as `Application/**/*.st` (POU body = `<Name>.st`; methods/properties/actions live in a same-named sibling directory `<Name>/`). Also generates `_folders.txt` (folder list incl. empty folders), `_index.txt` (relative path ↔ project PATH), `_project_info.txt` (project properties/devices/tasks/libraries summary), and `_full_export.xml` (PLCopenXML incl. graphic languages; can be re-imported to restore a project).
- **Import** (text → project): first executes `structure_ops.txt` structure operations (create objects of all kinds, rename, move, delete, assign to task, add library), then writes back each `.st` by its `// PATH:` header. **Backs up automatically first, verifies every write-back, saves only when something actually changed.** Renames rewrite references across all project texts at word boundaries (3.5.17's `rename()` itself does not touch references). DELETE has a built-in zero-reference check (including task program call instances).
- **Build** (headless): runs `build()` on a copy of the project; the report starts with `errors=`/`warnings=` counts — for the "edit text → import → build" self-check loop.

## Important rules (read before changing anything)

1. **Close the project in the IDE before importing / applying patches**; export reads a copy and works even while the IDE has the project open.
2. **Old flat layout** (`pous/NNN_*.txt`) fails on import — re-export with the current export to migrate.
3. **Version guard**: an older IDE opening a newer project silently reads 0 objects — the script detects this and FATALs; switch to a matching CODESYS installation (`-CodesysExe`/`-Profile`).
4. **After hand-editing the project in the IDE, export before importing** (the timestamp guard refuses otherwise; use `-Force` only when you are sure nothing was hand-edited).
5. **Rename**: preferably rename the file in the export tree + update its `// PATH:` header — the importer recognizes it via `// GUID:`; or write a RENAME op. Both rewrite references project-wide — **always run a build afterwards to confirm**.
6. When `--runscript` hits FATAL, the CODESYS exit code is usually still 0 — judge success by `FATAL`/`ABORTED` in the log and by `errors=` in the build report, never by the exit code.
7. With several CODESYS versions installed (e.g. SP17 + SP22), auto-detection **matches the project's last-saved compiler version** (`project_settings.get_compilerversion`, cached in `_project_info.txt` as `compiler_version:`). It does **not** pick the newest install — opening an SP17 project with SP22 would silently upgrade it. Only when the version cannot be determined does it fall back to the newest install (with a WARN). Pin an install via `-CodesysExe`/`-Profile` only when you intentionally want a different one.

## Interface

```powershell
# Export (reads a copy of the project under projects/; safe while the IDE has it open)
powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\export.ps1 -Root <repo> [-Select <number>]

# Import (writes the REAL project file — close that project in the IDE first!)
powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\import.ps1 -Root <repo> [-Select <number>] [-Yes] [-Dir <path keyword>] [-Sync] [-Force] [-VerifyBuild] [-VerifyQuick]

# Verify (read-only: text tree vs project consistency; missing/drift/rename candidates)
powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\verify.ps1 -Root <repo> [-Select <number>]

# Build (reads a copy of the project under projects/; safe while the IDE has it open; report defaults to <repo>\.codesys-sync\build_report.txt)
powershell -NoProfile -ExecutionPolicy Bypass -File <codesys-sync>\build.ps1 -Root <repo> [-Select <number>] [-Out <report path>]
```

| Parameter | Meaning |
|---|---|
| `-Root` | Target repo root (required); must contain `projects/` |
| `-Select` | Project number (menu order); non-interactive. Without it an interactive menu appears |
| `-SrcRoot` | Export/import only: text source root (relative to repo root), default `src/plc` |
| `-Yes` / `-Dir` | Import only: skip confirmation / filter by path keyword |
| `-Sync` | Import only: structure sync — objects new in the export tree are created, stale objects in the project are deleted (zero-reference protection; skipped with a warning when referenced) |
| `-Force` | Import only: skip the "project newer than last export" guard (use only when sure no IDE hand-edits are at risk) |
| `-VerifyBuild` | Import only: run a full build after a successful import (exit 0 only when errors=0) |
| `-VerifyQuick` | Import only: run a precompile quick check (`check_all_pool_objects`, faster than a full build; `-VerifyBuild` wins if both are given) |
| `-Out` | Build only: report output path |
| `-CodesysExe` / `-Profile` | CODESYS installation override. Defaults to auto-detection: the install matching the project's **last-saved** compiler version (see below) |

**CODESYS install resolution order**: parameters → environment variables `CODESYS_SYNC_EXE` / `CODESYS_SYNC_PROFILE` → **match the project's last-saved compiler version** to the installed `CODESYS 3.5*` (version cached in `_project_info.txt` `compiler_version:`; if missing, a no-save probe reads `get_compilerversion()`). Profile taken from the chosen install's `CODESYS\Profiles\*.profile.xml`.

A repo may hold thin `.bat` double-click entry points, equivalent to calling these scripts with `-Root`.

## Target repo layout (default; adjust with -SrcRoot)

| Location | Contents |
|---|---|
| `<repo>/projects/` | Real `.project`/`.library` files (**not committed**; gitignore); subdirectories supported and mirrored in the export; `.library` exports to `<SrcRoot>/reference/` |
| `<repo>/<SrcRoot>/<project name>/` | Exported text (**committed**): `Application/**/*.st`, `structure_ops.txt`, `_folders.txt`, `_index.txt`, `_project_info.txt`, `_full_export.xml` |
| `<repo>/.codesys-sync/` | Tool working area (**not committed**; gitignore): project copies, target files, run bats, logs (`<project>_export_log.txt` / `_import_log.txt` / `_build_report.txt`), timestamp stamps `*_lastexport.txt` |

Project name → directory name rule: whitespace and parentheses become `-`. Name the project file with the directory name you want; when renaming an export directory you must rename the project file under `projects/` as well, otherwise the next export creates a new directory under the old name.

Further facts:

- `.projectarchive` is a zip: extract the `.project` inside into `projects/` (keep subdirectories) and export normally.
- `_full_export.xml` depends on the CODESYS device descriptions installed locally; with missing device descriptions the XML export fails while `.st` export is unaffected; the library list in `_project_info.txt` is parsed from that XML and is empty when the XML fails.
- After editing the project in the IDE (Ctrl+S), re-running export refreshes the export directory.

## .st file format

```
// PATH: Device/Plc Logic/Application/DUTs/AxisInfo   <- full object path (authoritative for import)
// GUID: <object instance fingerprint>                <- used to auto-detect renames
// TYPE: <object type GUID>
// ===== DECLARATION =====
<declaration text>
// ===== IMPLEMENTATION =====
<implementation text>
```

- The relative file path must match the PATH (counted from the Application node); import verifies this and errors on mismatch.
- The POU body is `<Name>.st`; its methods/properties/actions are `<Name>/<child>.st` (parent file + same-named directory coexist).
- Encoding UTF-8 (BOM or not); line-ending differences are normalized on the import side.

**Hard rules (will FATAL or silently skip if ignored)**

1. `// PATH:` is the **first** line and must be the **full** object path (`Device/Plc Logic/Application/...`), not an export-relative path. A file that does not parse is skipped with `unparseable .st`.
2. Declaration and implementation need the exact markers `// ===== DECLARATION =====` / `// ===== IMPLEMENTATION =====` (a missing trailing newline after the impl marker is tolerated).
3. **Type names are application-scoped** — a folder does not namespace them. `CREATE_DUT|Application/Tests|Foo` fails or skips if `Application/Foo` already exists. Move or delete the old name first (`MOVE` / `DELETE`).
4. `structure_ops` is **all-or-nothing**: any `fatal` aborts the import and the project file is left untouched. Fix the op and re-run; do not assume half of the ops stuck.
5. `export.ps1` **rewrites** the export directory from the project. Copy hand-edited `.st` back only after export, or import first.
6. Close the project in the IDE before import (`project in use` otherwise).

## structure_ops.txt (structure operations list)

Placed at `<SrcRoot>/<project name>/structure_ops.txt`; executed in order before the text write-back; if absent, the import is pure text write-back. Paths start with the Application node name (same as the export tree):

```
CREATE_POU|<parent path>|<name>                   Program (ST)
CREATE_FB |<parent path>|<name>[|<base FB>[|<interface>]]  FunctionBlock (may inherit/implement)
CREATE_FUN|<parent path>|<name>|<return type>     Function
CREATE_DUT|<parent path>|<name>|Structure[|<base type>]    DUT (Enumeration/Alias/Union likewise)
CREATE_GVL|<parent path>|<name>                   Global variable list
CREATE_FOLDER|<parent path>|<name>                Organizational folder
CREATE_METHOD |<parent POU path>|<name>[|<return type>]    Method
CREATE_PROPERTY|<parent POU path>|<name>|<return type>     Property
CREATE_ACTION |<parent POU path>|<name>           Action
CREATE_TRANSITION|<parent POU path>|<name>        Transition
CREATE_TASK|<task config path>|<name>[|<kind>][|<interval>][|<priority>]
                                                  New task, e.g. CREATE_TASK|Application/Task Configuration|CommTask|Cyclic|t#20ms|2
                                                  (the task configuration node is created automatically on the application when missing)
RENAME|<old path>|<new name>                      Rename; migrates the .st/subdirectory and rewrites references project-wide (word boundaries)
MOVE|<object path>|<new parent path>              Moves an object to another folder (migrates the .st and updates PATH)
DELETE|<path>                                     Delete; allowed only with zero references (text bodies + task instances)
ASSIGN_TO_TASK|<task path>|<program path>         Assigns a program to a task (e.g. Application/Task Configuration/MainTask)
ADD_LIBRARY|<library manager resolve string>      Adds a library reference; the version must match the IDE profile (SP17 → 3.5.17.0), see boundaries below
```

**ADD_LIBRARY boundaries (learned the hard way)**:

- The script's `add_library` **only creates a placeholder and does not resolve the dependency chain** (e.g. SysTypes required by SysSocket is not pulled in); the GUI "Add Library" brings in the whole dependency tree. **For a new project missing libraries, add them once manually in the GUI first** (the binding persists after save); scripted library adds are only suitable when a proper reference already exists and you are re-creating a placeholder.
- The version in the resolve string must match the SP of the `-Profile` (SP17 → `3.5.17.0`); do not copy versions from the LibDoc directory — that is a documentation directory shared by multi-version installs and lists the newest.
- **Do not repeatedly add/remove placeholders** — it derails the IDE's library resolution state and affects every subsequent scripted add in the same session; once you see "type suddenly unknown", clean up in the GUI and re-add the correct version.
- Socket-style FBs: **create the FB and its instantiating caller in the same import**; adding new call sites to an existing Socket FB in a later import can crash parsing with "unknown type in the declaration of the called FB" (reproduced repeatedly).
- A failed placeholder resolution (empty resolution) shows up as compile error C77 "unknown type"; cleanup via `app.get_library_manager().remove_library('display name, version (vendor)')` — the full display string is required, the short name raises KeyError. Library Manager child nodes are ExtendedObjects and do not enumerate via `get_children()`; use `get_libraries()` / `remove_library()`.

The **content** of newly created objects still comes from their `.st` files (ops only create empty shells; the text write-back fills them):

```
# Create PRG_Init under Application and assign it to MainTask
CREATE_POU|Application|PRG_Init
ASSIGN_TO_TASK|Application/Task Configuration/MainTask|Application/PRG_Init
```

All CREATE_* and ASSIGN_TO_TASK are idempotent: when the target already exists (same-named object under the parent, or the program already in the task) they skip silently and log it; structure_ops.txt can stay as-is and be re-run with every import — no "applied" bookkeeping needed.

Import flow: backup → execute ops (each verified on write-back) → create missing folders per `_folders.txt` → `.st` text write-back → save only when changed (with a `save_as` fallback). Any failed step aborts without saving; roll back via the backup.

**RENAME note**: 3.5.17 `rename()` does not update references; the importer rewrites them at word boundaries (ST text bodies only — references inside graphic languages are not covered; run a build after renaming). CREATE followed by an immediate rename in the same ops file works; for renames across imports, if a caller's `.st` still carries the old name it gets overwritten by the text write-back — use a clean ops file for rename imports (do not carry caller `.st` files with the old name), or fix the caller texts first.

**DELETE note**: the reference check covers ST declarations/implementations (comments stripped, word boundaries) and task program call instances; **references in graphic languages (CFC/FBD) cannot be recognized** — when in doubt, do not delete.

## Daily workflow guards and sync

- **Timestamp guard**: a successful export/import stamps `<repo>/.codesys-sync/<project>_lastexport.txt`. On import, if the `.project` mtime is newer than the stamp (typical: hand-edited in the IDE and saved without re-exporting) the import is **refused** with a prompt to export first. Use `-Force` to override when sure it is safe.
- **Rename auto-detection (GUID fingerprint)**: after renaming/moving files in the export tree and updating the PATH header, just import — when the PATH is not found but the GUID matches, the importer performs the rename + project-wide reference rewriting + syncs the other `.st` bodies automatically (no hand-written RENAME op needed).
- **Refactor sync `-Sync`**: POU/DUT/GVL/methods new in the export tree are created automatically (type detected from the declaration header); textual objects present in the project but missing from the export tree are deleted (zero-reference + task instance protection).
- **git conventions**: `projects/`, `.codesys-sync/`, `*.bak` are not committed; text source is. Recommended `.gitattributes` in the target repo: `<SrcRoot>/** text eol=lf` (otherwise line endings jitter on every export under Windows `autocrlf=true`). Exported files contain no absolute paths and no timestamps; `creationDateTime` in `_full_export.xml` is normalized — re-exporting an unchanged project leaves `git status` clean.
- **Rollback**: import backs up to `<project>.<timestamp>.bak` (same directory as the project) before touching anything; copy it back over the project file to roll back.

## One-off patch mode

Changes that structure operations cannot cover (device tree, axis configuration, internals of graphic objects, ...) go through patches: place a **self-contained** `patch_project.py` + `run_patch.bat` in a patch directory of the repo (same Scripting Engine route; the `.py` uses the same target.txt convention as these scripts), back up first, log every step.

The boundary outside referenced callers remains for deletions: `o.remove()` is irreversible and can only be recovered from the pre-patch `.project` backup; the DELETE structure op has a built-in reference check, but hand-written patch deletions still need your own verification.

## Pitfalls (read before modifying the scripts)

- The inner .py files run on the CODESYS built-in **IronPython 2.7 — no Python 3 syntax**; the outer layer is a PowerShell wrapper (no local Python needed).
- **Export** operates on a copy in a temp area (robocopy — a plain copy silently truncates the file while the IDE has it locked); **import/patches write the REAL project** — the project must be closed in the IDE first, otherwise the IDE's next save overwrites your import.
- Do not call `CODESYS.exe` from Git Bash with `--profile="..."` (MSYS argument conversion eats the quotes); do not pass it inline with `&` from ps1 either (PS 5.1 quotes the whole argument containing spaces and CODESYS mis-parses it as "must specify --profile"). Always generate a **pure ASCII temp bat** and call it via cmd (built into the scripts).
- **ps1 files must be saved UTF-8 with BOM** (PS 5.1 parses without BOM as GBK and chokes); when a ps1 throws weird syntax errors after editing, check the BOM first.
- ps1 → py parameters are passed via `target.txt` (UTF-8 key=value) whose path is pointed to by the `CODESYS_SYNC_TARGET` environment variable into the target repo's `.codesys-sync/`; the .py also supports the legacy "target.txt next to the script" (self-contained patch directory style).
- **Scripting API facts (verified on 3.5.17 and 3.5.22)**:
  - `create_pou/create_function_block/create_function/create_dut/create_gvl/create_folder/create_method/create_property/create_action/create_transition/create_task/move` all work (interface since 3.5.9.0)
  - `create_folder()` **returns None** — look the object up by name after creating it
  - A new POU's `textual_implementation` has `has_textual_implementation=False` until first written — the importer force-writes
  - `rename()` does not update references (3.5.17) — the importer rewrites them at word boundaries
  - `task.pous.add(<program name string>)` — passing an object raises TypeError; the `task.priority` setter wants a string (the script falls back int→str)
  - ACTION/TRANSITION have no separate textual declaration; a PROPERTY implementation is a GET/SET pair of documents and cannot be written as a single impl — the corresponding warnings in the log are normal
  - `save()` works headless (noUI); the importer keeps a `save_as` + file-replace fallback
  - The library list objects are `ExtendedObject[IScriptObject]` whose properties IronPython cannot read — the library section of `_project_info` is parsed from `_full_export.xml`
  - **3.5.22 difference**: `doc.text` may carry one extra trailing newline — text comparison normalizes with `rstrip` (`same_text`)
- **Version guard**: `project_settings.get_compilerversion()` is compared against the version in the running CODESYS path; older-opens-newer FATALs immediately (otherwise the old IDE silently reads 0 objects). Newer-opens-older (upgrade) is allowed.
- **Build specifics**: the global object in the scripting environment is lowercase `system` (the documented `System` does not exist); `app.build()` does not throw on errors and the CODESYS exit code is always 0 — judge by the `errors=` count in the report; `print()` output from the script lands in the message store, so compile messages are fetched via `system.get_message_objects(category)` with the script-output category excluded (`build_project.py` handles this — read it before changing).
- The import text loop **must re-parse content just in time**: a GUID rename rewrites `.st` files on disk mid-loop; writing back from content parsed before the loop would overwrite the just-fixed references.
- **Multiple `.st` files with the same PATH are a data-corruption trap** (an empty shell once overwrote full content) — the importer hard-checks: duplicate PATHs FATAL and list the files; delete the stale copy manually, then re-import.
- **The DELETE op also deletes the corresponding `.st` file** — after "delete and recreate under the same name" you must rewrite the source file, otherwise the text stage finds nothing to write and the object stays an empty shell.
- Removing a program call from a task takes **two steps**: after `task.pous.remove(name)` the instance node often remains; remove the same-named instance node under the task as well (see the remove_task_instances pattern from development).
- `projects.create(path)` creates a project (path includes the `.project` file name); `proj.add(name, DeviceID(type, id, version))` adds a root device; device objects add children via `.add/.plug/.insert` — `add` returns None (like `create_folder`), look the object up by name afterwards.
  - Common SoftMotion device-tree IDs: CODESYS SoftMotion Win V3 = `4102/0000 0001` (ships a "SoftMotion General Axis Pool" node — `.add` axis objects directly on it); virtual axis SM_Drive_Virtual = `1024/FFFF 0001`; axis pool device description = `1249/0000 0001`; CODESYS Control Win V3 = `4096/0000 0001` (axis pool `1249` works as its child device, the PLCopenSingle example tree).
  - A new Application has no Task Configuration node by default; `app.create_task_configuration()` adds one (CREATE_TASK auto-creates it in the importer).
- ST syntax traps: `dt` is a reserved word (DT type); **instance declarations must not carry initializers** (`fb : FB(x:=TRUE)` breaks FB_Init resolution — put initialization in the body or assignments); inline STRUCTs in program VARs **must be promoted to DUTs**; POINTER parameters should not use the call-style `fb(p:=ADR(x))` — assign fields one by one, then call bare.

## Verified scope

Verified on 3.5.17 / 3.5.22: full-range object CRUD, reference rewriting, task creation and assignment, library adds, `-Sync` refactor sync, timestamp guard, GUID rename detection, `.bak` rollback, file-lock protection, multi-task projects, SoftMotion/system-library projects, git clone round-trip (export idempotent, clean diffs), SoftMotion virtual-axis creation (`pool.add(name, scriptengine.DeviceID(...))`), and building a complete project from scratch (SoftMotion virtual axes, system libraries, multi-task setup).
