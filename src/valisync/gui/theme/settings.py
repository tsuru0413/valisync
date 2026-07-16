"""QSettings の org/app 定数 — theme 層の共有点 (spec §11.2)。

main_window.py / recent_files.py の _ORG/_APP と同一値の複製 (それらから
import すると main_window → apply → main_window の循環になるため)。
テスト隔離: tests/{gui,realgui}/conftest.py が本モジュールを monkeypatch する
— ここを経由しない QSettings 書き込みを theme 層に作らないこと。
"""

from __future__ import annotations

_ORG = "ValiSync"
_APP = "ValiSync"
