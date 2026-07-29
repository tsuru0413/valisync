from __future__ import annotations

import threading
from typing import Any


class MdfHandle:
    """開いたままの asammdf MDF と直列化ロックを包む。

    asammdf の select/get は単一の共有 self._file を seek+read するためスレッド
    非安全。グループ内の全 LazyMdfValues はこの lock で読みを直列化する。ハンドルは
    SignalGroup が 1 個所有し、unload/エラー経路で close() する (増分B/M3)。"""

    __slots__ = ("_close_lock", "_closed", "lock", "mdf", "source_path")

    def __init__(self, mdf: Any, source_path: str = "") -> None:
        self.mdf = mdf
        self.lock = threading.Lock()
        # close の check-and-set 専用の小さい lock。読み直列化用の self.lock とは
        # **別物**にする — 同じ lock を使うと、二重 close かどうかを判定するだけの
        # ために in-flight な select の完了を待つことになり GUI が固まる。
        self._close_lock = threading.Lock()
        self._closed = False
        # 遅延読みの失敗診断を「どのファイルの話か」で出すために保持する。
        # ハンドルは 1 ファイル 1 個なので、26 万個の LazyMdfValues 各々に
        # 持たせるより安い (信号側は既に Signal.source_file を持つ)。
        self.source_path = source_path

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """冪等な close (mmap 解放・ファイルロック解除).

        check-and-set は close 専用 lock で不可分にする (並行 close で
        mdf.close() が 2 回走らない)。ただし **フラグを立てるのは self.lock の
        外のまま** — 待たされている reader が「これから閉じるハンドル」を
        is_closed==False と見てはならない (固定ユーザー決定)。
        """
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        # mdf.close() 自体は読み直列化 lock 下で行う: in-flight な select を
        # 中断せず完走させ、mmap の native アクセス違反を防ぐ。
        with self.lock:
            self.mdf.close()
