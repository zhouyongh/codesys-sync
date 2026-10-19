# -*- coding: utf-8 -*-
# CODESYS Scripting Engine (IronPython 2.7) — generic project exporter, v2.
# Reads target.txt (key=value, UTF-8): path from env CODESYS_SYNC_TARGET,
# falling back to a target.txt next to this script:
#   project = absolute path of the .project/.library to open (usually a copy)
#   outdir  = output directory
#   log     = log file path
#
# Output layout (outdir):
#   Application/.../*.st        tree mirroring each Application (folders kept)
#                               POU body = <Name>.st; methods/properties etc.
#                               live in a same-named directory <Name>/
#   _folders.txt                all real folders (incl. empty), one per line
#   _index.txt                  flat index: <rel .st path>\t<full project PATH>
#   _project_info.txt           project / devices / tasks / libraries summary
#   _full_export.xml            full PLCopenXML (graphical languages etc.)
#
# Non-textual system nodes under Application (Library Manager, Task
# Configuration) are NOT exported as directories; their content is summarized
# in _project_info.txt instead.
# Do NOT use Python 3 syntax — this runs inside CODESYS IronPython 2.7.

import codecs
import os
import re
import time


def script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return "."


BASE = script_dir()

cfg = {}
TARGET = os.environ.get("CODESYS_SYNC_TARGET") or os.path.join(BASE, "target.txt")
f = codecs.open(TARGET, "r", "utf-8-sig")
for ln in f.read().splitlines():
    if u"=" in ln:
        k, v = ln.split(u"=", 1)
        cfg[k.strip()] = v.strip()
f.close()

PROJ = cfg[u"project"]
OUT = cfg[u"outdir"]
LOG = cfg[u"log"]

# system nodes under Application that must not become directories
SKIP_NAMES = set([u"Library Manager", u"Task Configuration"])

DECL_MARK = u"// ===== DECLARATION =====\n"
IMPL_MARK = u"\n// ===== IMPLEMENTATION =====\n"


def ensure_clean_dir(path):
    if os.path.isdir(path):
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except Exception:
                    pass
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except Exception:
                    pass
    else:
        os.makedirs(path)


ensure_clean_dir(OUT)

logf = codecs.open(LOG, "w", "utf-8")


def log(msg):
    try:
        logf.write(unicode(msg) + u"\n")
        logf.flush()
    except Exception:
        pass


def fatal(msg):
    log(u"FATAL: " + msg)
    raise SystemExit


def safe_filename(name):
    s = re.sub(ur'[\\/:*?"<>|\r\n]+', u"_", unicode(name))
    return s[:80]


def get_name_safe(o):
    try:
        return unicode(o.get_name())
    except Exception:
        return u"?"


def obj_type_guid(o):
    try:
        return unicode(o.type)
    except Exception:
        return u""


def has_text(o, kind):
    try:
        if kind == u"decl" and o.has_textual_declaration:
            t = o.textual_declaration.text
            return t is not None and unicode(t).strip() != u""
        if kind == u"impl" and o.has_textual_implementation:
            t = o.textual_implementation.text
            return t is not None and unicode(t).strip() != u""
    except Exception:
        pass
    return False


def get_text(o, kind):
    try:
        if kind == u"decl" and o.has_textual_declaration:
            t = o.textual_declaration.text
            return unicode(t) if t else u""
        if kind == u"impl" and o.has_textual_implementation:
            t = o.textual_implementation.text
            return unicode(t) if t else u""
    except Exception:
        pass
    return u""


def is_folder(o):
    try:
        return bool(o.is_folder)
    except Exception:
        return False


def is_application(o):
    try:
        return bool(o.is_application)
    except Exception:
        return False


def children(o):
    try:
        ch = o.get_children()
    except Exception:
        ch = []
    return ch if ch else []


folders = []       # rel paths of real folders (from export root)
index_rows = []    # (rel_st_path, full_path)
exported = 0
skipped_nontext = 0


def write_st(o, full_path, rel_dir):
    """Write one textual object as <rel_dir>/<Name>.st. Returns the st rel path."""
    global exported
    name = get_name_safe(o)
    rel = os.path.join(rel_dir, safe_filename(name) + u".st")
    abs_path = os.path.join(OUT, rel)
    parent = os.path.dirname(abs_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    decl = get_text(o, u"decl") if has_text(o, u"decl") else u""
    impl = get_text(o, u"impl") if has_text(o, u"impl") else u""
    f = codecs.open(abs_path, "w", "utf-8")
    f.write(u"// PATH: " + full_path + u"\n")
    try:
        f.write(u"// GUID: " + unicode(o.guid) + u"\n")
    except Exception:
        f.write(u"// GUID: \n")
    f.write(u"// TYPE: " + obj_type_guid(o) + u"\n")
    f.write(DECL_MARK)
    f.write(decl)
    f.write(IMPL_MARK)
    f.write(impl)
    if not impl.endswith(u"\n"):
        f.write(u"\n")
    f.close()
    exported += 1
    index_rows.append((rel.replace(u"\\", u"/"), full_path))
    log(u"exported: " + rel.replace(u"\\", u"/"))
    return rel


def walk_app(o, full_path, rel_dir):
    """Walk an Application subtree. full_path uses '/' separators (project PATH)."""
    global skipped_nontext
    name = get_name_safe(o)
    if name in SKIP_NAMES:
        log(u"skip system node: " + full_path)
        return

    if is_folder(o):
        rel = os.path.join(rel_dir, safe_filename(name))
        abs_dir = os.path.join(OUT, rel)
        if not os.path.isdir(abs_dir):
            os.makedirs(abs_dir)
        folders.append(rel.replace(u"\\", u"/"))
        log(u"folder: " + rel.replace(u"\\", u"/"))
        for c in children(o):
            walk_app(c, full_path + u"/" + get_name_safe(c), rel)
        return

    textual = has_text(o, u"decl") or has_text(o, u"impl")
    kids = children(o)
    if textual:
        rel_st = write_st(o, full_path, rel_dir)
        # children (methods/properties/actions/...) live in a same-named dir
        if kids:
            sub_rel = os.path.join(rel_dir, safe_filename(name))
            sub_abs = os.path.join(OUT, sub_rel)
            if not os.path.isdir(sub_abs):
                os.makedirs(sub_abs)
            for c in kids:
                walk_app(c, full_path + u"/" + get_name_safe(c), sub_rel)
        return

    # non-textual, non-folder: system-ish or graphical object
    if kids:
        skipped_nontext += 1
        log(u"skip non-textual container: " + full_path)
        return
    # leaf non-textual (e.g. task pou instance) — ignore silently
    return


def write_project_info(proj, apps):
    path = os.path.join(OUT, u"_project_info.txt")
    f = codecs.open(path, "w", "utf-8")
    f.write(u"# _project_info.txt — generated by codesys-sync export, read-only\n")
    f.write(u"# project / devices / tasks / libraries summary for AI + humans\n\n")

    f.write(u"[project]\n")
    f.write(u"file: %s\n" % os.path.basename(PROJ))
    # last-saved compiler version — used by Resolve-CodesysInstall to pick
    # the matching CODESYS install on import/build (do not remove)
    try:
        cv = unicode(proj.project_settings.get_compilerversion())
    except Exception:
        cv = u""
    f.write(u"compiler_version: %s\n" % cv)
    # no absolute path / no timestamp here — this file is committed to git
    f.write(u"\n")

    f.write(u"[project_information]\n")
    try:
        has_pi = bool(proj.has_project_info)
    except Exception:
        has_pi = False
    if not has_pi:
        f.write(u"note: project information not set in IDE (has_project_info=False)\n\n")
    else:
        try:
            pi = proj.get_project_info()
            for fld in (u"company", u"title", u"version", u"author",
                        u"description", u"default_namespace"):
                try:
                    v = getattr(pi, fld)
                    f.write(u"%s: %s\n" % (fld, v if v is not None else u""))
                except Exception:
                    f.write(u"%s: <unavailable>\n" % fld)
            f.write(u"\n")
        except Exception as e:
            f.write(u"error: %r\n\n" % (e,))

    f.write(u"[applications]\n")
    for full, obj in apps:
        f.write(u"%s\n" % full)
    f.write(u"\n")

    f.write(u"[devices]\n")
    try:
        def walk_dev(o, prefix):
            name = get_name_safe(o)
            full = prefix + u"/" + name if prefix else name
            try:
                if o.is_device:
                    ident = o.get_device_identification()
                    f.write(u"%s  type=%s id=%s version=%s\n" % (
                        full,
                        getattr(ident, u"type", u"?"),
                        getattr(ident, u"id", u"?"),
                        getattr(ident, u"version", u"?")))
            except Exception:
                pass
            for c in children(o):
                walk_dev(c, full)
        for top in proj.get_children():
            walk_dev(top, u"")
    except Exception as e:
        f.write(u"error: %r\n" % (e,))
    f.write(u"\n")

    f.write(u"[tasks]\n")
    try:
        def walk_tasks(o, prefix):
            name = get_name_safe(o)
            full = prefix + u"/" + name if prefix else name
            is_task = False
            kind = u""
            interval = u""
            prio = u""
            try:
                kind = unicode(o.kind_of_task)
                is_task = True
                try:
                    interval = unicode(o.interval)
                except Exception:
                    interval = u"?"
                try:
                    prio = unicode(o.priority)
                except Exception:
                    prio = u"?"
            except Exception:
                pass
            if is_task:
                progs = [get_name_safe(c) for c in children(o)]
                f.write(u"%s  kind=%s interval=%s priority=%s programs=%s\n" % (
                    full, kind, interval, prio, u",".join(progs) if progs else u"-"))
            for c in children(o):
                walk_tasks(c, full)
        for app_full, app_obj in apps:
            for c in children(app_obj):
                walk_tasks(c, app_full)
    except Exception as e:
        f.write(u"error: %r\n" % (e,))
    f.write(u"\n")

    f.write(u"[libraries]\n")
    # SP17 wraps library objects in ExtendedObject[IScriptObject] whose members
    # are not reachable from IronPython — take the data from the PLCopenXML
    # export instead (Name / Namespace / DefaultResolution).
    xml_path = os.path.join(OUT, u"_full_export.xml")
    parsed = False
    try:
        if os.path.isfile(xml_path):
            xf = codecs.open(xml_path, "r", "utf-8-sig")
            xtext = xf.read()
            xf.close()
            import re as _re
            for m in _re.finditer(ur'<Library\s+([^>]*?)/?>', xtext):
                attrs = m.group(1)
                def _attr(key):
                    mm = _re.search(key + u'="([^"]*)"', attrs)
                    return mm.group(1) if mm else u""
                nm = _attr(u"Name")
                ns = _attr(u"Namespace")
                res = _attr(u"DefaultResolution")
                if nm:
                    f.write(u"%s  namespace=%s resolution=%s\n" % (nm, ns, res))
                    parsed = True
    except Exception as e:
        f.write(u"xml parse error: %r\n" % (e,))
    if not parsed:
        f.write(u"unavailable (no libraries parsed from _full_export.xml)\n")
    f.close()
    log(u"project info written")


def check_version_compat(proj):
    """Abort when the project was saved with a NEWER compiler than the running
    CODESYS: SP17 will 'open' an SP22 file but silently read zero objects."""
    cv = u""
    try:
        cv = unicode(proj.project_settings.get_compilerversion())
    except Exception:
        log(u"version check: get_compilerversion unavailable — skipped")
        return
    exe = u""
    try:
        import System.Diagnostics as _sd
        exe = unicode(_sd.Process.GetCurrentProcess().MainModule.FileName)
    except Exception:
        pass
    pm = re.search(u"3\\.5\\.(\\d+)", cv)
    em = re.search(u"3\\.5\\.(\\d+)", exe)
    log(u"version check: project compiler=%s running=%s" % (cv, exe if exe else u"?"))
    if pm and em and int(pm.group(1)) > int(em.group(1)):
        fatal(u"project saved with CODESYS %s but running installation is older (%s) — "
              u"re-run with a matching CODESYS install (-CodesysExe / -Profile)" % (cv, exe))


try:
    proj = projects.open(PROJ)
    log(u"opened: " + unicode(proj.path))
    check_version_compat(proj)

    apps = []

    def find_apps(o, prefix):
        name = get_name_safe(o)
        full = prefix + u"/" + name if prefix else name
        if is_application(o):
            apps.append((full, o))
            return
        for c in children(o):
            find_apps(c, full)

    for top in proj.get_children():
        find_apps(top, u"")

    log(u"applications found: %d" % len(apps))

    used_top = set()
    for app_full, app_obj in apps:
        app_name = get_name_safe(app_obj)
        top_rel = safe_filename(app_name)
        n = 2
        while top_rel.lower() in used_top:
            top_rel = safe_filename(app_name) + u"_%d" % n
            n += 1
        if top_rel.lower() in used_top or len(apps) > 1:
            log(u"application export root: " + top_rel)
        used_top.add(top_rel.lower())
        abs_top = os.path.join(OUT, top_rel)
        if not os.path.isdir(abs_top):
            os.makedirs(abs_top)
        for c in children(app_obj):
            walk_app(c, app_full + u"/" + get_name_safe(c), top_rel)

    # _folders.txt
    folders = sorted(set(folders))
    f = codecs.open(os.path.join(OUT, u"_folders.txt"), "w", "utf-8")
    for rel in folders:
        f.write(rel + u"\n")
    f.close()
    log(u"folders listed: %d" % len(folders))

    # _index.txt
    index_rows = sorted(index_rows)
    f = codecs.open(os.path.join(OUT, u"_index.txt"), "w", "utf-8")
    for rel, full in index_rows:
        f.write(rel + u"\t" + full + u"\n")
    f.close()
    log(u"index rows: %d" % len(index_rows))

    # _full_export.xml first — _project_info.txt parses libraries from it
    try:
        all_objs = []

        def collect(o):
            all_objs.append(o)
            for c in children(o):
                collect(c)
        for top in proj.get_children():
            collect(top)
        proj.export_xml(all_objs, os.path.join(OUT, u"_full_export.xml"))
        log(u"xml export done")
        # normalize run-varying timestamps so re-export of an unchanged
        # project produces a clean git diff
        try:
            xp = os.path.join(OUT, u"_full_export.xml")
            xf = codecs.open(xp, "r", "utf-8-sig")
            xt = xf.read()
            xf.close()
            xt = re.sub(
                ur'creationDateTime="[^"]*"',
                u'creationDateTime="1970-01-01T00:00:00"', xt)
            xt = xt.replace(u"\r\n", u"\n")
            xf = codecs.open(xp, "w", "utf-8")
            xf.write(xt)
            xf.close()
        except Exception as e:
            log(u"xml timestamp normalize failed: %r" % (e,))
    except Exception as e:
        log(u"xml export failed: %r" % (e,))

    write_project_info(proj, apps)

    log(u"summary: textual objects=%d, folders=%d, skipped nontextual containers=%d" % (
        exported, len(folders), skipped_nontext))

    try:
        proj.close(False)
    except Exception:
        try:
            proj.close()
        except Exception:
            pass
    log(u"done")
except Exception as e:
    log(u"FATAL: %r" % (e,))

logf.close()
