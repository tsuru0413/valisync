from __future__ import annotations

import threading
from typing import Any


class MdfHandle:
    """開いたままの asammdf MDF と直列化ロックを包む。

    asammdf の select/get は単一の共有 self._file を seek+read するためスレッド
    非安全。グループ内の全 LazyMdfValues はこの lock で読みを直列化する。ハンドルは
    SignalGroup が 1 個所有し、unload/エラー経路で close() する (増分B/M3)。"""

    __slots__ = ("_closed", "lock", "mdf")

    def __init__(self, mdf: Any) -> None:
        self.mdf = mdf
        self.lock = threading.Lock()
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """冪等な close (mmap 解放・ファイルロック解除)."""
        if self._closed:
            return
        self._closed = True
        with self.lock:
            self.mdf.close()
