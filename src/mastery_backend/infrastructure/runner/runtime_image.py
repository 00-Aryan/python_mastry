"""Curated operator-built runtime and explicit native syscall policy, never learner supplied."""

import ctypes
import errno
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Native x86_64 Python startup, file I/O, JSON and clocks. No process/network/namespace APIs.
SYSCALLS = """read write close openat newfstatat fstat stat lstat statx access faccessat
faccessat2 lseek pread64 pwrite64 readv writev mmap mprotect munmap mremap madvise brk
rt_sigaction rt_sigprocmask rt_sigreturn sigaltstack arch_prctl set_tid_address
set_robust_list rseq prlimit64 getrandom fcntl flock getdents64 getcwd readlink readlinkat
execve exit exit_group getuid geteuid getgid getegid getpid getppid gettid clock_gettime
clock_nanosleep nanosleep futex sched_getaffinity sched_yield uname getrusage sysinfo
wait4 waitid poll ppoll select pselect6 dup dup2 dup3 ftruncate truncate unlink unlinkat
mkdir mkdirat
rmdir rename renameat renameat2 fsync fdatasync umask chdir fchdir ioctl
""".split()
# ioctl is required by CPython isatty; disallow TIOCSTI with no tty/new session.


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_seccomp(path: Path) -> None:
    if platform.machine() != "x86_64":
        raise RuntimeError("Only the reviewed x86_64 syscall profile is supported")
    library = ctypes.CDLL("libseccomp.so.2")
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    library.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x00050000 | errno.EPERM)
    if not context:
        raise RuntimeError("Cannot initialize seccomp")
    try:
        for name in SYSCALLS:
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number < 0 or library.seccomp_rule_add(context, 0x7FFF0000, number, 0) != 0:
                raise RuntimeError("Cannot build seccomp allowlist")
        with path.open("wb") as output:
            if library.seccomp_export_bpf(context, output.fileno()) != 0:
                raise RuntimeError("Cannot export seccomp profile")
    finally:
        library.seccomp_release(context)


def build_runtime(directory: Path) -> None:
    if directory.exists():
        raise ValueError("Runtime directory must be new")
    if sys.version_info[:2] != (3, 12) or os.getuid() == 0:
        raise RuntimeError("Runtime builder requires non-root Python 3.12")
    directory.mkdir(mode=0o700, parents=True)
    image = directory / "image"
    (image / "runtime/bin").mkdir(parents=True)
    (image / "runtime/lib").mkdir()
    for name in ("proc", "dev", "tmp"):
        (image / name).mkdir()
    interpreter = Path(sys.base_prefix) / "bin/python3.12"
    shutil.copy2(interpreter.resolve(), image / "runtime/bin/python")
    stdlib = Path(sys.base_prefix) / "lib/python3.12"
    shutil.copytree(
        stdlib,
        image / "runtime/lib/python3.12",
        ignore=shutil.ignore_patterns(
            "site-packages", "__pycache__", "test", "tests", "idlelib", "tkinter", "ensurepip"
        ),
    )
    shutil.copy2(Path(__file__).with_name("sandbox_bootstrap.py"), image / "bootstrap.py")
    executables = [image / "runtime/bin/python", *image.rglob("*.so")]
    dependencies: set[Path] = set()
    for executable in executables:
        result = subprocess.run(
            ["/usr/bin/ldd", str(executable)], capture_output=True, text=True, check=True
        )
        for match in re.findall(r"(/[^\s()]+)", result.stdout):
            dependencies.add(Path(match))
    for dependency in sorted(dependencies):
        target = image / dependency.relative_to("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dependency.resolve(), target)
        if dependency.name.startswith("libpython"):
            shutil.copy2(dependency.resolve(), image / "runtime/lib" / dependency.name)
    profile = directory / "seccomp.bpf"
    write_seccomp(profile)
    profile.chmod(0o400)
    for path in image.rglob("*"):
        path.chmod(0o500 if path.is_dir() or path.stat().st_mode & 0o111 else 0o400)
    image.chmod(0o500)
    manifest = {
        str(path.relative_to(image)): sha256_file(path)
        for path in sorted(image.rglob("*"))
        if path.is_file()
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
    (directory / "manifest.json").chmod(0o400)


def verify_runtime(directory: Path) -> tuple[str, str]:
    image = directory / "image"
    manifest_bytes = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict) or len(manifest) > 5000:
        raise RuntimeError("Invalid runtime manifest")
    actual = set()
    for path in [image, *image.rglob("*")]:
        metadata = path.lstat()
        if path.is_symlink() or metadata.st_uid != os.getuid() or metadata.st_mode & 0o222:
            raise RuntimeError("Runtime must be owned, sealed and contain no symlinks")
        if path.is_file():
            relative = str(path.relative_to(image))
            actual.add(relative)
            if manifest.get(relative) != sha256_file(path):
                raise RuntimeError("Runtime integrity mismatch")
        elif not path.is_dir():
            raise RuntimeError("Runtime contains a special file")
    if actual != set(manifest):
        raise RuntimeError("Runtime inventory mismatch")
    profile = directory / "seccomp.bpf"
    if (
        profile.is_symlink()
        or profile.stat().st_uid != os.getuid()
        or profile.stat().st_mode & 0o222
    ):
        raise RuntimeError("Seccomp profile must be sealed")
    return hashlib.sha256(manifest_bytes).hexdigest(), hashlib.sha256(
        profile.read_bytes()
        + Path(__file__).with_name("sandbox_launcher.py").read_bytes()
        + Path(__file__).with_name("local_sandbox.py").read_bytes()
    ).hexdigest()
