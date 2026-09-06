"""Test bootstrap.

The service modules import as `services.*`, so the repo root has to be
importable. Nothing here touches Supabase or the network: every test in this
suite either exercises pure functions or injects a fake store.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
