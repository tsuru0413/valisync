import os

# Set Qt platform to offscreen before Qt is imported.
# This allows Qt-based tests to run in headless environments (CI, remote sessions).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
