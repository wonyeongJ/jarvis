"""Filesystem actions triggered from the chat UI.

These helpers wrap platform-specific file operations so widgets and the main
window can reuse the same behavior.
"""

import os
import shutil
import subprocess


def open_path(path):
    """Open a file or folder with the operating system default handler."""
    if os.path.isdir(path):
        subprocess.Popen(["explorer", path])
    else:
        os.startfile(path)


def open_parent_folder(path):
    """Open the containing folder for a file path or the folder itself."""
    target = path if os.path.isdir(path) else os.path.dirname(path)
    subprocess.Popen(["explorer", target])
    return target


def copy_path_to_desktop(path):
    """Copy a file or folder to the current user's desktop."""
    desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    name = os.path.basename(path)
    base, ext = os.path.splitext(name)
    destination = os.path.join(desktop_dir, name)
    counter = 1

    while os.path.exists(destination):
        destination = os.path.join(desktop_dir, f"{base} ({counter}){ext}")
        counter += 1

    if os.path.isdir(path):
        shutil.copytree(path, destination)
    else:
        shutil.copy2(path, destination)

    return destination


def move_path_to_recycle_bin(path):
    """Move a file or folder to the recycle bin."""
    try:
        import send2trash  # type: ignore

        send2trash.send2trash(path)
    except ImportError:
        powershell_command = (
            "Add-Type -AssemblyName Microsoft.VisualBasic; "
            f"[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('{path}',"
            "'OnlyErrorDialogs','SendToRecycleBin')"
        )
        subprocess.run(
            ["powershell", "-Command", powershell_command],
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=True,
        )
