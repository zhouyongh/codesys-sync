# -*- coding: utf-8 -*-
# CODESYS Scripting Engine (IronPython 2.7) — fast precompile check.
# Uses ScriptProject.check_all_pool_objects() (lighter than a full build)
# and writes the same report format as build_project.py:
#   errors=N / warnings=N at the top, details below.
# target.txt keys (env CODESYS_SYNC_TARGET or script-adjacent):
#   source  = original project path (for the report header, optional)
#   project = project file to check (usually a copy)
#   report  = output report path
import io
import os
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.environ.get("CODESYS_SYNC_TARGET") or os.path.join(SCRIPT_DIR, "target.txt")

# same message-category GUIDs as build_project.py (SP17)
SCRIPT_CAT = "{194b48a9-ab51-43ae-b9a9-51d3edaaddf3}"

lines = []


def log(msg):
    lines.append(u"%s" % msg)


def read_target(path):
    vals = {}
    f = io.open(path, "r", encoding="utf-8")
    try:
        for line in f:
            line = line.strip()
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    finally:
        f.close()
    return vals


def cat_str(cat):
    return u"{%s}" % str(cat).lower().strip("{}")


cfg = read_target(TARGET)
SOURCE = cfg.get("source", u"")
PROJECT = cfg["project"]
REPORT = cfg["report"]

n_err = 0
n_warn = 0
summaries = []
status = u"not run"

try:
    log(u"source=%s" % SOURCE)
    log(u"project=%s" % PROJECT)
    proj = projects.open(PROJECT)
    log(u"opened: %s" % proj.path)

    # version guard (same rule as export/import)
    try:
        cv = u"%s" % proj.project_settings.get_compilerversion()
        import System.Diagnostics as _sd
        exe = u"%s" % _sd.Process.GetCurrentProcess().MainModule.FileName
        log(u"version check: project compiler=%s running=%s" % (cv, exe))
        parts = cv.split(u".")
        proj_series = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        run_series = None
        for seg in exe.replace(u"\\", u"/").split(u"/"):
            if seg.startswith(u"CODESYS 3.5."):
                cand = seg[len(u"CODESYS 3.5."):].split(u" ")[0].split(u".")[0]
                if cand.isdigit():
                    run_series = int(cand)
                break
        if proj_series is not None and run_series is not None and proj_series > run_series:
            raise RuntimeError(
                u"project saved with CODESYS %s but running installation is older (%s)"
                % (cv, exe))
    except RuntimeError:
        raise
    except Exception as e:
        log(u"version check skipped: %r" % (e,))

    # drop messages produced while opening
    try:
        for c in list(system.get_message_categories()):
            if cat_str(c) != SCRIPT_CAT:
                system.clear_messages(c)
    except Exception as e:
        log(u"clear_messages failed: %s" % e)

    try:
        result = proj.check_all_pool_objects()
        log(u"check_all_pool_objects returned: %r" % (result,))
        status = u"ok"
    except Exception as e:
        status = u"raised: %s" % e
        log(u"check=%s" % status)

    try:
        cats = list(system.get_message_categories())
    except Exception:
        cats = []
    for c in cats:
        if cat_str(c) == SCRIPT_CAT:
            continue
        try:
            objs = system.get_message_objects(c)
        except Exception:
            continue
        for m in objs:
            try:
                sev = str(m.severity)
            except Exception:
                sev = u"?"
            try:
                text = u"%s" % m.text
            except Exception:
                text = u"?"
            if sev == u"Text":
                if (u"rror" in text) or (u"错误" in text):
                    summaries.append(text)
                continue
            if sev == u"Error":
                n_err += 1
            elif sev == u"Warning":
                n_warn += 1
            try:
                num = m.number
            except Exception:
                num = None
            code = u"C%s" % num if num is not None else u"C?"
            try:
                obj = m.object
            except Exception:
                obj = None
            name = u"-"
            try:
                name = obj.get_name()
            except Exception:
                pass
            log(u"[%s %s] %s | %s" % (sev.upper(), code, name, text.replace(u"\n", u" ")))

    try:
        proj.close()
    except Exception:
        pass
    log(u"check=%s" % status)
except Exception:
    log(u"FATAL")
    log(traceback.format_exc())
    n_err += 1
    summaries.append(u"FATAL (see details)")

final = []
final.append(u"errors=%d" % n_err)
final.append(u"warnings=%d" % n_warn)
final.append(u"source=%s" % SOURCE)
final.append(u"mode=precompile (check_all_pool_objects)")
for s in summaries:
    final.append(u"summary=%s" % s)
final.append(u"--- details ---")
final.extend(lines)

f = io.open(REPORT, "w", encoding="utf-8")
try:
    f.write(u"\n".join(final) + u"\n")
finally:
    f.close()
