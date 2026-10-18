# -*- coding: utf-8 -*-
# CODESYS Scripting Engine (IronPython 2.7) — generic project importer, v2.
# Reads target.txt (key=value, UTF-8): path from env CODESYS_SYNC_TARGET,
# falling back to a target.txt next to this script:
#   project = absolute path of the REAL .project/.library to modify
#   indir   = export-root directory (Application/**.st + metadata files)
#   log     = log file path
#
# Input layout (matches export v2):
#   Application/**.st           textual objects (// PATH: header is authority)
#   _folders.txt                real folders to ensure (one rel path per line)
#   structure_ops.txt           structural ops (create/rename/delete/task)
#   _index.txt / _project_info.txt / _full_export.xml   ignored on import
#
# structure_ops.txt grammar (# comment, blank ignored, executed in order):
#   CREATE_POU|<parent-rel>|<name>
#   CREATE_FB|<parent-rel>|<name>[|<baseType>[|<interfaces>]]
#   CREATE_FUN|<parent-rel>|<name>|<returnType>
#   CREATE_DUT|<parent-rel>|<name>|<DutType>[|<baseType>]
#   CREATE_GVL|<parent-rel>|<name>
#   CREATE_FOLDER|<parent-rel>|<name>
#   CREATE_METHOD|<pou-rel>|<name>[|<returnType>]
#   CREATE_PROPERTY|<pou-rel>|<name>[|<returnType>]
#   CREATE_ACTION|<pou-rel>|<name>
#   CREATE_TRANSITION|<pou-rel>|<name>
#   CREATE_TASK|<task-config-rel>|<name>[|<kind>][|<interval>][|<priority>]
#   RENAME|<old-rel-path>|<newName>
#   MOVE|<object rel>|<new parent rel>
#   DELETE|<rel-path>
#   ASSIGN_TO_TASK|<task-rel-path>|<program-rel-path>
#   ADD_LIBRARY|<resolution-string>
# <...-rel> paths start with the Application node name, same as the .st tree.
#
# Safety: project backed up first; every structural op verified; write-verify
# on text; save only when something changed (save_as fallback). Any FATAL
# aborts without save. DELETE refuses if any textual object references the
# name (comments stripped). CLOSE the project in the CODESYS IDE before running.
# Do NOT use Python 3 syntax — this runs inside CODESYS IronPython 2.7.

import codecs
import glob
import os
import re
import shutil
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
INDIR = cfg[u"indir"]
LOG = cfg[u"log"]

DECL_MARK = u"// ===== DECLARATION =====\n"
IMPL_MARK = u"\n// ===== IMPLEMENTATION =====\n"

# system nodes under Application that must not be exported / pruned
SKIP_NAMES = set([u"Library Manager", u"Task Configuration"])

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


log(u"target: project=%s" % PROJ)
log(u"target: indir=%s" % INDIR)


# ---------- object helpers ----------

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


def walk_all(o, prefix, acc):
    full = prefix + u"/" + get_name(o) if prefix else get_name(o)
    if full not in acc:
        acc[full] = o
    for c in children(o):
        walk_all(c, full, acc)
    return acc


def build_index(proj):
    """Index all objects by full PATH. Starts from the project's children
    so keys are Device/... not <ProjectName>/Device/..."""
    acc = {}
    for top in proj.get_children():
        walk_all(top, u"", acc)
    return acc


def find_app(o, want, prefix_acc):
    """Return application object whose name == want (first match)."""
    try:
        if o.is_application and get_name(o) == want:
            return o
    except Exception:
        pass
    for c in children(o):
        r = find_app(c, want, prefix_acc)
        if r is not None:
            return r
    return None


def find_app_fullpath(o, want, prefix):
    name = get_name(o)
    full = prefix + u"/" + name if prefix else name
    try:
        if o.is_application and name == want:
            return full
    except Exception:
        pass
    for c in children(o):
        r = find_app_fullpath(c, want, full)
        if r is not None:
            return r
    return None


def resolve_rel(proj, rel):
    """Resolve export-relative path (starts with Application node name)
    to (full_project_path, object_or_None)."""
    rel = rel.strip().strip(u"/")
    if not rel:
        return u"", None
    seg0, _, rest = rel.partition(u"/")
    app = None
    for top in proj.get_children():
        app = find_app(top, seg0, None)
        if app is not None:
            break
    if app is None:
        return u"", None
    app_full = None
    for top in proj.get_children():
        app_full = find_app_fullpath(top, seg0, u"")
        if app_full is not None:
            break
    if not rest:
        return app_full, app
    full = app_full + u"/" + rest
    by = build_index(proj)
    return full, by.get(full)


def rel_to_full(proj, rel):
    full, _ = resolve_rel(proj, rel)
    return full


def find_all_apps(proj):
    apps = []

    def rec(o, prefix):
        name = get_name(o)
        full = prefix + u"/" + name if prefix else name
        try:
            if o.is_application:
                apps.append((name, full, o))
                return
        except Exception:
            pass
        for c in children(o):
            rec(c, full)
    for top in proj.get_children():
        rec(top, u"")
    return apps


def app_full_to_relbase(app_full, proj):
    """Device/Plc Logic/Application/... -> Application/... (export-relative)."""
    # strip everything up to and including the application node name
    parts = app_full.split(u"/")
    for i, p in enumerate(parts):
        # application segment: match any known app name
        pass
    # simpler: find app boundary by known app node names
    return app_full


def full_to_rel(proj, full):
    """Convert full project PATH to export-relative (Application/...)."""
    apps = find_all_apps(proj)
    for name, app_full, _o in apps:
        if full == app_full:
            return name
        prefix = app_full + u"/"
        if full.startswith(prefix):
            return name + u"/" + full[len(prefix):]
    return full


# ---------- .st parsing ----------

def norm_eol(t):
    if t is None:
        return None
    return t.replace(u"\r\n", u"\n")


def same_text(a, b):
    """Compare ignoring trailing newlines — SP17 doc.text has no trailing
    newline, SP22 may include one; files always end with exactly one."""
    if a is None or b is None:
        return a == b
    return a.rstrip(u"\n") == b.rstrip(u"\n")


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
    if decl.endswith(u"\r\n"):
        decl = decl[:-2]
    return pou_path, decl, impl, guid


def get_text(o, kind):
    try:
        if kind == u"decl" and o.has_textual_declaration:
            t = o.textual_declaration.text
            return norm_eol(unicode(t)) if t else None
        if kind == u"impl" and o.has_textual_implementation:
            t = o.textual_implementation.text
            return norm_eol(unicode(t)) if t else None
    except Exception:
        pass
    return None


def set_text(o, kind, t):
    doc = o.textual_declaration if kind == u"decl" else o.textual_implementation
    try:
        doc.text = t
    except Exception:
        doc.replace(t)
    return same_text(get_text(o, kind), t)


def set_text_direct(o, kind, t):
    """Write even when has_textual_* is still False (freshly created POU)
    and verify by reading the document itself."""
    try:
        doc = o.textual_declaration if kind == u"decl" else o.textual_implementation
    except Exception:
        return False
    try:
        doc.text = t
    except Exception:
        try:
            doc.replace(t)
        except Exception:
            return False
    try:
        return same_text(norm_eol(unicode(doc.text)), t)
    except Exception:
        return False


# ---------- comment strip / reference check ----------

def strip_comments(t):
    t = re.sub(ur"\(\*.*?\*\)", u" ", t, flags=re.S)
    t = re.sub(ur"//[^\n]*", u" ", t)
    return t


def find_textual_refs(proj, symbol):
    """Return list of references (excluding the object named `symbol` itself)
    whose textual bodies mention `symbol`, plus task program instances."""
    pat = re.compile(ur"\b" + re.escape(symbol) + ur"\b")
    refs = []
    by = build_index(proj)
    for path, o in by.items():
        if get_name(o) == symbol:
            continue
        body_parts = []
        d = get_text(o, u"decl")
        if d:
            body_parts.append(d)
        i = get_text(o, u"impl")
        if i:
            body_parts.append(i)
        if not body_parts:
            continue
        if pat.search(strip_comments(u"\n".join(body_parts))):
            refs.append(path)

    # task program-call instances are non-textual references
    def walk_task(o, prefix):
        name = get_name(o)
        full = prefix + u"/" + name if prefix else name
        is_task = False
        try:
            _k = o.kind_of_task
            is_task = True
        except Exception:
            pass
        if is_task:
            for c in children(o):
                if get_name(c) == symbol:
                    refs.append(full + u"/" + symbol + u" (task instance)")
        for c in children(o):
            walk_task(c, full)
    for top in proj.get_children():
        walk_task(top, u"")
    return sorted(refs)


# ---------- structure ops ----------

SKIP_CREATE_TYPES = {}


def child_named(parent, name):
    """Direct child of `parent` with the given name, or None."""
    for c in children(parent):
        if get_name(c) == name:
            return c
    return None


def do_create(proj, op, args, changed_flags):
    import scriptengine as se
    if op == u"CREATE_FOLDER":
        parent_rel, name = args[0], args[1]
        full, parent = resolve_rel(proj, parent_rel)
        if parent is None:
            fatal(u"CREATE_FOLDER parent not found: " + parent_rel)
        if get_name(parent) in (u"Library Manager", u"Task Configuration"):
            fatal(u"CREATE_FOLDER under system node refused: " + parent_rel)
        if child_named(parent, name) is not None:
            log(u"ops: CREATE_FOLDER %s/%s already exists, skipped" % (parent_rel, name))
            return
        parent.create_folder(name)
        # SP17: create_folder returns None — re-find by name
        found = None
        for c in children(parent):
            if get_name(c) == name:
                found = c
                break
        if found is None:
            fatal(u"CREATE_FOLDER verify failed (not found after create): " + name)
        log(u"ops: CREATE_FOLDER %s/%s -> OK" % (parent_rel, name))
        changed_flags[0] = True
        return

    if op in (u"CREATE_POU", u"CREATE_FB", u"CREATE_FUN"):
        parent_rel, name = args[0], args[1]
        full, parent = resolve_rel(proj, parent_rel)
        if parent is None:
            fatal(u"%s parent not found: %s" % (op, parent_rel))
        if child_named(parent, name) is not None:
            log(u"ops: %s %s/%s already exists, skipped" % (op, parent_rel, name))
            return
        try:
            if op == u"CREATE_POU":
                new_o = parent.create_pou(name=name, type=se.PouType.Program, language=None)
            elif op == u"CREATE_FB":
                base = args[2] if len(args) > 2 else u""
                ifaces = args[3] if len(args) > 3 else u""
                if base or ifaces:
                    new_o = parent.create_function_block(
                        name, None, base if base else None, ifaces if ifaces else None)
                else:
                    new_o = parent.create_pou(
                        name=name, type=se.PouType.FunctionBlock, language=None)
            else:
                ret = args[2] if len(args) > 2 else u"BOOL"
                new_o = parent.create_pou(
                    name=name,
                    type=se.PouType.Function,
                    language=None,
                    return_type=ret)
        except Exception as e:
            # FUNCTION via create_pou may not take return_type on this version
            if op == u"CREATE_FUN":
                try:
                    ret = args[2] if len(args) > 2 else u"BOOL"
                    new_o = parent.create_function(name, ret)
                except Exception as e2:
                    fatal(u"%s failed: %r / %r" % (op, (e,), (e2,)))
            else:
                fatal(u"%s failed: %r" % (op, (e,)))
        if new_o is None:
            fatal(u"%s returned None: %s" % (op, name))
        log(u"ops: %s %s/%s -> OK" % (op, parent_rel, name))
        changed_flags[0] = True
        return

    if op == u"ADD_LIBRARY":
        # resolution string as shown in Library Manager, e.g.
        # "SysSocket, 3.5.19.0 (System)"
        res = args[0] if args else u""
        if not res:
            fatal(u"ADD_LIBRARY missing resolution string")
        apps = find_all_apps(proj)
        if not apps:
            fatal(u"ADD_LIBRARY: no application found")
        app = apps[0][2]
        # idempotency: skip when a reference with the same base name exists
        short = res.split(u",")[0].strip()
        existing = set()
        try:
            for c in children(app):
                if get_name(c) == u"Library Manager":
                    for lc in children(c):
                        existing.add(get_name(lc))
        except Exception:
            pass
        for n in existing:
            if n == short or n.endswith(u"/" + short) or n.endswith(u"." + short):
                log(u"ops: ADD_LIBRARY %s already present (%s)" % (res, n))
                changed_flags[0] = changed_flags[0] or False
                return
        lm = app.get_library_manager()
        try:
            lm.add_library(res)
        except Exception as e:
            fatal(u"ADD_LIBRARY failed (%s): %r" % (res, (e,)))
        log(u"ops: ADD_LIBRARY %s -> OK" % res)
        changed_flags[0] = True
        return

    if op == u"CREATE_DUT":
        parent_rel, name = args[0], args[1]
        dut_type_s = args[2] if len(args) > 2 else u"Structure"
        base = args[3] if len(args) > 3 else None
        full, parent = resolve_rel(proj, parent_rel)
        if parent is None:
            fatal(u"CREATE_DUT parent not found: " + parent_rel)
        if child_named(parent, name) is not None:
            log(u"ops: CREATE_DUT %s/%s already exists, skipped" % (parent_rel, name))
            return
        tmap = {
            u"Structure": se.DutType.Structure,
            u"Enumeration": se.DutType.Enumeration,
            u"Alias": se.DutType.Alias,
            u"Union": se.DutType.Union,
        }
        dt = tmap.get(dut_type_s)
        if dt is None:
            fatal(u"CREATE_DUT unknown type: " + dut_type_s)
        try:
            if base:
                new_o = parent.create_dut(name, dt, base)
            else:
                new_o = parent.create_dut(name, dt)
        except Exception as e:
            fatal(u"CREATE_DUT failed: %r" % ((e,),))
        if new_o is None:
            fatal(u"CREATE_DUT returned None: " + name)
        log(u"ops: CREATE_DUT %s/%s (%s) -> OK" % (parent_rel, name, dut_type_s))
        changed_flags[0] = True
        return

    if op == u"CREATE_GVL":
        parent_rel, name = args[0], args[1]
        full, parent = resolve_rel(proj, parent_rel)
        if parent is None:
            fatal(u"CREATE_GVL parent not found: " + parent_rel)
        if child_named(parent, name) is not None:
            log(u"ops: CREATE_GVL %s/%s already exists, skipped" % (parent_rel, name))
            return
        try:
            new_o = parent.create_gvl(name)
        except Exception as e:
            fatal(u"CREATE_GVL failed: %r" % ((e,),))
        if new_o is None:
            fatal(u"CREATE_GVL returned None: " + name)
        log(u"ops: CREATE_GVL %s/%s -> OK" % (parent_rel, name))
        changed_flags[0] = True
        return

    if op in (u"CREATE_METHOD", u"CREATE_PROPERTY", u"CREATE_ACTION", u"CREATE_TRANSITION"):
        parent_rel, name = args[0], args[1]
        ret = args[2] if len(args) > 2 else None
        full, parent = resolve_rel(proj, parent_rel)
        if parent is None:
            fatal(u"%s parent not found: %s" % (op, parent_rel))
        if child_named(parent, name) is not None:
            log(u"ops: %s %s/%s already exists, skipped" % (op, parent_rel, name))
            return
        try:
            if op == u"CREATE_METHOD":
                new_o = parent.create_method(name, ret, None)
            elif op == u"CREATE_PROPERTY":
                new_o = parent.create_property(name, ret if ret else u"BOOL", None)
            elif op == u"CREATE_ACTION":
                new_o = parent.create_action(name, None)
            else:
                new_o = parent.create_transition(name, None)
        except Exception as e:
            fatal(u"%s failed: %r" % (op, (e,)))
        if new_o is None:
            fatal(u"%s returned None: %s" % (op, name))
        log(u"ops: %s %s/%s -> OK" % (op, parent_rel, name))
        changed_flags[0] = True
        return

    if op == u"CREATE_TASK":
        # CREATE_TASK|<task config path>|<name>[|<kind>][|<interval>][|<priority>]
        # e.g. CREATE_TASK|Application/Task Configuration|CommTask|Cyclic|t#20ms|2
        tc_rel, name = args[0], args[1]
        kind = args[2] if len(args) > 2 else u""
        interval = args[3] if len(args) > 3 else u""
        prio = args[4] if len(args) > 4 else u""
        full, tc = resolve_rel(proj, tc_rel)
        if tc is None:
            # fresh scripted applications have no Task Configuration node —
            # create it on the application and re-resolve
            app_rel = tc_rel.split(u"/", 1)[0]
            _af, app = resolve_rel(proj, app_rel)
            if app is not None:
                try:
                    app.create_task_configuration()
                    log(u"ops: CREATE_TASK task-config auto-created on %s" % app_rel)
                except Exception as e:
                    log(u"ops: create_task_configuration failed: %r" % (e,))
                full, tc = resolve_rel(proj, tc_rel)
        if tc is None:
            fatal(u"CREATE_TASK task-config not found: " + tc_rel)
        if child_named(tc, name) is not None:
            log(u"ops: CREATE_TASK %s/%s already exists, skipped" % (tc_rel, name))
            return
        try:
            t = tc.create_task(name)
        except Exception as e:
            fatal(u"CREATE_TASK failed: %r" % ((e,),))
        if t is None:
            fatal(u"CREATE_TASK returned None: " + name)
        # apply settings (defaults from create_task are Cyclic/t#4ms/1)
        if kind:
            try:
                t.kind_of_task = getattr(se.KindOfTask, kind)
            except Exception as e:
                log(u"CREATE_TASK kind set failed (%s): %r" % (kind, (e,)))
        if interval:
            try:
                t.interval = interval
            except Exception as e:
                log(u"CREATE_TASK interval set failed (%s): %r" % (interval, (e,)))
        if prio:
            try:
                t.priority = int(prio)
            except Exception:
                try:
                    # SP17 quirk: priority setter sometimes wants a string
                    t.priority = unicode(prio)
                except Exception as e:
                    log(u"CREATE_TASK priority set failed (%s): %r" % (prio, (e,)))
        # verify it appears under the task configuration
        found = False
        for c in children(tc):
            if get_name(c) == name:
                found = True
                break
        if not found:
            fatal(u"CREATE_TASK verify failed (not under " + tc_rel + u")")
        log(u"ops: CREATE_TASK %s/%s OK (kind=%s interval=%s prio=%s)" % (
            tc_rel, name,
            kind if kind else u"default",
            interval if interval else u"default",
            prio if prio else u"default"))
        changed_flags[0] = True
        return

    fatal(u"unknown create op: " + op)


def migrate_st_rename(proj, old_full, new_full):
    """After obj.rename: update .st PATH headers (object + children) and
    move the file / same-named child directory inside indir."""
    old_rel = full_to_rel(proj, old_full)
    new_rel = full_to_rel(proj, new_full)
    # update PATH headers of the object itself and of all children
    for root, dirs, files in os.walk(INDIR):
        for fn in files:
            if not fn.endswith(u".st"):
                continue
            fp = os.path.join(root, fn)
            try:
                f = codecs.open(fp, "r", "utf-8-sig")
                text = f.read()
                f.close()
            except Exception:
                continue
            if not text.startswith(u"// PATH: "):
                continue
            eol = text.index(u"\n")
            path_in_file = text[len(u"// PATH: "):eol].strip()
            if path_in_file == old_full:
                new_path = new_full
            elif path_in_file.startswith(old_full + u"/"):
                new_path = new_full + path_in_file[len(old_full):]
            else:
                continue
            text = (u"// PATH: " + new_path + text[eol:])
            f = codecs.open(fp, "w", "utf-8")
            f.write(text)
            f.close()
            log(u"ops: st PATH updated: %s -> %s" % (path_in_file, new_path))
    # move file
    old_disk = os.path.join(INDIR, old_rel + u".st")
    new_disk = os.path.join(INDIR, new_rel + u".st")
    if os.path.normpath(old_disk) != os.path.normpath(new_disk):
        ndir = os.path.dirname(new_disk)
        if ndir and not os.path.isdir(ndir):
            os.makedirs(ndir)
        if os.path.isfile(old_disk):
            shutil.move(old_disk, new_disk)
            log(u"ops: st file moved: %s -> %s" % (old_rel, new_rel))
    # move same-named child directory (methods/properties)
    old_sub = os.path.join(INDIR, old_rel)
    new_sub = os.path.join(INDIR, new_rel)
    if os.path.isdir(old_sub):
        if not os.path.isdir(new_sub):
            shutil.move(old_sub, new_sub)
            log(u"ops: st subdir moved: %s/ -> %s/" % (old_rel, new_rel))


def apply_rename(proj, obj, old_full, new_name, rewrite_disk_st=True):
    """Rename obj, migrate on-disk .st (if any left at old path), and
    word-boundary rewrite textual references (SP17 rename() does not)."""
    old_name = get_name(obj)
    try:
        obj.rename(new_name)
    except Exception as e:
        fatal(u"RENAME failed (%s -> %s): %r" % (old_full, new_name, (e,)))
    new_full = old_full.rsplit(u"/", 1)[0] + u"/" + new_name
    by = build_index(proj)
    if new_full not in by:
        fatal(u"RENAME verify failed (missing %s)" % new_full)
    migrate_st_rename(proj, old_full, new_full)
    pat = re.compile(ur"\b" + re.escape(old_name) + ur"\b")
    n_refs = 0
    by = build_index(proj)
    for path, ro in by.items():
        if path == new_full:
            continue
        for kind in (u"decl", u"impl"):
            cur = get_text(ro, kind)
            if not cur or not pat.search(strip_comments(cur)):
                continue
            newt = pat.sub(new_name, cur)
            if not set_text_direct(ro, kind, newt):
                fatal(u"reference rewrite failed on %s (%s)" % (path, kind))
            n_refs += 1
            log(u"ops: reference rewritten: %s (%s)" % (path, kind))
    if rewrite_disk_st:
        for root, dirs, files in os.walk(INDIR):
            for fn in files:
                if not fn.endswith(u".st"):
                    continue
                fp = os.path.join(root, fn)
                try:
                    f = codecs.open(fp, "r", "utf-8-sig")
                    txt = f.read()
                    f.close()
                except Exception:
                    continue
                if not pat.search(strip_comments(txt)):
                    continue
                txt2 = pat.sub(new_name, txt)
                f = codecs.open(fp, "w", "utf-8")
                f.write(txt2)
                f.close()
                log(u"ops: st body rewritten: " + fp)
    log(u"ops: RENAME %s -> %s OK (%d project refs rewritten)" % (
        old_full, new_name, n_refs))
    return new_full


def check_staleness(cfg, proj_path):
    """FATAL when the .project was modified after the last successful
    export/import (so manual IDE edits cannot be silently overwritten)."""
    if cfg.get(u"force") in (u"1", u"true", u"True", u"yes"):
        log(u"staleness: skipped (-Force)")
        return
    lastexport = cfg.get(u"lastexport", u"")
    if not lastexport or not os.path.isfile(lastexport):
        log(u"staleness: no last-export stamp recorded — skipped")
        return
    try:
        proj_mtime = os.path.getmtime(proj_path)
        stamp_mtime = os.path.getmtime(lastexport)
    except Exception as e:
        log(u"staleness: mtime read failed: %r" % (e,))
        return
    if proj_mtime > stamp_mtime + 2.0:
        fatal(u"project file was modified after the last export/import "
              u"(mtime newer than stamp) — run export.ps1 first to refresh "
              u"the .st tree, then import (or pass -Force to override)")
    log(u"staleness: ok (project mtime <= last export stamp)")


def stamp_lastexport(cfg):
    """Record 'texts now match project' after a successful import run."""
    lastexport = cfg.get(u"lastexport", u"")
    if not lastexport:
        return
    try:
        d = os.path.dirname(lastexport)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        f = codecs.open(lastexport, "w", "utf-8")
        f.write(u"stamped=%s\n" % time.strftime("%Y-%m-%dT%H:%M:%S"))
        f.close()
        log(u"last-export stamp updated: " + lastexport)
    except Exception as e:
        log(u"last-export stamp FAILED: %r" % (e,))


def sync_autocreate(proj, st_files_info, changed_flags):
    """-Sync: create textual objects present in .st files but missing in the
    project (refactor drift: AI added a POU on the export side)."""
    import scriptengine as se
    by = build_index(proj)
    created = 0
    for fname, (pou_path, decl, impl, guid) in st_files_info:
        if pou_path in by:
            continue
        seg0, _, rest = pou_path.partition(u"/")
        if not rest:
            log(u"sync: cannot create top-level " + pou_path)
            continue
        parent_path = pou_path.rsplit(u"/", 1)[0]
        parent = by.get(parent_path)
        if parent is None:
            log(u"sync: parent not found, skip create: " + pou_path)
            continue
        name = pou_path.rsplit(u"/", 1)[1]
        d = decl.strip()
        try:
            if d.startswith(u"PROGRAM "):
                parent.create_pou(name=name, type=se.PouType.Program, language=None)
            elif d.startswith(u"FUNCTION_BLOCK "):
                parent.create_pou(name=name, type=se.PouType.FunctionBlock, language=None)
            elif d.startswith(u"FUNCTION "):
                m = re.match(ur"FUNCTION\s+\S+\s*:\s*(\S+)", d)
                ret = m.group(1) if m else u"BOOL"
                try:
                    parent.create_pou(name=name, type=se.PouType.Function,
                                      language=None, return_type=ret)
                except Exception:
                    parent.create_function(name, ret)
            elif d.startswith(u"TYPE "):
                if re.search(ur"\bENUM\b", d.split(u"END_TYPE")[0], flags=re.I):
                    parent.create_dut(name, se.DutType.Enumeration)
                else:
                    parent.create_dut(name, se.DutType.Structure)
            elif d.startswith(u"VAR_GLOBAL"):
                parent.create_gvl(name)
            elif d.startswith(u"METHOD "):
                m = re.match(ur"METHOD\s+\S+\s*:\s*(\S+)", d)
                ret = m.group(1) if m else None
                parent.create_method(name, ret, None)
            else:
                log(u"sync: unknown decl kind, skip create: " + pou_path)
                continue
        except Exception as e:
            fatal(u"sync: create failed for %s: %r" % (pou_path, (e,)))
        log(u"sync: created " + pou_path)
        created += 1
        changed_flags[0] = True
    if created:
        # refresh index for later phases
        pass
    log(u"sync autocreate: %d" % created)


def sync_prune(proj, st_paths, changed_flags):
    """-Sync: delete Application-level textual objects that no longer appear
    in the export tree (refactor drift: POU removed on the export side).
    Zero-reference protection applies; protected objects are skipped."""
    # collect project textual paths (Application subtree, skip system nodes)
    proj_paths = []

    def walk(o, full_path):
        name = get_name(o)
        if name in SKIP_NAMES:
            return
        textual = has_text_ref(o, u"decl") or has_text_ref(o, u"impl")
        kids = children(o)
        if textual:
            proj_paths.append(full_path)
        for c in kids:
            walk(c, full_path + u"/" + get_name(c))
    apps = find_all_apps(proj)
    for app_name, app_full, app_obj in apps:
        for c in children(app_obj):
            walk(c, app_full + u"/" + get_name(c))
    st_set = set(st_paths)
    pruned = 0
    skipped = 0
    for p in proj_paths:
        if p in st_set:
            continue
        full, obj = resolve_rel(proj, full_to_rel(proj, p))
        if obj is None:
            continue
        name = get_name(obj)
        refs = find_textual_refs(proj, name)
        # exclude nothing: refs include task instances
        if refs:
            log(u"sync: prune skipped (refs): %s <- %s" % (p, u"; ".join(refs[:4])))
            skipped += 1
            continue
        rel_disk = full_to_rel(proj, p)
        try:
            obj.remove()
        except Exception as e:
            log(u"sync: prune FAILED %s: %r" % (p, (e,)))
            skipped += 1
            continue
        st = os.path.join(INDIR, rel_disk + u".st")
        if os.path.isfile(st):
            try:
                os.remove(st)
            except Exception:
                pass
        sub = os.path.join(INDIR, rel_disk)
        if os.path.isdir(sub):
            try:
                shutil.rmtree(sub)
            except Exception:
                pass
        log(u"sync: pruned " + p)
        pruned += 1
        changed_flags[0] = True
    log(u"sync prune: deleted=%d skipped=%d" % (pruned, skipped))


def has_text_ref(o, kind):
    try:
        if kind == u"decl" and o.has_textual_declaration:
            return True
        if kind == u"impl" and o.has_textual_implementation:
            return True
    except Exception:
        pass
    return False


def do_ops(proj, changed_flags):
    ops_path = os.path.join(INDIR, u"structure_ops.txt")
    if not os.path.isfile(ops_path):
        log(u"no structure_ops.txt — skipping structural ops")
        return 0
    f = codecs.open(ops_path, "r", "utf-8-sig")
    raw_lines = f.read().splitlines()
    f.close()
    n = 0
    for lineno, ln in enumerate(raw_lines, 1):
        s = ln.strip()
        if not s or s.startswith(u"#"):
            continue
        parts = s.split(u"|")
        op = parts[0].strip().upper()
        args = [p.strip() for p in parts[1:]]
        try:
            if op in (u"CREATE_POU", u"CREATE_FB", u"CREATE_FUN", u"CREATE_DUT",
                      u"CREATE_GVL", u"CREATE_FOLDER", u"CREATE_METHOD", u"CREATE_PROPERTY",
                      u"CREATE_ACTION", u"CREATE_TRANSITION", u"CREATE_TASK", u"ADD_LIBRARY"):
                need = 1 if op == u"ADD_LIBRARY" else 2
                if len(args) < need:
                    fatal(u"ops line %d: not enough args: %s" % (lineno, s))
                do_create(proj, op, args, changed_flags)
            elif op == u"RENAME":
                old_rel, new_name = args[0], args[1]
                old_full, obj = resolve_rel(proj, old_rel)
                if obj is None:
                    fatal(u"ops line %d: RENAME target not found: %s" % (lineno, old_rel))
                apply_rename(proj, obj, old_full, new_name)
                changed_flags[0] = True
            elif op == u"DELETE":
                rel = args[0]
                full, obj = resolve_rel(proj, rel)
                if obj is None:
                    fatal(u"ops line %d: DELETE target not found: %s" % (lineno, rel))
                name = get_name(obj)
                refs = find_textual_refs(proj, name)
                if refs:
                    fatal(u"ops line %d: DELETE refused, %d textual refs: %s" % (
                        lineno, len(refs), u"; ".join(refs[:8])))
                try:
                    obj.remove()
                except Exception as e:
                    fatal(u"ops line %d: DELETE failed: %r" % (lineno, (e,)))
                by = build_index(proj)
                if full in by:
                    fatal(u"ops line %d: DELETE verify failed (still present)" % lineno)
                # remove matching .st / subtree on disk
                rel_disk = full_to_rel(proj, full)
                st = os.path.join(INDIR, rel_disk + u".st")
                if os.path.isfile(st):
                    os.remove(st)
                sub = os.path.join(INDIR, rel_disk)
                if os.path.isdir(sub):
                    shutil.rmtree(sub)
                log(u"ops: DELETE %s -> OK" % rel)
                changed_flags[0] = True
            elif op == u"ASSIGN_TO_TASK":
                task_rel, prog_rel = args[0], args[1]
                _tf, task = resolve_rel(proj, task_rel)
                _pf, prog = resolve_rel(proj, prog_rel)
                if task is None:
                    fatal(u"ops line %d: task not found: %s" % (lineno, task_rel))
                if prog is None:
                    fatal(u"ops line %d: program not found: %s" % (lineno, prog_rel))
                prog_name = get_name(prog)
                if child_named(task, prog_name) is not None:
                    log(u"ops: ASSIGN_TO_TASK %s += %s already assigned, skipped"
                        % (task_rel, prog_rel))
                    n += 1
                    continue
                # SP17 ScriptPouObjectList.add() takes the program NAME (str)
                try:
                    task.pous.add(prog_name)
                except Exception as e1:
                    fatal(u"ops line %d: ASSIGN_TO_TASK add failed: %r" % (lineno, (e1,)))
                # verify: a pou-instance child with that name now exists
                found = False
                for c in children(task):
                    if get_name(c) == prog_name:
                        found = True
                        break
                if not found:
                    fatal(u"ops line %d: ASSIGN_TO_TASK verify failed (no instance %s under task)"
                          % (lineno, prog_name))
                log(u"ops: ASSIGN_TO_TASK %s += %s OK" % (task_rel, prog_rel))
                changed_flags[0] = True
            elif op == u"MOVE":
                # MOVE|<object path>|<new parent path> - move an object into another folder
                src_rel, dst_rel = args[0], args[1]
                src_full, src_obj = resolve_rel(proj, src_rel)
                dst_full, dst_obj = resolve_rel(proj, dst_rel)
                if src_obj is None:
                    fatal(u"ops line %d: MOVE source not found: %s" % (lineno, src_rel))
                if dst_obj is None:
                    fatal(u"ops line %d: MOVE target folder not found: %s" % (lineno, dst_rel))
                try:
                    src_obj.move(dst_obj)
                except Exception as e:
                    fatal(u"ops line %d: MOVE failed: %r" % (lineno, (e,)))
                new_rel = dst_rel + u"/" + get_name(src_obj)
                new_full = dst_full + u"/" + get_name(src_obj)
                _nf, check = resolve_rel(proj, new_rel)
                if check is None:
                    fatal(u"ops line %d: MOVE verify failed (missing %s)" % (lineno, new_rel))
                # move matching .st (+ child dir) inside indir and fix PATH headers
                old_disk = os.path.join(INDIR, src_rel + u".st")
                new_disk = os.path.join(INDIR, new_rel + u".st")
                if os.path.isfile(old_disk):
                    ndir = os.path.dirname(new_disk)
                    if ndir and not os.path.isdir(ndir):
                        os.makedirs(ndir)
                    shutil.move(old_disk, new_disk)
                    try:
                        f = codecs.open(new_disk, "r", "utf-8-sig")
                        txt = f.read()
                        f.close()
                        txt = txt.replace(u"// PATH: " + src_full,
                                          u"// PATH: " + new_full)
                        f = codecs.open(new_disk, "w", "utf-8")
                        f.write(txt)
                        f.close()
                    except Exception as e:
                        log(u"MOVE: st PATH update failed: %r" % (e,))
                old_sub = os.path.join(INDIR, src_rel)
                new_sub = os.path.join(INDIR, new_rel)
                if os.path.isdir(old_sub) and not os.path.isdir(new_sub):
                    shutil.move(old_sub, new_sub)
                log(u"ops: MOVE %s -> %s OK" % (src_rel, new_rel))
                changed_flags[0] = True
            else:
                fatal(u"ops line %d: unknown op %s" % (lineno, op))
            n += 1
        except SystemExit:
            raise
        except Exception as e:
            fatal(u"ops line %d: %r" % (lineno, (e,)))
    log(u"ops applied: %d" % n)
    return n


def ensure_folders(proj, changed_flags):
    path = os.path.join(INDIR, u"_folders.txt")
    if not os.path.isfile(path):
        log(u"no _folders.txt — skipping folder sync")
        return
    f = codecs.open(path, "r", "utf-8-sig")
    lines = [l.strip() for l in f.read().splitlines()]
    f.close()
    for rel in lines:
        if not rel or rel.startswith(u"#"):
            continue
        parts = [p for p in rel.split(u"/") if p]
        if len(parts) < 2:
            continue
        # walk segment by segment, creating missing folders
        cur_rel = parts[0]
        _, cur = resolve_rel(proj, cur_rel)
        if cur is None:
            log(u"folders: app not found for " + rel)
            continue
        for seg in parts[1:]:
            nxt_rel = cur_rel + u"/" + seg
            _, nxt = resolve_rel(proj, nxt_rel)
            if nxt is None:
                cur.create_folder(seg)
                _, nxt = resolve_rel(proj, nxt_rel)
                if nxt is None:
                    fatal(u"folders: create/verify failed: " + nxt_rel)
                log(u"folders: created " + nxt_rel)
                changed_flags[0] = True
            cur = nxt
            cur_rel = nxt_rel
    log(u"folders synced")


# ---------- main ----------

# ---------- version guard ----------

def check_version_compat(proj):
    """Abort when the project was saved with a NEWER compiler than the running
    CODESYS (older IDE reads nothing / could damage the project)."""
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
    # old-layout guard
    old_flat = glob.glob(os.path.join(INDIR, u"[0-9][0-9][0-9]_*.txt"))
    if old_flat:
        fatal(u"old flat layout detected (%d NNN_*.txt files) — re-export with codesys-sync v2 first"
              % len(old_flat))

    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = PROJ + u"." + ts + u".bak"
    shutil.copy(PROJ, bak)
    log(u"backup: " + bak)

    proj = projects.open(PROJ)
    log(u"opened: " + unicode(proj.path))
    check_version_compat(proj)
    check_staleness(cfg, PROJ)

    changed_flags = [False]

    # structural phase
    do_ops(proj, changed_flags)
    ensure_folders(proj, changed_flags)

    # text phase: recursive *.st
    st_files = []
    for root, dirs, files in os.walk(INDIR):
        for fn in files:
            if fn.endswith(u".st"):
                st_files.append(os.path.join(root, fn))
    st_files.sort()
    st_files_info = []
    path_files = {}
    for fname in st_files:
        parsed = parse_st(fname)
        if parsed is None:
            log(u"WARNING: unparseable .st skipped: " + fname)
            continue
        st_files_info.append((fname, parsed))
        pou_path = parsed[0]
        path_files.setdefault(pou_path, []).append(fname)
    log(u"st files scanned: %d" % len(st_files_info))

    # duplicate PATH guard: two .st claiming the same object would silently
    # overwrite each other (last writer wins — a known data-loss trap)
    dups = dict((k, v) for k, v in path_files.items() if len(v) > 1)
    if dups:
        for pou_path, flist in sorted(dups.items()):
            log(u"DUPLICATE PATH: " + pou_path)
            for fp in flist:
                log(u"  - " + fp)
        fatal(u"%d object PATH(s) claimed by multiple .st files — "
              u"delete the stale copies (see log) before importing" % len(dups))

    # -Sync: create objects that exist only on the export side
    if cfg.get(u"sync") in (u"1", u"true", u"True", u"yes"):
        sync_autocreate(proj, st_files_info, changed_flags)

    by = build_index(proj)
    log(u"objects total: %d" % len(by))

    changed = 0
    warnings = 0
    matched = 0
    for fname, _preparsed in st_files_info:
        # always re-parse: a GUID rename mid-loop rewrites .st files on disk,
        # and writing back a stale pre-rename parse would clobber the rewrite
        parsed = parse_st(fname)
        if parsed is None:
            log(u"WARNING: unparseable .st skipped: " + fname)
            warnings += 1
            continue
        pou_path, decl, impl, guid = parsed
        o = by.get(pou_path)
        if o is None and guid:
            # GUID fingerprint match = the object was renamed/moved locally
            for path, cand in by.items():
                try:
                    if unicode(cand.guid) == guid:
                        o = cand
                        new_name = pou_path.rsplit(u"/", 1)[1]
                        if get_name(cand) != new_name:
                            log(u"rename detected by GUID: %s -> %s" % (path, new_name))
                            apply_rename(proj, cand, path, new_name)
                            by = build_index(proj)
                            o = by.get(pou_path)
                        break
                except Exception:
                    continue
        if o is None:
            log(u"WARNING: object not found in project, skipped: " + pou_path)
            warnings += 1
            continue
        matched += 1
        obj_changed = False
        for kind, new_text in ((u"decl", decl), (u"impl", impl)):
            cur = get_text(o, kind)
            if cur is None:
                if new_text.strip() == u"":
                    continue
                # freshly created POU: impl/decl doc may not be flagged ready
                if set_text_direct(o, kind, new_text):
                    obj_changed = True
                    log(u"written (doc was unset): %s (%s)" % (pou_path, kind))
                    continue
                log(u"WARNING: %s has no textual %s, skipped" % (pou_path, kind))
                warnings += 1
                continue
            if not same_text(cur, new_text):
                if not set_text(o, kind, new_text):
                    fatal(u"write-verify failed on %s (%s) - aborting WITHOUT save"
                          % (pou_path, kind))
                obj_changed = True
        if obj_changed:
            changed += 1
            log(u"updated: " + pou_path)

    # -Sync: prune textual objects that no longer appear in the export tree
    if cfg.get(u"sync") in (u"1", u"true", u"True", u"yes"):
        st_paths = [p for _f, (p, _d, _i, _g) in st_files_info]
        sync_prune(proj, st_paths, changed_flags)

    log(u"text objects updated: %d, warnings: %d" % (changed, warnings))

    if st_files_info and matched == 0:
        fatal(u"%d .st file(s) scanned but none matched a project object — "
              u"check the // PATH: headers (they must be FULL paths, e.g. "
              u"'Device/Plc Logic/Application/...', not export-relative)"
              % len(st_files_info))

    anything = changed_flags[0] or changed > 0
    if anything:
        saved = False
        try:
            proj.save()
            log(u"saved")
            saved = True
        except Exception as e:
            log(u"save() failed (%r), trying save_as + file replace" % (e,))
        if not saved:
            root, ext = os.path.splitext(PROJ)
            tmp = root + u".tmp_save" + ext
            proj.save_as(tmp)
            try:
                proj.close()
            except Exception:
                pass
            shutil.copy(tmp, PROJ)
            os.remove(tmp)
            log(u"saved (save_as + replace)")
    else:
        log(u"no changes - project NOT saved")

    # project and export tree are in sync again — refresh the stamp
    stamp_lastexport(cfg)

    try:
        proj.close(False)
    except Exception:
        try:
            proj.close()
        except Exception:
            pass
    log(u"done")
except SystemExit:
    log(u"ABORTED - project file untouched (backup still created)")
except Exception as e:
    log(u"FATAL: %r" % (e,))

logf.close()
