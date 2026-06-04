"""AIOS entry point — run with: python -m aios [--ui]"""
import sys

if "--ui" in sys.argv:
    from aios.ui import launch_ui
    launch_ui()
else:
    from aios.main import main
    main()
