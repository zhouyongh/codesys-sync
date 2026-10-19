# -*- coding: utf-8 -*-
# probe_version.py - open a project WITHOUT saving and print its last-saved
# compiler version (project_settings.get_compilerversion).
# target.txt keys: project=, result=   (env CODESYS_SYNC_TARGET or script-adjacent)

import os
import traceback
import codecs

TARGET = os.environ.get("CODESYS_SYNC_TARGET") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "target.txt")


def load_cfg(path):
    cfg = {}
    f = open(path, "r")
    try:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    finally:
        f.close()
    return cfg


def main():
    cfg = load_cfg(TARGET)
    proj_path = cfg.get("project", "")
    result_path = cfg.get("result", "")
    out = []
    try:
        proj = projects.open(proj_path)
        try:
            cv = u"%s" % proj.project_settings.get_compilerversion()
        except Exception:
            cv = u""
        out.append(u"compiler_version=%s" % cv)
    except Exception:
        out.append(u"error=%s" % traceback.format_exc().replace("\n", " | "))
    if result_path:
        f = codecs.open(result_path, "w", "utf-8")
        try:
            f.write(u"\n".join(out) + u"\n")
        finally:
            f.close()


main()
