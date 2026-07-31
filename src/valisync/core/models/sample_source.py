from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from valisync.core.loaders.column_names import ColumnPath
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
    LD-14 の位置パスがあれば該当リーフ列を抽出、native dtype 凍結してキャッシュする。
    デコード済みのチャンネル 2-D は handle が持つ ChannelSampleCache で同一
    チャンネルの全列が共有する (E-4a) — 兄弟列の 2 本目以降は select を呼ばない。"""

    __slots__ = (
        "_cache",
        "_ci",
        "_gi",
        "_handle",
        "_length",
        "_name",
        "_path",
        "_selector",
    )

    def __init__(
        self,
        handle: MdfHandle,
        name: str,
        gi: int,
        ci: int,
        length: int,
        selector: tuple[str, ...] | None = None,
        path: ColumnPath | None = None,
    ) -> None:
        if (selector is None) != (path is None):
            # 片方だけ渡せる形にすると、列が容器分岐 (2-D 丸ごと) を通って
            # 「例外の出ない誤データ」になる。名前 (永続キー) と位置 (ロードごとに
            # 導出) は同じ 1 本のリーフの両面なので、対でしか受けない。
            raise ValueError("selector と path は対で渡すこと (列の名前と位置)")
        self._handle = handle
        self._name = name
        self._gi = gi
        self._ci = ci
        self._length = length
        # 名前は **永続キーのまま**保つ (LD-14 リーフ名・spec §5.6)。読みには使わ
        # なくなったが、診断とオラクル (test_mdf_loader_lazy) の宛先として残す。
        self._selector = selector
        # リーフへの位置。位置引きにすると読みが _flatten の全リーフ辞書を作らずに
        # 済む (幅 1,100 のチャンネルで 1/1,100 の仕事)。
        self._path = path
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
        channel_cache = self._handle.cache
        key = (id(self._handle), self._gi, self._ci)
        # E-4a: デコード済みチャンネル 2-D は同一チャンネルの全列で共有する。
        # ここで **lock を取らない** のが要点 (spec §5.8) — ヒットの意味は
        # 「ファイルに触らない」なので、他スレッドの in-flight select
        # (prod 実測 316 ms) を待つ理由が無い。取るとエクスポート中の再描画が
        # キャッシュに載っている列でも固まる。
        if channel_cache is not None:
            shared = channel_cache.get(key)
            if shared is not None:
                return self._column_of(shared)
        with self._handle.lock:
            if self._cache is not None:  # ← 削除禁止 (double-checked の "second check")
                return self._cache
            if self._handle.is_closed:  # ← lock 内判定も **維持** (外へ出すと TOCTOU)
                raise self._closed_error()
            # lock 内で channel_cache を引き直さないのは、1 回の読みで miss を
            # 二重計上しないため (misses == select 回数 が ①gate の観測点)。
            # 代償は「同一チャンネルの別列を **同時に** 読み始めた」稀なケースで
            # select が 1 本余分に走ること (値は同じ・正しさには影響しない)。
            try:
                asig = self._handle.mdf.select(
                    [(self._name, self._gi, self._ci)],
                    raw=False,
                    ignore_value2text_conversions=True,
                    copy_master=False,
                )[0]
                samples = asig.samples
            except Exception as exc:  # I/O・破損・閉鎖後アクセス等
                raise SampleReadError(
                    f"信号 '{self._name}' のサンプル読み取りに失敗しました: {exc}",
                    signal_key=self._name,
                    source_file=self._handle.source_path,
                ) from exc
            # 共有する前に read-only 化する: 以後この配列は同一チャンネルの全列が
            # 同時に見るので、書ける配列を配ると 1 列の in-place 変更が全列へ伝播
            # する。キャッシュ未配線の構成でも同じ経路を通す (分岐を作ると、テストが
            # production と違う道を測ることになる)。
            #
            # **``put`` より前**であることが要件 (T1 レビュー): 容器パス
            # (スカラー/物理チャンネル全体) は _column_of で ``_freeze`` を素通り
            # させて共有実体をそのまま Signal の値にする。後ろへ回すと ``_freeze`` が
            # コピーし、キャッシュ (コピーも凍結もしない契約) と Signal が同じ内容を
            # 2 本抱える = 予算 2 倍。詳細と会計上の帰結は _column_of の docstring。
            samples.flags.writeable = False
            col = self._column_of(samples)  # 長さ不変条件もこの中で執行する
            if channel_cache is not None and (samples.ndim > 1 or samples.dtype.names):
                # put は **長さ検証を通った後**。壊れた読みを共有キャッシュへ
                # 焼き付けると、同じチャンネルの全列が以後その配列を見る。
                # 予算超のエントリは載らない (put が False・spec D7) が、
                # 呼び出し側から見た値の意味は変わらない。
                #
                # **スカラー (1-D かつ非構造化) チャンネルは意図的にキャッシュしない**
                # (レビュー I4): そのチャンネルの容器 Signal と「列」は同一の
                # LazyMdfValues インスタンスを指す — ``_mint_column`` は
                # ``rest == ""`` で None を返すので第 2 の読み手が存在しない。
                # つまりこのエントリは construction 上二度と ``get()`` で引かれず、
                # 載せても LRU が evict しても実 RSS は 1 バイトも動かない
                # 「実効ゼロの死蔵エントリ」になるだけ。prod (4,324 物理チャンネル)
                # の大半はスカラーなので、これを載せ続けると 256 MB 予算がその死蔵
                # エントリで埋まり、実際に兄弟列を持つ広幅 2-D エントリを押し出す
                # うえ ``bytes_held`` が「evict すれば解放できるバイト数」を過大に
                # 報告する。``Mono`` (2-D・幅 1) は引き続き載る — 兄弟列
                # (``Mono[0]``) が実在し、命中パステストの前提はここに依存する。
                channel_cache.put(key, samples)
            return col

    def _column_of(self, samples: np.ndarray) -> np.ndarray:
        """チャンネルの 2-D から自分の列を切り出し、検証・凍結してキャッシュする。

        **返す配列は共有 2-D のビューであってはならない** (spec §5.4)。ビューを
        ``_cache`` へ焼き付けると (a) LRU が evict しても列 Signal が base 経由で
        チャンネル全体を生かし RSS が 1 バイトも下がらず (b)
        ``nbytes_if_materialized`` がビュー自身の nbytes を返すので teardown の
        バイト軸が実体の 1/1000 を計上する。``_freeze`` は **read-only 入力を
        素通しする** ので、この責務は ``apply_path`` 側の copy (T1 の契約) が負う
        — 凍結は守ってくれない。

        逆に、その素通し性のおかげで**列読みのコピーは 1 回で済む**: ``apply_path``
        は自分が作った配列を read-only にして返す契約なので、下の ``_freeze(col)``
        は**何もコピーしない**。ここを「凍結していない配列が来るかもしれない」と
        読んで明示 copy を足したり、``apply_path`` 側の凍結を外したりすると、
        E-4a が縮めようとしているホットパスで毎列 2x のアロケーション + memcpy に
        戻る (値のテストは両方とも緑のままなので、数字にも現れない)。

        **「``_freeze`` が何もコピーしない」が成立する条件は経路で違う** (T1 レビュー
        指摘・無条件に読まないこと):

        - **列パス** (``self._path`` あり) — ``apply_path`` が自分で作った独立配列を
          read-only で返すので素通し。コピーは ``apply_path`` の中の 1 回だけ。
        - **容器パス** (``self._path`` が None = スカラー/物理チャンネル全体) —
          ``apply_path`` の空パス分岐と同じく「呼び出し側の配列をそのまま返す」形に
          なる。素通しになるのは ``array()`` が **``put`` より前に ``samples`` を
          read-only 化している**からで、その 1 行が無いと ``_freeze`` がコピーし、
          キャッシュ (「コピーも凍結もしない」契約) と Signal が同じ内容を 2 本
          抱える = **スカラーチャンネル 1 本につきバイト予算 2 倍**になる (列を
          1 本しか持たないチャンネルなので、キャッシュから得るものは何も無い)。
          実測: 凍結を ``put`` の後ろへ回すと ``Signal.values is 載せた配列`` が
          False になり ``bytes_held + nbytes_if_materialized`` が実体の 2 倍を刷る。

        帰結として容器パスでは **キャッシュと Signal が 1 本のバッファを共有する**。
        よって ``ChannelSampleCache.bytes_held`` と ``nbytes_if_materialized`` は
        その分を二重に数えるが、実 RSS は常にその和より小さい (安全側の過大計上)
        うえ、``TeardownService._retained_bytes`` の ``id()`` dedup が同一エントリ内で
        畳む。**容器の値は共有実体なので ``values.base`` は非 None になりうる**
        (asammdf の ``samples`` 自身が base を持つ — 実測 ``Wide (3,12) uint8``)。
        spec §5.4 の「base を持たない」不変条件は **列にだけ** 課すもので、容器へ
        広げてはならない (広げると production が満たせない条件をテストが要求する)。
        """
        try:
            if self._path is not None:
                # 遅延 import: sample_source(model) -> loaders の循環を避ける
                from valisync.core.loaders.column_names import apply_path

                col = apply_path(samples, self._path)
            else:
                # 容器 (物理チャンネル全体) を読む器。連続なら共有実体をそのまま
                # 指すが、これは「チャンネル全部を持つ Signal」なので会計は正しい
                # (列の 1/1000 計上とは別物)。
                col = np.ascontiguousarray(samples)
            if len(col) != self._length:
                # 長さ不変条件の**唯一の執行点**: Signal.__post_init__ は展開を
                # 避けるため source.length (= 宣言値 len(master)) しか見ないので、
                # follower のレコード数が master とずれる仮想グループ (v4.20+
                # remote-master/column-storage) は構築時検証を通り抜ける。render の
                # ts[lo:hi] / vs[lo:hi] は numpy が黙って clamp するため、ここで
                # 止めないと「エラーにならない誤った波形」になる。**2 つのキャッシュ
                # のどちらへ入れるより前**に投げて、壊れた列も壊れたチャンネルも
                # 焼き付けない。try 内に置くのは、想定外の形状 (0-d 等) で len() が
                # TypeError になっても下の except Exception が SampleReadError へ
                # 包み、degrade 機構の外へ漏らさないため。
                raise SampleReadError(
                    f"信号 '{self._name}' のサンプル数が宣言と一致しません "
                    f"(宣言 {self._length} / 読み取り {len(col)})",
                    signal_key=self._name,
                    source_file=self._handle.source_path,
                )
        except SampleReadError:
            raise
        except Exception as exc:  # 形状不整合・パス不整合等
            raise SampleReadError(
                f"信号 '{self._name}' のサンプル読み取りに失敗しました: {exc}",
                signal_key=self._name,
                source_file=self._handle.source_path,
            ) from exc
        col = _freeze(col)
        self._cache = col
        return col
