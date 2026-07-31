from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # 実行時 import は不要 (注釈は from __future__ で文字列化済み)。
    from valisync.core.loaders.channel_cache import ChannelSampleCache


class MdfHandle:
    """開いたままの asammdf MDF と直列化ロックを包む。

    asammdf の select/get は単一の共有 self._file を seek+read するためスレッド
    非安全。グループ内の全 LazyMdfValues はこの lock で読みを直列化する。ハンドルは
    SignalGroup が 1 個所有し、unload/エラー経路で close() する (増分B/M3)。"""

    __slots__ = ("_close_lock", "_closed", "cache", "lock", "mdf", "source_path")

    def __init__(
        self,
        mdf: Any,
        source_path: str = "",
        cache: ChannelSampleCache | None = None,
    ) -> None:
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
        # E-4a: デコード済みチャンネル 2-D のプロセス単位 LRU (所有は Session)。
        # ハンドルに提げるのは、LazyMdfValues が既に handle しか持たないから —
        # 信号 26 万個に別の参照を配らずに全列へ届く唯一の場所である。
        # None ならキャッシュ無し = E-3 と同一挙動 (MdfLoader を直接使う経路)。
        self.cache = cache

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
        # 予算の返却は読み直列化 lock の**外**で行う: キャッシュは自前の lock で
        # 守られているので、in-flight な select の完了を待つ理由が無い。
        # 通常の unload はここへ来る前に remove_group が drop_handle() で回収済み
        # なので空振りする — 回収されない close (ローダーのエラー/キャンセル経路)
        # でエントリが恒久滞留するのを防ぐのがここの役目。キーは id(self) なので、
        # 残すと予算が目減りするだけでなく id 再利用時に別ファイルの配列を引く。
        #
        # 呼ぶのは drop_handle ではなく release_handle: close には回収した配列を
        # 手渡す相手が居ないので、ここは**同期解放**である。返り値を捨てる形にすると
        # その事実がコードから読めなくなる (回収 = teardown 行きは remove_group の側)。
        #
        # **None ガードは必須** (省略不可): cache は任意で、MdfLoader を引数なしで
        # 使う経路 — ローダー単体テスト・load() のエラー/キャンセル経路の finally・
        # MdfHandle(_FakeMdf()) — が全て cache=None のまま close() を呼ぶ。
        if self.cache is not None:
            self.cache.release_handle(id(self))
        # mdf.close() 自体は読み直列化 lock 下で行う: in-flight な select を
        # 中断せず完走させ、mmap の native アクセス違反を防ぐ。
        with self.lock:
            self.mdf.close()
