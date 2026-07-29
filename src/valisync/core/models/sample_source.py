from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from valisync.core.loaders.mdf_handle import MdfHandle


class SampleReadError(Exception):
    """遅延サンプル読み取りが I/O 等で失敗したことを表す (アプリは落とさず degrade).

    ``signal_key`` / ``source_file`` は診断の宛先を決めるための任意コンテキスト。
    app レベルの excepthook は render 境界 (``GraphPanelVM._report_read_error``) と
    同じ規約 — signal_key で「1 信号 1 診断」に dedup し、source_file の basename を
    診断ラベルにする — を再現する必要があるが、フックには例外オブジェクトしか
    届かない (Signal も signal_key も無い) ため、投げ手がここへ載せる。
    """

    def __init__(
        self,
        message: str,
        *,
        signal_key: str | None = None,
        source_file: str | None = None,
    ) -> None:
        super().__init__(message)
        self.signal_key = signal_key
        self.source_file = source_file


@runtime_checkable
class SampleSource(Protocol):
    """Signal の値配列の供給源。EagerValues (即時) と LazyMdfValues (遅延) の共通契約."""

    @property
    def is_materialized(self) -> bool:
        """値配列が既にメモリ上にあるか (mechanism 観測。RSS プロキシではない)."""
        ...

    @property
    def length(self) -> int:
        """サンプル数。値を展開せずに既知 (長さ不変条件の検証に使う)."""
        ...

    @property
    def nbytes_if_materialized(self) -> int:
        """展開済みなら値配列の nbytes、未展開なら 0 (teardown 会計用)."""
        ...

    def array_if_materialized(self) -> np.ndarray | None:
        """展開済みなら値配列、未展開なら None (**展開は誘発しない**).

        nbytes_if_materialized は数値しか返さないので id-dedup ができない。
        teardown 会計が共有配列を二重計上しないために同一性が要る。
        """
        ...

    def array(self) -> np.ndarray:
        """値配列を返す (初回で展開+キャッシュ・read-only 凍結)。失敗時 SampleReadError."""
        ...


def _freeze(array: np.ndarray) -> np.ndarray:
    """現行 Signal.__post_init__ と同一の凍結: writeable ならコピーしてから read-only 化.

    呼び出し側が保持する可変配列を in-place で凍結しない (read-only はそのまま共有)."""
    frozen = array.copy() if array.flags.writeable else array
    frozen.flags.writeable = False
    return frozen


class EagerValues:
    """値配列を即時保持する SampleSource (CSV/Derived/downsampler/offset 前の既定)."""

    __slots__ = ("_array",)

    def __init__(self, array: np.ndarray) -> None:
        self._array = _freeze(array)

    @property
    def is_materialized(self) -> bool:
        return True

    @property
    def length(self) -> int:
        return len(self._array)

    @property
    def nbytes_if_materialized(self) -> int:
        return int(self._array.nbytes)

    def array_if_materialized(self) -> np.ndarray | None:
        """常に展開済み (eager) なので値配列そのものを返す."""
        return self._array

    def array(self) -> np.ndarray:
        return self._array


class LazyMdfValues:
    """MDF から値配列をオンデマンド読みする SampleSource。

    初回 array() で現行 eager と同一意味論の単一チャンネル select を lock 下で実行し、
    LD-14 selector があれば該当リーフ列を抽出、native dtype 凍結してキャッシュする。"""

    __slots__ = ("_cache", "_ci", "_gi", "_handle", "_length", "_name", "_selector")

    def __init__(
        self,
        handle: MdfHandle,
        name: str,
        gi: int,
        ci: int,
        length: int,
        selector: tuple[str, ...] | None = None,
    ) -> None:
        self._handle = handle
        self._name = name
        self._gi = gi
        self._ci = ci
        self._length = length
        self._selector = selector
        self._cache: np.ndarray | None = None

    @property
    def is_materialized(self) -> bool:
        return self._cache is not None

    @property
    def length(self) -> int:
        return self._length

    @property
    def nbytes_if_materialized(self) -> int:
        return 0 if self._cache is None else int(self._cache.nbytes)

    def array_if_materialized(self) -> np.ndarray | None:
        """キャッシュ済みの値配列 (未展開なら None — 読みで展開を誘発しない)."""
        return self._cache

    def _closed_error(self) -> SampleReadError:
        """閉鎖後アクセスのエラー (診断の dedup キー/ラベル付き).

        signal_key は展開列でも**物理チャンネル名** (self._name) にする: LD-14 の
        兄弟リーフは 1 本の select を共有するので、1 本壊れたときは同じ 1 件の
        障害であり、リーフごとに診断を出すのは同じ事実の水増しになる。
        """
        return SampleReadError(
            f"信号 '{self._name}' のファイルは既に閉じられています",
            signal_key=self._name,
            source_file=self._handle.source_path,
        )

    def array(self) -> np.ndarray:
        cached = self._cache
        if cached is not None:
            return cached  # ヒットは lock 不要 (代入は 1 回だけ・GIL 下で atomic)
        if self._handle.is_closed:
            # 先行 bail: close() の GUI 最悪待ちを「残り全列のループ」から
            # 「in-flight select 1 本」に縮める (belt-and-braces)。
            raise self._closed_error()
        # 遅延 import: sample_source(model) -> loaders の循環を避ける
        from valisync.core.loaders.mdf_loader import _flatten

        with self._handle.lock:
            if self._cache is not None:  # ← 削除禁止 (double-checked の "second check")
                return self._cache
            if self._handle.is_closed:  # ← lock 内判定も **維持** (外へ出すと TOCTOU)
                raise self._closed_error()
            try:
                asig = self._handle.mdf.select(
                    [(self._name, self._gi, self._ci)],
                    raw=False,
                    ignore_value2text_conversions=True,
                    copy_master=False,
                )[0]
                samples = asig.samples
                if self._selector is not None:
                    # LD-14: 展開リーフ列を名前一致で取り出す
                    leaf = dict(_flatten(self._name, samples))
                    col = leaf[self._selector[-1]]
                else:
                    col = np.ascontiguousarray(samples)
            except SampleReadError:
                raise
            except Exception as exc:  # I/O・破損・閉鎖後アクセス等
                raise SampleReadError(
                    f"信号 '{self._name}' のサンプル読み取りに失敗しました: {exc}",
                    signal_key=self._name,
                    source_file=self._handle.source_path,
                ) from exc
            col = _freeze(col)
            self._cache = col
            return col
