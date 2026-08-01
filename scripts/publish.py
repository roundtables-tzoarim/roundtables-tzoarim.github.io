#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
עדכון + פרסום בפקודה אחת: מסנכרן מה-Docs ואז דוחף ל-GitHub (ומכאן ל-GitHub Pages).
הרצה: python scripts/publish.py
דורש: git remote בשם origin כבר מוגדר (ראו README/הוראות ההתקנה).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def run(cmd, check=True):
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=check)


def main():
    run([sys.executable, "scripts/sync_content.py"])

    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    if not status.stdout.strip():
        print("אין שינויים חדשים - כלום לא פורסם.")
        return

    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "עדכון תוכן מהמסמך"])
    run(["git", "push"])
    print("פורסם בהצלחה! השינויים יופיעו באתר החי תוך דקה־שתיים.")


if __name__ == "__main__":
    main()
