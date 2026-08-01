from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from valisync.core.downsampler.downsampler import Downsampler
from valisync.core.export.csv_exporter import (
    EXPORT_CONTAINER_CHANNEL_ERROR_TMPL,
    CsvExporter,
    CsvExportOptions,
    ExportRequest,
    passthrough_header_names,
)
from valisync.core.export.legacy_bridge import export_via_legacy_path
from valisync.core.formula.engine import FormulaEngine
from valisync.core.interpolation.interpolator import InterpolationMethod, Interpolator
from valisync.core.loaders.channel_cache import ChannelSampleCache
from valisync.core.loaders.csv_loader import CsvLoader
from valisync.core.loaders.mdf_loader import MdfLoader
from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR, SignalGroupManager
from valisync.core.models import FormatDefinition, Signal, SignalGroup
from valisync.core.models.load_result import Diagnostic, LoadCancelled
from valisync.core.statistics.range_stats import RangeStatistics, StatisticsResult
from valisync.core.sync.synchronizer import TimeSynchronizer

__all__ = [
    "LoadCancelled",
    "LoadError",
    "LoadManyResult",
    "LoadOutcome",
    "RemovalResult",
    "Session",
    "SourceInfo",
]


class LoadError(Exception):
    """Raised when a single-file load fails; carries the loader diagnostics."""

    def __init__(
        self,
        file_path: Path,
        messages: list[str],
        diagnostics: tuple[Diagnostic, ...] = (),
    ) -> None:
        self.file_path = file_path
        self.messages = messages
        self.diagnostics = tuple(diagnostics)
        super().__init__(f"{file_path} の読み込みに失敗しました: {'; '.join(messages)}")


@dataclass(frozen=True)
class LoadOutcome:
    """Result of a successful single-file load: group key + loader diagnostics.

    ``diagnostics`` surfaces non-fatal issues (skipped channels, dropped enum
    labels, 0-channel files) that the GUI shows in the Diagnostics dock (FB-02).
    """

    key: str
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class LoadManyResult:
    """Outcome of a batch load: ``succeeded`` is a tuple of ``LoadOutcome`` (Req 5.4)."""

    succeeded: tuple[LoadOutcome, ...] = ()
    failed: tuple[tuple[Path, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class RemovalResult:
    """Outcome of a remove_group request (Req 4.5).

    ``removed`` is False when dependent Derived_Signals exist and removal was not
    forced; ``dependent_signals`` then names the blocking Derived_Signals.
    ``removed_group`` carries the popped Signal_Group on success so the GUI can
    defer its dealloc off the UI thread (FU-16); None when removal was refused.
    ``removed_columns`` carries the group's minted column Signals (E-1), which
    live outside ``SignalGroup.signals`` and would otherwise escape the teardown
    accounting.
    ``cached_arrays`` carries the decoded channel arrays recovered from the
    ``ChannelSampleCache`` (E-4a). ``removed_columns`` cannot carry them: those
    are raw ndarrays, not Signals. 1 本 13.2 MB (prod の広幅チャンネル) なので、
    ここで渡さないと teardown の三軸ペーシングを丸ごと迂回する。
    """

    removed: bool
    dependent_signals: tuple[str, ...] = ()
    removed_group: SignalGroup | None = None
    removed_columns: tuple[Signal, ...] = ()
    cached_arrays: tuple[np.ndarray, ...] = ()


@dataclass(frozen=True)
class SourceInfo:
    """Read-only metadata of a loaded file for GUI surfaces (FB-10 tooltip).

    ``size_bytes`` is None when the file no longer exists on disk;
    ``t_min``/``t_max`` are None for 0-channel groups.
    """

    full_path: Path
    size_bytes: int | None
    t_min: float | None
    t_max: float | None
    n_channels: int
    file_format: str


@dataclass(frozen=True)
class _DerivedRecord:
    """A Derived_Signal and the namespaced input signal names it depends on."""

    name: str
    input_names: frozenset[str] = field(default_factory=frozenset)


class Session:
    """Orchestration layer. The single gateway between the GUI and core modules.

    Coordinates loaders, synchronizer, formula engine, interpolation, statistics,
    downsampler and export, and manages loaded Signal_Groups by key.
    """

    def __init__(
        self,
        cache_budget_bytes: int | None = None,
        column_capacity: int | None = None,
    ) -> None:
        # column_capacity は鋳造列 LRU の容量注入 (テスト/①gate 用・T2 の
        # cache_budget_bytes と同型で、D6 の「予算を注入して小さくする」)。
        # None は production 既定。
        if column_capacity is None:
            self._groups = SignalGroupManager()
        else:
            self._groups = SignalGroupManager(resolved_capacity=column_capacity)
        self._csv_loader = CsvLoader()
        # E-4a: デコード済みチャンネル 2-D の LRU。**Session が 1 個だけ持つ** —
        # 予算 (U3: 256 MB) の裁定者を 1 人にするため (spec §5.2)。ローダーは
        # これを MdfHandle へ提げるだけで所有しない。
        #
        # cache_budget_bytes は予算の注入口 (テスト / realgui ①gate 用・D6
        # 「予算を注入して小さくする」)。**setter ではなくコンストラクタ引数**に
        # するのが要点: この __init__ が MdfLoader へ渡した時点で MdfLoader._cache が
        # このオブジェクトを捕捉し、MdfHandle はロード時にそれを提げる。
        # LazyMdfValues.array() が見るのは self._handle.cache なので、後から
        # session.channel_cache へ別インスタンスを差し込んでも **誰もそれを書かない**
        # (misses も bytes_held も 0 のまま = 予算注入が構造的に成立しない)。
        # 同じ理由で channel_cache に setter は置かない。
        self._channel_cache = (
            ChannelSampleCache()
            if cache_budget_bytes is None
            else ChannelSampleCache(budget_bytes=cache_budget_bytes)
        )
        self._mdf_loader = MdfLoader(cache=self._channel_cache)
        self._formula = FormulaEngine()
        self._synchronizer = TimeSynchronizer()
        self._interpolator = Interpolator()
        self._statistics = RangeStatistics()
        self._downsampler = Downsampler()
        self._exporter = CsvExporter()
        self._derived: list[_DerivedRecord] = []

    @property
    def channel_cache(self) -> ChannelSampleCache:
        """チャンネル 2-D の共有 LRU (鋳造も読みも誘発しない introspection)。

        hits/misses/evictions/skipped_oversize/bytes_held は計測器 (E-4a の
        出口表) と realgui ①gate の観測点。「select 回数」を数える口は他に無い。

        **setter は無い** (``__init__`` の WHY 参照): 差し替えても既にロード済み /
        これからロードする ``MdfHandle`` は ``MdfLoader`` が捕捉した旧インスタンスを
        提げるので、注入した新キャッシュには 1 バイトも載らない。予算を変えたい
        呼び出し側は ``Session(cache_budget_bytes=...)`` を使う。
        """
        return self._channel_cache

    def load(
        self,
        file_path: Path,
        format_def: FormatDefinition | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> LoadOutcome:
        """Load a file and return the group key plus any loader diagnostics.

        Dispatches to the CSV or MDF4 loader by file type. Raises LoadError when
        the loader reports failure. ``cancel`` is a cooperative callback the
        loader polls at checkpoints; when it returns True the loader raises
        LoadCancelled and no group is registered (FB-04 — user-initiated, not
        an error).
        """
        file_path = Path(file_path)
        if self._csv_loader.supports(file_path):
            if format_def is None:
                raise ValueError("CSV の読み込みにはフォーマット定義が必要です")
            result = self._csv_loader.load(file_path, format_def, cancel=cancel)
        elif self._mdf_loader.supports(file_path):
            result = self._mdf_loader.load(file_path, cancel=cancel)
        else:
            raise ValueError(f"対応していないファイル形式です: {file_path}")

        if result.signal_group is None:
            messages = [d.message for d in result.diagnostics]
            raise LoadError(file_path, messages, diagnostics=result.diagnostics)
        try:
            key = self._groups.add(
                result.signal_group, column_records=result.column_records
            )
        except Exception:
            # 登録に失敗したグループは誰も所有しない。handle を閉じないと
            # トレースバックが生かし続け、GUI のエラーダイアログ表示中ずっと
            # ファイルがロックされる。ローダー自身の失敗経路 (mdf_loader の
            # cancel/例外時) は signal_group=None を返すので上の early return
            # で抜けており、ここに来るのは group が実在する場合のみ — 二重
            # close にはならない (MdfHandle.close() は冪等だが、それに頼らず
            # 所有権の切れ目をここに一本化する)。
            handle = result.signal_group.handle
            if handle is not None:
                handle.close()
            raise
        return LoadOutcome(key=key, diagnostics=result.diagnostics)

    def is_csv(self, file_path: Path) -> bool:
        """*file_path* が CSV ローダー対象かを返す (GUI の開く経路分岐用・LD-01)。"""
        return self._csv_loader.supports(Path(file_path))

    def load_many(
        self, specs: list[tuple[Path, FormatDefinition | None]]
    ) -> LoadManyResult:
        """Load several files, keeping successes available and reporting failures.

        A failure on one file never aborts the batch (Req 5.4): each successful
        load is registered, each failure is reported with its diagnostics.
        """
        succeeded: list[LoadOutcome] = []
        failed: list[tuple[Path, tuple[str, ...]]] = []
        for file_path, format_def in specs:
            try:
                succeeded.append(self.load(file_path, format_def))
            except LoadError as exc:
                failed.append((Path(file_path), tuple(exc.messages)))
            except ValueError as exc:
                failed.append((Path(file_path), (str(exc),)))
        return LoadManyResult(succeeded=tuple(succeeded), failed=tuple(failed))

    def signals(self) -> list[Signal]:
        """Every loaded signal, name-spaced by its group key.

        シェルの列挙は安価だが **``Signal.values`` は遅延 I/O backed** (MDF は
        ``LazyMdfValues``) — この戻り値を回して全信号の ``.values`` に触ると
        ファイル全体を実体化する (遅延ロードで取り除いた回帰そのもの)。
        """
        return self._groups.signals()

    def signal_map(self) -> Mapping[str, Signal]:
        """Read-only ``{namespaced_name: Signal}`` view over all loaded signals.

        Cached at the SignalGroupManager level and rebuilt only on load/unload
        (FU-08) — callers on the autofit hot path avoid re-walking every signal.

        **非対称 Mapping** (意図的逸脱): ルックアップ (``[]``/``get``/``in``) は
        列キーを解決器経由で鋳造しうるが、列挙 (``__iter__``/``len``) は**物理キー
        のみ**を返す。``dict(session.signal_map())``・``.items()``・``.values()``
        による全キー列挙は**してはならない** — 330k 列を鋳造して ~390 MB を再導入
        する (この増分で取り除いた回帰そのもの)。詳細は
        ``SignalGroupManager.signal_map()`` / ``_ResolvingMap`` を参照。
        """
        return self._groups.signal_map()

    def group_keys(self) -> list[str]:
        """Keys of all loaded groups, in insertion order.

        Delegates to SignalGroupManager.keys. Lets callers test whether a
        namespaced signal_key's group is still loaded without walking every
        signal (FU-16: prune reconciliation avoids forcing a namespaced
        rebuild at prod scale).
        """
        return self._groups.keys

    def source_name(self, key: str) -> str:
        """Original source filename (basename) for the group under ``key``.

        Public recovery point so the GUI never reaches into Session internals
        to display a file's name. Raises KeyError for an unknown key.
        """
        return self._groups.source_name(key)

    def group_signals(self, key: str) -> list[Signal]:
        """Namespaced signals for a single loaded file (KeyError if unknown).

        Lets callers fetch one file's signals without scanning every group.
        """
        return self._groups.group_signals(key)

    def resolve_signal(self, key: str) -> Signal | None:
        """名前空間つきキーを Signal へ解決する (列キーは要求時に鋳造・E-1)."""
        return self._groups.resolve(key)

    def column_names_of(self, key: str, display_name: str) -> tuple[str, ...]:
        """物理チャンネル 1 本の列名を順序どおり返す (名前空間なし・E-3)。

        GUI が「その物理チャンネルにどんな列があるか」を知る唯一の口。
        鋳造 (``resolve_signal``) を誘発しないので、展開していない親にも使える。
        """
        return self._groups.column_names_of(key, display_name)

    def total_column_count(self, key: str) -> int:
        """グループの数値列総数 (KeyError if unknown)。表示件数の母数 (U2)。"""
        return self._groups.total_column_count(key)

    def has_column(self, key: str, display_name: str) -> bool:
        """*display_name* の列がこのグループに実在するか (鋳造しない存在判定)。

        ``resolve_signal`` と違い副テーブルへ何も残さない — 「表示のためだけに列を
        登録する」経路を作らないための口。E-4a で LRU が入ったので鋳造列の恒久滞留は
        なくなったが、非 pin の枠を食ってプロット中でない列を押し出す (spec §5.5)。
        """
        return self._groups.has_column(key, display_name)

    def set_pinned_columns(self, keys: Iterable[str]) -> None:
        """今 pin すべき列キー集合を差し替える (GUI が push する・E-4a spec §5.5)。

        pin 済みの鋳造列は LRU の evict 対象外になる。予算を超えても**拒否しない**
        (拒否するとプロット中の列が落ちて再描画ごとに 316 ms 停止が復活する) —
        超過は :meth:`pinned_column_overflow` で観測する。
        """
        self._groups.set_pinned_columns(keys)
        # spec §5.2「予算の裁定者は 1 人」の実配線。pin した列は所有権不変条件
        # (spec §5.4) により**自前の独立配列**を抱えるので、チャンネル 2-D と同じ
        # U3 256 MB を食う。ここを繋がないと ChannelSampleCache.set_reserved は
        # 誰も呼ばない dead API になり、「プロット中の列 + キャッシュ」の合計が
        # 静かに上限を超える — どちらの帳簿でも自分だけは予算内に見えるので、
        # 症状はメモリ以外のどの数字にも出ない。
        # **順序が重要**: 先に set_pinned_columns で pin 集合を確定させてから
        # 数える (逆だと古い pin 集合のバイト数を渡す)。
        self._channel_cache.set_reserved(self._groups.pinned_column_bytes())

    def pinned_columns(self) -> frozenset[str]:
        """現在 pin されている列キー集合 (introspection・鋳造しない)."""
        return self._groups.pinned_columns()

    def pinned_column_overflow(self) -> int:
        """予算を超えて pin されている鋳造列の数 (0 なら予算内)."""
        return self._groups.pinned_overflow

    def is_container_channel(self, key: str, display_name: str) -> bool:
        """*display_name* が複数列 (または改名列) へ展開される「親」チャンネルか。

        判定は ColumnRecord の列構造から引く — ``sig.values.ndim`` を見ると
        チャンネル全読み (prod で 1 本 96 MB) を誘発し、遅延展開の利得をその場で
        捨てることになる。列キー・スカラー・未知名は ``(display_name,)`` が返るので
        いずれも False (E-3 C-d)。
        """
        return self.column_names_of(key, display_name) != (display_name,)

    def source_info(self, key: str) -> SourceInfo:
        """Return read-only metadata for the group under *key* (KeyError if unknown)."""
        group = self._groups.group(key)
        try:
            size: int | None = group.source_path.stat().st_size
        except OSError:
            size = None  # moved/deleted after load — show what we still know
        # t_min/t_max は範囲のみ必要 — sorted_view() を呼ぶと FU-20 の native
        # dtype 値を全信号ぶん float64 へ upcast + キャッシュし prod(264k)で +数GB
        # 膨張する(FU-18)。MDF は channel-group 内で read-only master を共有する
        # (mdf_loader) ので id() dedup が unique master ごと1回に潰す(264k->数本)。
        # CSV は writeable timestamps を per-signal コピーするため dedup は効かない
        # が、blowup 撤去(sorted_view 不使用)は全ローダー無条件・値も dedup 非依存。
        reps = {id(s.timestamps): s for s in group.signals if len(s.timestamps)}
        ranges = [r for s in reps.values() if (r := s.time_range()) is not None]
        t_min = min(r[0] for r in ranges) if ranges else None
        t_max = max(r[1] for r in ranges) if ranges else None
        return SourceInfo(
            full_path=group.source_path,
            size_bytes=size,
            t_min=t_min,
            t_max=t_max,
            # U2: 単位は **列数**。E-3 反転で len(group.signals) は物理チャンネル数
            # (prod 4,324) になったので、そのまま使うとファイル情報だけが別の母数を
            # 名乗る (ブラウザヘッダ/エクスポートは列数 264,004)。表を持たない
            # CSV/Derived では total_column_count が len(group.signals) に落ちるので
            # 従来値のまま。
            n_channels=self._groups.total_column_count(key),
            file_format=group.file_format,
        )

    def evaluate_formula(
        self,
        expression: str,
        inputs: dict[str, Signal],
        max_depth: int = 100,
    ) -> Signal:
        """Evaluate a Formula and register the resulting Derived_Signal.

        Dependency tracking records the namespaced input signal names so that
        remove_group can detect Derived_Signals that would be orphaned (Req 4.5).
        """
        derived = self._formula.evaluate(expression, inputs, max_depth=max_depth)
        self._derived.append(
            _DerivedRecord(name=derived.name, input_names=frozenset(inputs.keys()))
        )
        return derived

    def remove_group(self, key: str, force: bool = False) -> RemovalResult:
        """Remove a Signal_Group, guarding Derived_Signals that depend on it.

        When a Derived_Signal references any signal in the group and ``force`` is
        False, removal is refused and the dependents are reported (Req 4.5).
        """
        prefix = f"{key}{KEY_SEPARATOR}"
        dependents = tuple(
            rec.name
            for rec in self._derived
            if any(name.startswith(prefix) for name in rec.input_names)
        )
        if dependents and not force:
            return RemovalResult(removed=False, dependent_signals=dependents)

        # remove() drops the namespaced-wrapper caches, deallocating ~1 wrapper
        # Signal per channel synchronously (shared arrays, so cheap per object but
        # O(signal-count) overall). The heavy ~10 GB array dealloc is NOT here:
        # the caller hands `removed_group` to the GUI teardown service (FU-16).
        # This bookkeeping is the term most likely to grow toward the sync-close
        # budget at very high channel counts.
        group, columns = self._groups.remove(key)
        # 増分B: handle 寿命は core が持つ。ここで閉じることで unload と
        # MainWindow._discard (キャンセル完走のロールバック) の両方が構造的に
        # カバーされる — GUI 側 (unload_file) に置くと _discard が漏れる。
        # CSV/Derived グループは handle=None なので no-op。
        #
        # WHY (機序・誤解しやすい): close() は handle.lock を取る
        # (mdf_handle.py:30-31) ので、export ワーカーが select 中なら **GUI スレッドが
        # その読みの終了まで同期ブロック**する (実測 cold 1.18s / warm 0.73-0.83s)。
        # in-flight の select は lock により完走し、SampleReadError になるのは
        # _closed を見る「次の列」。lock は mdf.close() と in-flight mmap read の
        # 競合 (native アクセス違反) を防いでおり外せない。だから「エクスポート中の
        # unload」は close をやめるのではなく **UI 側で拒否**する
        # (AppViewModel.unload_file の述語ガード)。
        cached: tuple[np.ndarray, ...] = ()
        if group.handle is not None:
            # **close の前**に落とす (spec §5.7)。E-4b でキーを serial 化したので
            # 「id 再利用で別ファイルの 2-D を引き当てる」経路は**構造的に消えた**が、
            # この順序は維持する — 残る根拠は **解放のペーシング** である。
            #
            # E-4a: 回収した配列は捨てずに呼び出し側へ渡す。close() は自ハンドルの
            # エントリを ChannelSampleCache から落として**その場で同期解放**するので、
            # 順序を逆にすると teardown へ渡す実体が消え、13.2 MB/本 のチャンネル配列が
            # 三軸ペーシングを迂回して GUI スレッドで解放される (会計上は「配列は
            # 1 本も無かった」ように見えるので、症状はフリーズだけで数字に出ない)。
            #
            # 引く先は**ハンドル自身が提げているキャッシュ**を第一とし、None の
            # ときだけ Session の 1 個へ落とす。Session 経由のロードでは同一
            # オブジェクトなので production の挙動は 1 ビットも変わらないが、
            # self._channel_cache 固定にすると「別キャッシュを提げたハンドル」で
            # drop が空振りし、cached_arrays が空 → close() が実エントリを GUI
            # スレッドで同期解放する = **本タスクが防いだ退行そのもの**へ、
            # どの数字にも症状を出さずに degrade する (M5)。
            #
            # ``or`` ではなく ``is not None`` で分岐するのは、キャッシュが将来
            # ``__len__`` を持つと「空なら falsy」で無言に別帳簿へ逃げるため。
            cache = (
                group.handle.cache
                if group.handle.cache is not None
                else self._channel_cache
            )
            cached = cache.drop_handle(group.handle.serial)
            group.handle.close()
        return RemovalResult(
            removed=True,
            dependent_signals=dependents,
            removed_group=group,
            removed_columns=columns,
            cached_arrays=cached,
        )

    # ─── Pure-computation pass-throughs (Session is the only gateway) ──────────

    def apply_offset(
        self, signal: Signal, file_offset: float = 0.0, signal_offset: float = 0.0
    ) -> Signal:
        return self._synchronizer.apply_offset(signal, file_offset, signal_offset)

    def interpolate(
        self,
        signal: Signal,
        t: float,
        method: InterpolationMethod = InterpolationMethod.LINEAR,
    ) -> float | None:
        return self._interpolator.interpolate(signal, t, method)

    def compute_statistics(
        self, signal: Signal, t_start: float, t_end: float
    ) -> StatisticsResult:
        return self._statistics.compute(signal, t_start, t_end)

    def downsample(self, signal: Signal, n: int) -> Signal:
        return self._downsampler.downsample(signal, n)

    def export_csv(
        self,
        keys: Sequence[str],
        output_path: Path,
        options: CsvExportOptions | None = None,
        *,
        header_resolver: Callable[[Sequence[str]], list[str]] | None = None,
        extra_signals: Sequence[Signal] = (),
    ) -> None:
        """名前空間つき列キーで CSV を書き出す (E-4b spec §5.2・D1)。

        **Signal のリストは受けない** — prod 330,004 列を Signal で運ぶと出口に
        立つ前に ~390 MB を確定させる。解決は書き手が行う (Task 4 の時点では
        移行橋が全解決するので、メモリ挙動はまだ現状のまま)。

        *header_resolver* 既定は passthrough (``list(keys)``) で、直呼び経路の
        現行ヘッダバイトを保存する。GUI は ``csv_header_names`` を束ねた resolver を
        注入する (core は gui を import しない — C-5)。
        *extra_signals* は Derived の escape hatch (spec §5.2 [I-3])。

        Minor 1 (T4 レビュー): *options* に ``header_names`` を自分で詰めて渡しても
        **無視される**。keys 境界はヘッダを常に *header_resolver* (未指定なら
        passthrough) から導出する契約 (spec §10・ヘッダと値を同じ keys から作る)
        で、``CsvExportOptions.header_names`` は移行橋 (``legacy_bridge.py``) が
        旧 ``CsvExporter.export`` へ運ぶための**内部搬送路**にすぎない —
        ``export_via_legacy_path`` が resolver の解決結果で必ず上書きする
        (``replace(request.options, header_names=names)``)。ここを loud-fail に
        する案も検討したが、``header_names`` を設定してこの経路を呼ぶ現存の呼び
        出し元が無いこと、そして ``header_names`` フィールド自体が橋と運命を
        共にし Task 7 で消えることから見送った。
        """
        if isinstance(options, bool):
            # 旧署名 (signals, path, use_unified_timeline, options) から移行し
            # 損ねた呼び出し。黙って options 扱いすると `opts.delimiter` の
            # AttributeError になるだけで原因が読めない。
            raise TypeError(
                "export_csv の第 3 引数は CsvExportOptions です "
                "(use_unified_timeline は options.use_unified_timeline へ移動 — "
                "E-4b spec §5.2)"
            )
        key_tuple = tuple(keys)
        extras = tuple(extra_signals)
        self._reject_container_channels((*key_tuple, *(s.name for s in extras)))
        request = ExportRequest(
            keys=key_tuple,
            output_path=output_path,
            options=options if options is not None else CsvExportOptions(),
            header_resolver=(
                header_resolver
                if header_resolver is not None
                else passthrough_header_names
            ),
            extra_signals=extras,
        )
        # 橋へ self._exporter を渡さないのは、Task 7 の差し替え点を Session 側
        # 1 行 (`export_via_legacy_path(...)` -> `self._exporter.export(request,
        # self.resolve_signal, ...)`) に閉じ込めるため。self._exporter は
        # その受け皿として残す (未使用だが削除しない)。
        export_via_legacy_path(request, self.resolve_signal)

    def _reject_container_channels(self, keys: Sequence[str]) -> None:
        """配列/構造体チャンネルの親を、値を読む前に拒否する (E-3 C-d)。

        GUI のダイアログは親行をチェック不可にしている (C-a) が、scripted /
        realgui は ``session.export_csv`` を直呼びするため、ここが実効的な唯一の
        防波堤になる。所属グループが引けないキー (Derived・アンロード済み) は
        列構造を知りようがないので通す — 判定不能を拒否に倒すと Derived_Signal の
        エクスポートが全滅する (最後の砦は CsvExporter 側の 1 時刻 1 値検査)。

        E-4b: 判定材料が Signal から **キー** へ変わっただけで、述語も文言も不変。
        値を読まない (ColumnRecord 由来) ので 0.1 ms fail-fast も維持される。
        extra_signals の名前もここへ流す — escape hatch を guard の抜け道に
        しないため。
        """
        loaded = set(self.group_keys())
        for key in keys:
            group_key, sep, bare = key.partition(KEY_SEPARATOR)
            if not sep or group_key not in loaded:
                continue
            # 述語は is_container_channel と同一 — ここでインライン展開するのは、
            # エラー文の「例: Mat[0]」に列名そのものが要るため (二度引きしない)。
            columns = self.column_names_of(group_key, bare)
            if columns == (bare,):
                continue
            raise ValueError(
                EXPORT_CONTAINER_CHANNEL_ERROR_TMPL.format(
                    name=bare, example=columns[0] if columns else bare
                )
            )

    # ─── Calcbar operations (Req 26 / 15) ─────────────────────────────────────

    def moving_average(self, signal: Signal, window: int) -> Signal:
        """Simple moving average with a shrinking head window (Req 26.1)."""
        t, v = self._require_min_samples(signal, "moving_average")
        n = len(v)
        if not (1 <= window <= n):
            raise ValueError(f"window must be in 1..{n} (signal length), got {window}")
        out = np.empty(n, dtype=np.float64)
        for i in range(n):
            start = max(0, i - window + 1)
            out[i] = v[start : i + 1].mean()
        return self._derive(signal, f"sma({signal.name})", out, t)

    def linear_regression(self, signal: Signal) -> Signal:
        """Least-squares line evaluated on the (sorted) input timestamps (Req 26.2)."""
        t, v = self._require_min_samples(signal, "linear_regression")
        slope, intercept = np.polyfit(t, v, 1)
        return self._derive(signal, f"linreg({signal.name})", slope * t + intercept, t)

    def differentiate(self, signal: Signal) -> Signal:
        """Numerical derivative: central difference, one-sided at ends (Req 26.3)."""
        t, v = self._require_min_samples(signal, "differentiate")
        d = np.empty(len(v), dtype=np.float64)
        d[1:-1] = (v[2:] - v[:-2]) / (t[2:] - t[:-2])
        d[0] = (v[1] - v[0]) / (t[1] - t[0])
        d[-1] = (v[-1] - v[-2]) / (t[-1] - t[-2])
        return self._derive(signal, f"diff({signal.name})", d, t)

    def integrate(self, signal: Signal) -> Signal:
        """Cumulative trapezoidal integral, starting at 0.0 (Req 26.4)."""
        t, v = self._require_min_samples(signal, "integrate")
        segments = (v[1:] + v[:-1]) / 2.0 * (t[1:] - t[:-1])
        cumulative = np.concatenate([[0.0], np.cumsum(segments)])
        return self._derive(signal, f"integ({signal.name})", cumulative, t)

    @staticmethod
    def _require_min_samples(signal: Signal, op: str) -> tuple[np.ndarray, np.ndarray]:
        """Return the sorted (timestamps, values), raising if fewer than 2 samples (Req 26.7).

        The "≥2 samples" check is against the aligned axis: non-monotonic
        input is dedup'd (keep-last) by sorted_view first, so the count that
        matters is the aligned length, not the raw (possibly duplicate-laden)
        input length.
        """
        t, v = signal.sorted_view()
        if len(v) < 2:
            raise ValueError(f"{op} requires at least 2 samples, got {len(v)}")
        return t, v

    def _derive(
        self, source: Signal, name: str, values: np.ndarray, timestamps: np.ndarray
    ) -> Signal:
        """Build a Derived_Signal on the sorted axis its values were computed on (Req 26.5).

        *timestamps* is expected to already be the aligned (sorted, dedup'd)
        axis returned by ``_require_min_samples`` — Derived_Signals always
        carry a strictly-increasing axis regardless of the source's ordering.
        """
        return Signal(
            name=name,
            timestamps=timestamps,
            values=values,
            file_format="Derived",
            bus_type="",
            source_file="",
            metadata={},
        )
