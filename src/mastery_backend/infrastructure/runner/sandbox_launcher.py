"""Trusted standalone launcher: systemd cannot pass an inherited seccomp descriptor."""

import os
import sys


def main() -> None:
    image, profile = sys.argv[1:]
    descriptor = os.open(profile, os.O_RDONLY)
    os.set_inheritable(descriptor, True)
    os.execve(
        "/usr/bin/bwrap",
        [
            "bwrap",
            "--unshare-all",
            "--unshare-user",
            "--die-with-parent",
            "--new-session",
            "--uid",
            "1000",
            "--gid",
            "1000",
            "--cap-drop",
            "ALL",
            "--disable-userns",
            "--clearenv",
            "--ro-bind",
            image,
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            "1048576",
            "--tmpfs",
            "/tmp",
            "--setenv",
            "LD_LIBRARY_PATH",
            "/runtime/lib",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--seccomp",
            str(descriptor),
            "--chdir",
            "/tmp",
            "--",
            "/runtime/bin/python",
            "-I",
            "-B",
            "/bootstrap.py",
        ],
        {"PATH": "/usr/bin:/bin"},
    )


if __name__ == "__main__":
    main()
