from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping

from valisync.core.models import Signal, SignalGroup

_FORMAT_KEY_PREFIX: dict[str, str] = {"MDF4": "mf4", "CSV": "csv"}
KEY_SEPARATOR = "::"


class SignalGroupManager:
    """Manages loaded Signal_Groups under unique per-load keys.

    Each added group receives a key such as ``mf4_1`` / ``csv_2``, derived from
    its file format plus a per-format counter. The key namespaces every signal
    name (``mf4_1::speed``) so signals from different files — including re-loads
    of the same path — never collide. The counter never decrements, so a key is
    never reused after removal. Recovering the display name (original signal
    name and source file) is left to the GUI layer.
    """

    def __init__(self) -> None:
        self._groups: dict[str, SignalGroup] = {}
        self._counters: dict[str, int] = {}
        self._namespaced_list: list[Signal] | None = None
        self._namespaced_map: dict[str, Signal] | None = None
        self._namespaced_by_key: dict[str, list[Signal]] = {}
        # 鋳造した列 Signal (E-1)。**_invalidate_namespaced() に相乗りさせない** —
        # 相乗りすると 2 ファイル目のロードごとに全プロット列がフルチャンネル再読み
        # (実測 0.73-1.18 s/列) になる純粋な回帰。remove(key) でだけ切り離す。
        self._resolved_by_key: dict[str, dict[str, Signal]] = {}
        self.mint_count = 0

    def add(self, group: SignalGroup) -> str:
        """Register a Signal_Group and return its assigned key.

        Duplicate source paths are allowed; each load receives a distinct key.
        """
        prefix = _FORMAT_KEY_PREFIX.get(group.file_format)
        if prefix is None:
            raise ValueError(f"unsupported file_format: {group.file_format!r}")
        self._counters[prefix] = self._counters.get(prefix, 0) + 1
        key = f"{prefix}_{self._counters[prefix]}"
        self._groups[key] = group
        self._invalidate_namespaced()
        return key

    def remove(self, key: str) -> tuple[SignalGroup, tuple[Signal, ...]]:
        """グループと、そのグループで鋳造済みの列 Signal を取り出して返す。

        列 Signal は SignalGroup.signals の外に居るため、ここで返さないと
        TeardownService の会計・解放から漏れる。

        Dependency checking against Derived_Signals (Req 4.5) is the Session's
        responsibility; this method removes unconditionally.
        """
        try:
            group = self._groups.pop(key)
        except KeyError:
            raise KeyError(f"no Signal_Group registered under key: {key!r}") from None
        columns = tuple(self._resolved_by_key.pop(key, {}).values())
        self._invalidate_namespaced()
        return group, columns

    @property
    def keys(self) -> list[str]:
        """Keys of all registered groups, in insertion order."""
        return list(self._groups)

    def group(self, key: str) -> SignalGroup:
        """Return the Signal_Group registered under ``key`` (original signal names)."""
        return self._groups[key]

    def source_name(self, key: str) -> str:
        """Original source filename (basename) for the group under ``key``.

        Public recovery point for the GUI display name (the class otherwise
        leaves display-name recovery to the GUI layer). Raises KeyError if the
        key is unknown.
        """
        return self._groups[key].source_path.name

    @staticmethod
    def _namespaced(key: str, group: SignalGroup) -> list[Signal]:
        """Rewrite a group's signal names to ``{key}{KEY_SEPARATOR}{name}``.

        The returned Signals share the stored timestamp/value arrays.
        """
        result: list[Signal] = []
        for sig in group.signals:
            ns_sig = Signal(
                name=f"{key}{KEY_SEPARATOR}{sig.name}",
                timestamps=sig.timestamps,
                values_source=sig._values_source,
                file_format=sig.file_format,
                bus_type=sig.bus_type,
                source_file=sig.source_file,
                metadata=sig.metadata,
            )
            # namespaced ラッパーは FU-08 でキャッシュされ、add()/remove() の
            # 無効化までは再生成されない。無効化のたびにラッパーは作り直されるため、
            # sorted_view/finite_view の単調・非有限スキャン結果は長寿命の元 Signal に
            # 委譲して共有する — スキャンはラッパーが何度作り直されても元 Signal で
            # 1回だけ走る(render/カーソルのホットパス対策)。委譲は timestamps/values
            # の配列オブジェクトが元 Signal と同一であることが前提
            # (offset 適用後の別配列 Signal には絶対に付けないこと)。
            object.__setattr__(ns_sig, "_sorted_view_delegate", sig)
            result.append(ns_sig)
        return result

    def _invalidate_namespaced(self) -> None:
        """Drop the namespaced caches; rebuilt lazily on next access."""
        self._namespaced_list = None
        self._namespaced_map = None
        self._namespaced_by_key = {}
        # NOTE: _resolved_by_key はここで**捨てない** (Critical 1)。捨てると 2 ファイル目の
        # ロードごとに全プロット列が新オブジェクト (空キャッシュ) となり、次の render で
        # フルチャンネル再読み (実測 0.73-1.18 s/列) が走る。切り離しは remove(key) のみ。

    def _ensure_namespaced(self) -> None:
        """Build and cache the namespaced signal list/map once (idempotent).

        The expensive work — creating one namespaced Signal wrapper per signal
        across all groups — happens here a single time per load/unload, not on
        every ``signals()``/``signal_map()`` call (FU-08). The list preserves
        every signal (duplicate namespaced names included); the map is keyed by
        name with last-wins dedupe, matching the historical ``signals()``-to-dict
        behaviour its callers relied on.
        """
        if self._namespaced_list is not None:
            return
        result: list[Signal] = []
        for key, group in self._groups.items():
            result.extend(self._namespaced(key, group))
        self._namespaced_list = result
        self._namespaced_map = {sig.name: sig for sig in result}

    def group_signals(self, key: str) -> list[Signal]:
        """Namespaced signals for a single group (KeyError if key is unknown).

        Lets callers fetch one file's signals without scanning every group.
        Cached per key on the same invalidation lifecycle as the whole-session
        caches (FU-08); rebuilt only after add()/remove(). Prevents the
        per-call rebuild of every namespaced wrapper (FU-11).
        """
        group = self._groups[key]  # 未知 key は従来どおり KeyError
        cached = self._namespaced_by_key.get(key)
        if cached is None:
            cached = self._namespaced(key, group)
            self._namespaced_by_key[key] = cached
        return list(cached)  # 防御コピー(signals() と同契約) — Signal は共有

    def signals(self) -> list[Signal]:
        """Return every signal across all groups, name-spaced by its group key."""
        self._ensure_namespaced()
        assert self._namespaced_list is not None
        return list(self._namespaced_list)

    def signal_map(self) -> Mapping[str, Signal]:
        """読み取り専用 ``{namespaced_name: Signal}`` ビュー (FU-08 でキャッシュ)。

        重複した名前空間つき名は last-wins (``signals()`` から dict を作るのと同じ)。
        読み取り専用なので呼び出し側は共有キャッシュを壊せない。

        **非対称 Mapping** (E-1・意図的逸脱): ``[]``/``get``/``in`` は列キーを解決器
        経由で鋳造しうるが、``__iter__``/``len`` は既存 (物理) キーのみを返す。全論理
        キーの列挙は 330k 列を鋳造して ~390 MB を再導入するため提供しない —
        ``dict(signal_map())`` は使ってはならない。
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        return _ResolvingMap(self._namespaced_map, self.resolve)

    def resolve(self, key: str) -> Signal | None:
        """名前空間つきキーを Signal へ解決する (無ければ列として鋳造を試みる)。

        グループ未ロードなら None (正当な不在)。ローダーが列を展開している間は
        全キーが既存 map で解決でき、鋳造経路はテストからのみ exercise される。
        """
        self._ensure_namespaced()
        assert self._namespaced_map is not None
        hit = self._namespaced_map.get(key)
        if hit is not None:
            return hit
        group_key = key.split(KEY_SEPARATOR, 1)[0]
        if group_key not in self._groups:
            return None
        table = self._resolved_by_key.setdefault(group_key, {})
        cached = table.get(key)
        if cached is not None:
            return cached
        minted = self._mint_column(group_key, key)
        if minted is None:
            return None
        table[key] = minted
        self.mint_count += 1
        return minted

    def resolved_keys(self, group_key: str) -> frozenset[str]:
        """鋳造済み列キーの集合 (鋳造を誘発しない introspection)."""
        return frozenset(self._resolved_by_key.get(group_key, {}))

    def _mint_column(self, group_key: str, key: str) -> Signal | None:
        """列キーから Signal を鋳造する。E-1 では ColumnSpec 未配線のため None。

        E-3 でローダーが per-channel Signal + ColumnSpec を発行したら、ここで
        parse_leaf → LazyMdfValues(selector) → Signal 構築を行う。

        鋳造した Signal は列キーの**正典**であり (resolve は同じキーに同じオブジェクトを
        返す)、namespaced ラッパーと違って別の元 Signal を持たない —
        ``_sorted_view_delegate`` は不要。
        """
        return None


class _ResolvingMap(Mapping[str, Signal]):
    """既存マップ + 未知キーの解決器フォールバック (列挙は既存キーのみ)。

    ``Mapping`` の契約からの**意図的逸脱**: ``key in m`` が True でも ``iter(m)`` が
    その key を返さないことがある。全論理キーを列挙可能にすると 330k 列を鋳造して
    ~390 MB を再導入する — それが E-1 で取り除いているコストそのもの。読み取り専用
    (``__setitem__`` 無し) なので base の共有キャッシュは外から壊せない。
    """

    __slots__ = ("_base", "_resolve")

    def __init__(
        self, base: dict[str, Signal], resolve: Callable[[str], Signal | None]
    ) -> None:
        self._base = base
        self._resolve = resolve

    def __getitem__(self, key: str) -> Signal:
        hit = self._base.get(key)
        if hit is not None:
            return hit
        got = self._resolve(key)
        if got is None:
            raise KeyError(key)
        return got

    def get(self, key: str, default: Signal | None = None) -> Signal | None:  # type: ignore[override]
        # Mapping 既定の get は __getitem__ の KeyError を捕まえるので挙動は同じだが、
        # 呼出側 (約20箇所の sig_map.get) のホットパスから例外の送出/捕捉を外す。
        hit = self._base.get(key)
        if hit is not None:
            return hit
        got = self._resolve(key)
        return default if got is None else got

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        # 既存キーは解決器を通さない (鋳造を誘発しない)。
        return key in self._base or self._resolve(key) is not None

    def __iter__(self) -> Iterator[str]:
        return iter(self._base)  # 物理キーのみ — 鋳造しない (クラス docstring 参照)

    def __len__(self) -> int:
        return len(self._base)  # 物理キー数のみ — 鋳造しない
