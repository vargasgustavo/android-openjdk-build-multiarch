#!/usr/bin/env python3
"""
Idempotent source ports for building JDK 25 (jdk-25+36) for aarch64-linux-android.

The Bionic patch set lives in a single jdk21-era diff
(patches/jre_25/android/jdk21u_android.diff) applied with `git apply --reject`.
Against the JDK 25 tree a handful of hunks reject purely due to context drift.
This script re-applies, against the *actual* JDK 25 source, only the hunks that
are real compile blockers on Bionic. It runs from 6_buildjdk.sh with cwd=openjdk,
AFTER the big patch has been applied and BEFORE ./configure.

Every edit checks first and is safe to run twice.
"""
import os
import sys

CHANGED = []


def read(path):
    with open(path, "r", encoding="utf-8", errors="surrogateescape") as f:
        return f.read()


def write(path, s):
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write(s)
    CHANGED.append(path)


def replace_once(path, name, old, new, must_be_unique=True):
    if not os.path.exists(path):
        print(f"PORT: MISSING {path} (skip '{name}')", flush=True)
        return
    s = read(path)
    if new in s and old not in s:
        print(f"PORT: {path}: '{name}' already applied", flush=True)
        return
    cnt = s.count(old)
    if cnt == 0:
        print(f"PORT: {path}: '{name}' anchor NOT FOUND (skip)", flush=True)
        return
    if must_be_unique and cnt != 1:
        print(f"PORT: {path}: '{name}' anchor ambiguous (count={cnt}) - ABORT", flush=True)
        sys.exit(2)
    write(path, s.replace(old, new, 1))
    print(f"PORT: {path}: '{name}' applied", flush=True)


# 1) os_linux.cpp - Bionic has no dlvsym(); enable the fallback shim (used by the
#    libnuma loader) for __ANDROID__ as well as MUSL. Without this the shim is not
#    compiled and dlvsym() is an undeclared identifier -> hard compile error.
OSL = "src/hotspot/os/linux/os_linux.cpp"
replace_once(
    OSL, "dlvsym-ifdef",
    "#ifdef MUSL_LIBC\n// dlvsym is not a part of POSIX",
    "#if defined(MUSL_LIBC) || defined(__ANDROID__)\n// dlvsym is not a part of POSIX",
)
replace_once(
    OSL, "dlvsym-linkage",
    "static void *dlvsym(void *handle,",
    "void *dlvsym(void *handle,",
)

# 2) threadLS_linux_aarch64.S - the applied hunk opens `#ifndef __ANDROID__` right
#    after `#include "defs.S.inc"` to exclude the asm thread helper on Android, but
#    the matching `#endif` hunk rejected (JDK 25 appended a .note.gnu.property block
#    that shifted the tail). That leaves an unterminated #ifndef -> assembler error.
#    Close it immediately after the helper's `.size` directive.
TLS = "src/hotspot/os_cpu/linux_aarch64/threadLS_linux_aarch64.S"
if os.path.exists(TLS):
    s = read(TLS)
    if "#ifndef __ANDROID__" not in s:
        print(f"PORT: {TLS}: opening '#ifndef __ANDROID__' absent - skip", flush=True)
    else:
        n_if = s.count("#if")      # matches #if / #ifdef / #ifndef (not #endif/#else)
        n_end = s.count("#endif")
        if n_end >= n_if:
            print(f"PORT: {TLS}: already balanced (#if={n_if} #endif={n_end}) - skip", flush=True)
        else:
            lines = s.split("\n")
            marker = ".size _ZN10JavaThread25aarch64_get_thread_helperEv"
            hits = [i for i, l in enumerate(lines) if marker in l]
            if len(hits) != 1:
                print(f"PORT: {TLS}: .size marker count={len(hits)} - ABORT", flush=True)
                sys.exit(2)
            i = hits[0]
            lines.insert(i + 1, "#endif")
            write(TLS, "\n".join(lines))
            print(f"PORT: {TLS}: inserted #endif after helper (#if={n_if} #endif->{n_end + 1})", flush=True)
else:
    print(f"PORT: MISSING {TLS}", flush=True)

if CHANGED:
    print("PORT: files written: " + ", ".join(sorted(set(CHANGED))), flush=True)
print("PORT: done", flush=True)
