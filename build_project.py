# -*- coding: utf-8 -*-
# Build a CODESYS project headless and write a structured compile report
# (IronPython 2.7 — no Python 3 syntax). Companion of export_pous.py /
# import_pous.py; target paths arrive the same way:
#   env CODESYS_SYNC_TARGET -> UTF-8 key=value file (fallback: script-adjacent)
#   source=<original project>   project=<copy to build>   report=<output report>
import io
import os
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.environ.get("CODESYS_SYNC_TARGET") or os.path.join(SCRIPT_DIR, "target.txt")

# message categories (CODESYS 3.5 SP17, fixed GUIDs):
#   {194b48a9-...} script/console output  -> excluded (our own trace)
#   {56a60174-...} library manager
#   {97f48d64-...} compiler
#   {220493a1-...} other code checks
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
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.strip()
    finally:
        f.close()
    return vals


def find_app(node):
    try:
        if node.is_application:
            return node
    except Exception:
        pass
    for ch in node.get_children(False):
        r = find_app(ch)
        if r is not None:
            return r
    return None


def cat_str(cat):
    return u"{%s}" % str(cat).lower().strip("{}")


def get_name_safe(obj):
    if obj is None:
        return u"-"
    try:
        return u"%s" % obj.get_name()
    except Exception:
        return u"?"


cfg = read_target(TARGET)
SOURCE = cfg.get("source", u"")
PROJECT = cfg["project"]
REPORT = cfg["report"]

n_err = 0
n_warn = 0
summaries = []
build_status = u"not run"

try:
    log(u"source=%s" % SOURCE)
    log(u"project=%s" % PROJECT)
    proj = projects.open(PROJECT)

    # version guard: an older IDE cannot meaningfully build a newer project
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
                rest = seg[len(u"CODESYS 3.5."):]
                cand = rest.split(u" ")[0].split(u".")[0]
                if cand.isdigit():
                    run_series = int(cand)
                break
        if proj_series is not None and run_series is not None and proj_series > run_series:
            raise RuntimeError(
                u"project saved with CODESYS %s but running installation is older (%s) "
                u"— use a matching CODESYS install" % (cv, exe))
    except RuntimeError:
        raise
    except Exception as e:
        log(u"version check skipped: %r" % (e,))

    app = None
    try:
        app = proj.active_application
    except Exception:
        app = None
    if app is None:
        app = find_app(proj)
    log(u"application=%s" % app.get_name())

    # drop messages produced while opening (library complaints reappear
    # as compile warnings during the build itself)
    try:
        for c in list(system.get_message_categories()):
            if cat_str(c) != SCRIPT_CAT:
                system.clear_messages(c)
    except Exception as e:
        log(u"clear_messages failed: %s" % e)

    try:
        app.build()
        build_status = u"ok"
    except Exception as e:
        build_status = u"raised: %s" % e
    log(u"build=%s" % build_status)

    try:
        cats = list(system.get_message_categories())
    except Exception:
        cats = []
    for c in cats:
        if cat_str(c) == SCRIPT_CAT:
            continue
        try:
            objs = system.get_message_objects(c)
        except Exception as e:
            log(u"get_message_objects(%s) failed: %s" % (cat_str(c), e))
            continue
        for m in objs:
            try:
                sev = str(m.severity)
            except Exception:
                sev = u"?"
            try:
                text = u"%s" % m.text
            except Exception:
                text = u"<no text>"
            if sev == u"Text":
                # keep only result/summary lines, drop progress chatter
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
                pos = m.position_text
                pos = u"%s" % pos if pos else u"-"
            except Exception:
                pos = u"-"
            try:
                obj = m.object
            except Exception:
                obj = None  # dangling GUID in stale projects
            name = get_name_safe(obj)
            try:
                log(u"[%s %s] %s | %s | %s" % (
                    sev.upper(), code, name, pos, text.replace(u"\n", u" ")))
            except Exception as e:
                log(u"[?] <message formatting failed: %s>" % e)

    proj.close()
except Exception as e:
    log(u"FATAL")
    log(traceback.format_exc())
    # a fatal abort (e.g. version guard) must never report errors=0
    n_err += 1
    summaries.append(u"FATAL: %s" % e)

final = []
final.append(u"errors=%d" % n_err)
final.append(u"warnings=%d" % n_warn)
final.append(u"source=%s" % SOURCE)
for s in summaries:
    final.append(u"summary=%s" % s)
final.append(u"--- details ---")
final.extend(lines)

f = io.open(REPORT, "w", encoding="utf-8")
try:
    f.write(u"\n".join(final) + u"\n")
finally:
    f.close()
