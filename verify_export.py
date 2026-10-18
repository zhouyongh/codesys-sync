# -*- coding: utf-8 -*-
# CODESYS Scripting Engine (IronPython 2.7) — export-tree consistency check.
# Compares the on-disk export tree (*.st under indir) against the live project
# WITHOUT modifying anything. Report format like build/check:
#   errors=N / warnings=N at the top, details below.
# Checks:
#   missing_in_project : .st PATH not found (and no GUID match)
#   rename_candidates   : .st PATH not found but GUID matches an object (rename drift)
#   content_diff        : decl/impl differ (ignoring trailing newlines / EOL)
#   missing_in_tree     : project textual object has no .st in the tree
# target.txt keys (env CODESYS_SYNC_TARGET or script-adjacent):
#   project = project file to open (copy is fine)
#   indir   = export root (Application/**.st)
#   report  = output report path
import codecs
import io
import os
import re
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET = os.environ.get("CODESYS_SYNC_TARGET") or os.path.join(SCRIPT_DIR, "target.txt")

SKIP_NAMES = set([u"Library Manager", u"Task Configuration"])
DECL_MARK = u"// ===== DECLARATION =====\n"
IMPL_MARK = u"\n// ===== IMPLEMENTATION =====\n"

lines = []


def log(msg):
    lines.append(u"%s" % msg)


def read_target(path):
    vals = {}
    f = io.open(path, "r", encoding="utf-8")
    try:
        for line in f:
            line = line.strip()
            if u"=" not in line:
                continue
            k, v = line.split(u"=", 1)
            vals[k.strip()] = v.strip()
    finally:
        f.close()
    return vals


def norm_eol(t):
    if t is None:
        return None
    return t.replace(u"\r\n", u"\n")


def same_text(a, b):
    if a is None or b is None:
        return a == b
    return a.rstrip(u"\n") == b.rstrip(u"\n")


def get_name(o):
    try:
        return unicode(o.get_name())
    except Exception:
        return u"?"


def children(o):
    try:
        ch = o.get_children()
    except Exception:
        ch = []
    return ch if ch else []


def get_text(o, kind):
    try:
        if kind == u"decl" and o.has_textual_declaration:
            t = o.textual_declaration.text
            return norm_eol(unicode(t)) if t else u""
        if kind == u"impl" and o.has_textual_implementation:
            t = o.textual_implementation.text
            return norm_eol(unicode(t)) if t else u""
    except Exception:
        pass
    return None


def parse_st(fname):
    f = codecs.open(fname, "r", "utf-8-sig")
    text = norm_eol(f.read())
    f.close()
    if not text.startswith(u"// PATH: "):
        return None
    eol = text.index(u"\n")
    pou_path = text[len(u"// PATH: "):eol].strip()
    guid = u""
    for ln in text[:eol + 1 + 200].split(u"\n"):
        if ln.startswith(u"// GUID: "):
            guid = ln[len(u"// GUID: "):].strip()
            break
    try:
        d1 = text.index(DECL_MARK) + len(DECL_MARK)
        d2 = text.index(IMPL_MARK)
        i1 = d2 + len(IMPL_MARK)
    except ValueError:
        return None
    decl = text[d1:d2]
    impl = text[i1:]
    if impl.endswith(u"\r\n"):
        impl = impl[:-2]
    elif impl.endswith(u"\n"):
        impl = impl[:-1]
    return pou_path, decl, impl, guid


cfg = read_target(TARGET)
PROJECT = cfg[u"project"]
INDIR = cfg[u"indir"]
REPORT = cfg[u"report"]

n_err = 0
n_warn = 0

try:
    proj = projects.open(PROJECT)
    log(u"opened: " + unicode(proj.path))

    # version guard
    try:
        cv = unicode(proj.project_settings.get_compilerversion())
        import System.Diagnostics as _sd
        exe = unicode(_sd.Process.GetCurrentProcess().MainModule.FileName)
        log(u"version check: project=%s running=%s" % (cv, exe))
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
            raise RuntimeError(u"project saved with %s but running older IDE (%s)" % (cv, exe))
    except RuntimeError:
        raise
    except Exception as e:
        log(u"version check skipped: %r" % (e,))

    # index project textual objects (Application subtree, skip system nodes)
    proj_texts = {}   # full path -> (obj, decl, impl)
    guid_map = {}     # guid -> full path

    def walk(o, full_path):
        name = get_name(o)
        if name in SKIP_NAMES:
            return
        try:
            g = unicode(o.guid)
            if g:
                guid_map[g] = full_path
        except Exception:
            pass
        d = get_text(o, u"decl")
        i = get_text(o, u"impl")
        textual = (d is not None and d.strip() != u"") or (i is not None and i.strip() != u"")
        if textual:
            proj_texts[full_path] = (o, d if d is not None else u"", i if i is not None else u"")
        for c in children(o):
            walk(c, full_path + u"/" + get_name(c))

    def find_apps(o, prefix, acc):
        full = prefix + u"/" + get_name(o) if prefix else get_name(o)
        try:
            if o.is_application:
                acc.append((full, o))
                return
        except Exception:
            pass
        for c in children(o):
            find_apps(c, full, acc)

    apps = []
    for top in proj.get_children():
        find_apps(top, u"", apps)
    for app_full, app_obj in apps:
        for c in children(app_obj):
            walk(c, app_full + u"/" + get_name(c))
    log(u"project textual objects: %d" % len(proj_texts))

    # scan .st tree
    st_paths = set()
    for root, dirs, files in os.walk(INDIR):
        for fn in files:
            if not fn.endswith(u".st"):
                continue
            fp = os.path.join(root, fn)
            parsed = parse_st(fp)
            if parsed is None:
                log(u"UNPARSEABLE: " + fp)
                n_err += 1
                continue
            pou_path, decl, impl, guid = parsed
            st_paths.add(pou_path)
            hit = proj_texts.get(pou_path)
            if hit is None:
                if guid and guid in guid_map:
                    log(u"RENAME_CANDIDATE: %s -> project object at %s (GUID match)"
                        % (pou_path, guid_map[guid]))
                    n_warn += 1
                else:
                    log(u"MISSING_IN_PROJECT: " + pou_path)
                    n_err += 1
                continue
            _o, pd, pi = hit
            if not same_text(pd, decl):
                log(u"CONTENT_DIFF (decl): " + pou_path)
                n_err += 1
            if not same_text(pi, impl):
                log(u"CONTENT_DIFF (impl): " + pou_path)
                n_err += 1

    # reverse: project objects missing from tree
    for p in sorted(proj_texts.keys()):
        if p not in st_paths:
            log(u"MISSING_IN_TREE: " + p)
            n_err += 1

    try:
        proj.close(False)
    except Exception:
        try:
            proj.close()
        except Exception:
            pass
    log(u"done")
except Exception:
    log(u"FATAL")
    log(traceback.format_exc())
    n_err += 1

final = []
final.append(u"errors=%d" % n_err)
final.append(u"warnings=%d" % n_warn)
final.append(u"project=%s" % PROJECT)
final.append(u"indir=%s" % INDIR)
final.append(u"--- details ---")
final.extend(lines)

f = io.open(REPORT, "w", encoding="utf-8")
try:
    f.write(u"\n".join(final) + u"\n")
finally:
    f.close()
