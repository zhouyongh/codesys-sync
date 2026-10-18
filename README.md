# codesys-sync

**Sync binary CODESYS projects with plain-text source — for Git, code review, and AI agents.**

CODESYS stores projects (`.project` / `.library`) as binary files. Git cannot diff them, code review cannot see what changed, and AI coding agents cannot read or write them at all. codesys-sync converts between the two worlds through the official **CODESYS Scripting Engine** (IronPython, `CODESYS.exe --runscript`, fully headless):

```text
   .project  ──export──►  Application/**/*.st  ◄──edit──►  you / Git / AI agent
   (binary)  ◄──import──  + structure_ops.txt            (plain text)
                                   │
                                   ▼
                          headless build report
```

## What it can do

- **Round-trip text sync** — export every Application object to plain-text `.st` files, then write them back into the binary project, verified object by object.
- **Structural changes as text** — create / rename / move / delete objects, wire programs into tasks, and add library references via a declarative `structure_ops.txt`; renames rewrite references across the whole project automatically.
- **Headless build** — compile a project copy without opening the IDE; structured `errors=` / `warnings=` report with meaningful exit codes.
- **Read-only verification** — compare the text tree against the project and report missing objects, content drift, and rename candidates.
- **Safety rails** — automatic backup before every import, per-object write-back verification, a timestamp guard that refuses stale imports, and a version guard against IDE/project mismatches.
- **Git-friendly output** — exports contain no absolute paths and no timestamps; re-exporting an unchanged project leaves `git status` clean.

The typical loop: **export → edit text (yourself or an AI agent) → import → build** — every step runnable and verifiable from the command line, no IDE interaction required.

## Requirements

- Windows (PowerShell 5.1; the scripts are UTF-8 **with BOM** — keep it when editing)
- A local CODESYS 3.5.x installation with Scripting Engine (standard). Auto-detected: newest `CODESYS 3.5*` under Program Files. Override with `-CodesysExe`/`-Profile` or `CODESYS_SYNC_EXE`/`CODESYS_SYNC_PROFILE` — mandatory when several versions coexist and the project belongs to an older one.
- No Python needed on the machine — the inner scripts run on CODESYS' built-in IronPython 2.7.
- Verified on **CODESYS 3.5.17 and 3.5.22**.

## Quick start

1. In your repo, keep real projects under `projects/` (gitignored, never committed):

   ```
   my-plc-repo/
     projects/        <- real .project/.library files (NOT in git)
     src/plc/         <- exported text source (in git)
   ```

2. Export once:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File <path-to>\codesys-sync\export.ps1 -Root D:\repos\my-plc-repo
   ```

3. Edit the exported `.st` files (or ask an AI agent to), commit the diffs, then write back:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File <path-to>\codesys-sync\import.ps1 -Root D:\repos\my-plc-repo
   ```

   **Close the project in the CODESYS IDE first** — import writes the real project file. It backs up automatically (`<project>.<timestamp>.bak`), verifies each object after write-back, and only saves when something actually changed.

4. Build headlessly to confirm:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File <path-to>\codesys-sync\build.ps1 -Root D:\repos\my-plc-repo
   ```

   Exit code 0 = compiled with 0 errors; the report starts with `errors=` / `warnings=` counts.

Optional convenience: drop thin `.bat` shims in your repo (double-click entry points) that call the scripts above with `-Root` preset.

## The four commands

| Script | What it does | Reads / writes |
|---|---|---|
| `export.ps1` | Project → text tree (`*.st`, `_folders.txt`, `_index.txt`, `_project_info.txt`, `_full_export.xml`) | works on a **copy** — IDE can stay open |
| `import.ps1` | Text → project: runs `structure_ops.txt` first, then per-object text write-back | writes the **real** project (auto-backup, verified) |
| `verify.ps1` | Read-only consistency check: text tree vs project (missing objects, drift, rename candidates) | nothing |
| `build.ps1` | Headless build of a project copy, structured report | works on a **copy** — IDE can stay open |

All four take `-Root`, `-Select <n>` (non-interactive project pick), and installation overrides. `import.ps1` additionally supports `-Yes`, `-Dir <keyword>`, `-Sync` (structure sync for refactors), `-Force`, `-VerifyBuild`, `-VerifyQuick`. Full parameter reference: [SKILL.md](SKILL.md).

## Working with AI agents

The repo doubles as an **agent skill**: `SKILL.md` is a complete, self-contained instruction set (formats, ops reference, pitfalls, verified API facts) that lets coding agents like ZCode or Claude run the export → edit → import → build loop autonomously. Point your agent at this repository, or copy the folder into your agent's skills directory.

## Safety model

- **Backups**: import copies the project to `<project>.<timestamp>.bak` before touching it; copy back to roll back.
- **Write-back verification**: every object is re-read after writing; any mismatch aborts without saving.
- **Timestamp guard**: if the project file is newer than the last export (someone hand-edited in the IDE), import refuses until you re-export (override: `-Force`).
- **Version guard**: an older IDE silently reading a newer project as empty is detected and FATALs instead.
- Note: `CODESYS --runscript` exit codes are unreliable — success/failure is judged from the logs (`FATAL`/`ABORTED`) and the build report's `errors=` count, which the wrappers do for you.

## Limitations

- Windows only (PowerShell + CODESYS IDE).
- Reference rewriting on rename covers ST text bodies; references inside graphic languages (CFC/FBD) are not rewritten and not seen by DELETE's reference check.
- Library adds create placeholders only (no dependency resolution) — add brand-new libraries once via the GUI. Details in [SKILL.md](SKILL.md).

## License

[Unlicense](LICENSE) — public domain. Use, modify, republish, sell; no attribution required.
