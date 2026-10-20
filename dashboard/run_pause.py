"""Pause only the owned worker and its descendants; never the dashboard."""
import psutil

def suspend_tree(pid):
    root = psutil.Process(pid)
    suspended = []
    try:
        root.suspend()
        suspended.append(root)
        for child in root.children(recursive=True):
            try:
                child.suspend()
                suspended.append(child)
            except psutil.NoSuchProcess:
                pass
        return suspended
    except Exception:
        resume_tree(suspended)
        raise

def resume_tree(processes):
    for process in reversed(processes):
        try:
            if process.is_running():
                process.resume()
        except psutil.NoSuchProcess:
            pass
