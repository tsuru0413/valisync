"""ChannelBrowserVM — physical-channel browser for the active file.

Presents the currently selected file as one row per **physical channel** (E-2):
the loader still explodes arrays/structs into per-column Signals, so the columns
are folded back here and synthesized on demand by the tree model. Supports
incremental substring filtering (matched against *column* names) and selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.gui import strings as S
from valisync.gui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from valisync.core.models import Signal
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# (physical_name, unit, base_key, column_count, first_column, spans) — filter
# independent. spans index into _group_sigs; first_column is the real identity
# (orig, namespaced key) of the first column seen, never the synthetic base_key.
_PrepRow = tuple[str, str, str, int, tuple[str, str], list[tuple[int, int]]]

# (physical_name, unit, base_key, column_count, single_column) — what the tree
# model consumes. column_count stays the *real* column count (filter
# independent); single_column is non-None only while the row presents exactly
# one column, and then carries that column's real identity.
_TreeRow = tuple[str, str, str, int, tuple[str, str] | None]


def _orig_of(ns_name: str) -> str:
    """Strip the ``filekey::`` namespace prefix from a Signal name."""
    return ns_name.split(KEY_SEPARATOR, 1)[1] if KEY_SEPARATOR in ns_name else ns_name


def _matches(orig: str, fl: str) -> bool:
    """Substring match predicate: an empty filter matches everything, otherwise
    case-insensitive substring containment.

    The single place with this logic -- ``_filtered_rows()`` and
    ``column_names_for()`` both route through it so the header's matched-count
    and the tree's child rows can never diverge (C3).
    """
    return not fl or fl in orig.lower()


def _labels_tooltip(metadata: dict[str, Any] | None) -> str:
    """Render enum value_labels as a tooltip line, e.g. '0=OFF, 1=LEFT, 2=RIGHT'.

    Sorted by value ascending; truncated to the first 8 entries with a
    '… (全 n 件)' suffix beyond that (spec §3.3, LD-07).
    """
    labels = (metadata or {}).get("value_labels")
    if not labels:
        return ""
    items = sorted(labels.items())
    head = ", ".join(f"{v:g}={t}" for v, t in items[:8])
    if len(items) > 8:
        return f"ラベル: {head}, … (全 {len(items)} 件)"
    return f"ラベル: {head}"


class ChannelBrowserVM(Observable):
    """ViewModel for the channel-browser panel.

    Parameters
    ----------
    app_vm:
        The parent application ViewModel providing the active file context.
    """

    def __init__(self, app_vm: AppViewModel) -> None:
        super().__init__()
        self._app_vm = app_vm
        self._filter_text: str = ""
        self._selection: list[str] = []

        # Subscribe to AppViewModel events to react to file selection changes
        self._unsubscribe = self._app_vm.subscribe(self._on_app_change)

        # FU-11: active_key ごと 1 度だけ作る物理チャンネル単位のタプル列。
        # 生存キーは counter 非減で不変信号集合に対応するため stale 化しない。
        # 無効化は _on_app_change("active_file") で行う。
        #
        # _prep_valid は _prep_key とは別に持つ: active_key は str | None なので
        # "無効化直後で active_key が None" と "None ファイルに対して構築済み" が
        # _prep_key だけでは区別できず、deselect 直後に None==None のキャッシュ
        # ヒット判定で前ファイルの _prep が漏れる実バグがあった (tree_groups() の
        # テストを SignalItem 経由から直接呼びへ書き換えた際に判明)。
        self._prep_key: str | None = None
        self._prep_valid: bool = False
        self._prep: list[_PrepRow] = []
        # _prep と同じ寿命で掴む列 Signal 列 (防御コピーを展開のたびに取り直さない)。
        self._group_sigs: list[Signal] = []
        self._row_by_base_key: dict[str, int] = {}
        # フィルタ 1 パス分の結果メモ (フィルタ文字列, 生存行, 一致列総数)。
        # 中身を詰めるのは後続増分だが、無効化は prep のライフサイクルと不可分なので
        # 構築側 (_ensure_prep) と同じ場所で宣言しておく。
        self._filter_memo: tuple[str, list[_TreeRow], int] | None = None

    def _ensure_prep(self) -> None:
        """物理チャンネル単位の (name, unit, base_key, column_count, first_column,
        spans) を active file ごとに 1 度だけ作る。

        グループ化キーはローダー由来の metadata['physical_channel'] — 文字列解析では
        ACC.Speed (チャンネル名) と P.x (構造化フィールド) を区別できないため。
        E-2 時点ではローダーがまだ列を展開するので、ここで列を物理チャンネルへ畳む。
        小文字化した列名は **持たない** (旧 _prep の 68 MB の本体) — フィルタは
        _filtered_rows が 1 パスで解決する。

        session.group_signals は遅延アクセス時に読むので、monkeypatch した session
        (テスト) も初回アクセスで尊重される。
        """
        active_key = self._app_vm.active_file_key
        if self._prep_valid and self._prep_key == active_key:
            return
        self._filter_memo = None  # prep が変われば絞り込み結果も無効
        if not active_key:
            self._prep = []
            self._group_sigs = []
            self._row_by_base_key = {}
            self._prep_key = active_key
            self._prep_valid = True
            return
        # 防御コピー list(cached) は prod で ~2 ms / 2.1 MB (264k ポインタ・Signal 実体
        # は共有)。column_names_for が展開のたびに再取得しないよう _prep と同寿命で持つ。
        group_sigs = self._app_vm.session.group_signals(active_key)
        prep: list[_PrepRow] = []
        row_by_base_key: dict[str, int] = {}
        for i, sig in enumerate(group_sigs):
            ns_name = sig.name
            orig = _orig_of(ns_name)
            md = sig.metadata or {}
            # CSV/Derived は physical_channel を持たない = 1 列 1 物理チャンネル
            # (意図的逸脱・コントローラ決定 2)。直接添字は CSV で KeyError になる。
            phys = str(md.get("physical_channel") or orig)
            # base_key は「親をグループ化するための合成ハンドル」であって Signal キー
            # ではない (Mono / P / Q は実在しない)。葉の key には決して使わない。
            base_key = f"{active_key}{KEY_SEPARATOR}{phys}"
            row = row_by_base_key.get(base_key)
            if row is None:
                row_by_base_key[base_key] = len(prep)
                unit = str(md.get("unit", ""))
                prep.append((phys, unit, base_key, 1, (orig, ns_name), [(i, i + 1)]))
            else:
                name, unit, bk, n, first, spans = prep[row]
                last_start, last_stop = spans[-1]
                # 連続なら区間を伸ばし、そうでなければ新区間 (連続性は仮定でなく実測 —
                # LD-08 や配列/スカラー interleave で非隣接ブロックになりうる)
                if last_stop == i:
                    spans[-1] = (last_start, i + 1)
                else:
                    spans.append((i, i + 1))
                # unit は「最初に見た列」のもの。集約しない — 親行の Unit は空
                # (UX-29: 親は空・実体は子。混在単位の P.x=m / P.t=s で誤表示になる)。
                prep[row] = (name, unit, bk, n + 1, first, spans)
        self._prep = prep
        self._group_sigs = group_sigs
        self._row_by_base_key = row_by_base_key
        self._prep_key = active_key
        self._prep_valid = True

    def _filtered_rows(self) -> tuple[list[_TreeRow], int]:
        """現在のフィルタでの (生存行, 一致列総数) を 1 パスで求める。

        述語自体はモジュール関数 _matches() に一本化 — tree_groups()・shown_count()
        (共に本メソッド経由)・column_names_for() が同じ _matches() を通ることで
        「ヘッダーの件数」と「木に出る子行」が乖離できない構造にする (C3)。
        """
        self._ensure_prep()
        fl = self._filter_text.lower()
        rows: list[_TreeRow] = []
        if not fl:
            # フィルタ空 = 実列数がそのまま提示列数。prep だけで完結する (列走査ゼロ)。
            rows = [
                (name, unit, base_key, n, first if n == 1 else None)
                for name, unit, base_key, n, first, _spans in self._prep
            ]
            return rows, sum(row[3] for row in self._prep)
        matched_total = 0
        for name, unit, base_key, n, _first, spans in self._prep:
            hits = 0
            single: tuple[str, str] | None = None
            single_unit = ""
            for start, stop in spans:
                for sig in self._group_sigs[start:stop]:
                    orig = _orig_of(sig.name)
                    if not _matches(orig, fl):
                        continue
                    hits += 1
                    if hits == 1:
                        single = (orig, sig.name)
                        # 提示列が 1 本に落ちた行は葉として描かれるので、Unit も
                        # その列のもの (先頭列のではない) でなければ嘘になる。
                        single_unit = str((sig.metadata or {}).get("unit", ""))
            if hits == 0:
                continue  # 一致列 0 の行は出さない
            matched_total += hits
            # column_count は **フィルタ非依存の実列数** のまま (_group_total の供給元)。
            # 葉/親の判定に使わないこと — 使うと「絞って 1 列に落ちた行」がドラッグ
            # 不能な親のままになり、今日できる「絞って→ドラッグ」を壊す。
            if hits == 1:
                rows.append((name, single_unit, base_key, n, single))
            else:
                rows.append((name, unit, base_key, n, None))
        return rows, matched_total

    def shown_count(self) -> int:
        """現在のフィルタに一致した **列** の総数 (行数ではない)。

        件数表示が列基準 (ユーザー決定 2) なので total (_group_total) と単位を
        揃える。header_text/empty_state は件数しか要らないので、per-signal
        オブジェクトはここでも作らない (FU-22 B の残 ~263ms の再発防止)。
        """
        return self._filtered_rows()[1]

    def tree_groups(self) -> list[_TreeRow]:
        """active file の行を物理チャンネル単位で返す (1 行 = 1 物理チャンネル)。

        [(physical_name, unit, base_key, column_count, single_column), ...] を
        ローダー出現順で返す。**葉のリストは返さない** — 子は SignalTreeModel が
        column_names_for() で要求時に合成する。フィルタで一致列 0 の行は返さない。
        """
        try:
            self._ensure_prep()
        except KeyError:
            # set_active_file() does not validate the key exists (FU-22 A), so a
            # notify can still be in flight for a key the session already
            # dropped. Same guard as shown_count/_group_total (FU-22 B: this became
            # production-reachable once ChannelBrowserView switched to
            # SignalTreeModel, whose _on_vm_change calls tree_groups() directly).
            return []
        return self._filtered_rows()[0]

    def column_names_for(self, base_key: str) -> list[tuple[str, str, str]]:
        """base_key の物理チャンネルの列を (orig, unit, key) で返す。

        走査はその行の span (最大でそのチャンネルの列数) だけ — group_signals 全走査
        (prod 264,004) を展開のたびに走らせない (O(n^2) 回避)。返すのは **現在の
        フィルタに一致する列だけ** (フィルタ空なら全列) で、述語は _matches() に
        一本化 — 件数と子行が乖離できない構造にする (C3)。
        """
        try:
            self._ensure_prep()
        except KeyError:
            # Mirrors tree_groups(): reached from _materialize() -> index()/
            # rowCount() inside Qt virtuals (SignalTreeModel), so a notify can
            # still be in flight for a key the session already dropped. An
            # exception escaping into the C++ event loop here is worse than an
            # empty result (FU-22 A/B).
            return []
        row = self._row_by_base_key.get(base_key)
        if row is None:
            return []
        fl = self._filter_text.lower()
        out: list[tuple[str, str, str]] = []
        for start, stop in self._prep[row][5]:
            for sig in self._group_sigs[start:stop]:
                ns_name = sig.name
                orig = _orig_of(ns_name)
                if not _matches(orig, fl):
                    continue
                out.append((orig, str((sig.metadata or {}).get("unit", "")), ns_name))
        return out

    # ─── Header / empty-state (FB-05/09) ────────────────────────────────────

    def _group_total(self) -> int | None:
        """Return the active file's filter-independent total **column** count, or
        None (no file active, or its key was already dropped from the session —
        FU-22 B).

        #14: this no longer resolves the file's display name — the header
        (the only former consumer of it) dropped the filename prefix, and
        which file is active is now shown by the FileBrowser's own selection
        highlight instead.
        """
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            self._ensure_prep()  # prep hit なら追加 fetch なし
        except KeyError:
            return None
        # shown_count() が列を数える以上 total も列で数える (C2)。行数のままだと
        # prod で「4,324 ch 中 264,004 ch を表示」= shown > total の自己矛盾になる
        # (ユーザー決定 2)。empty_state() の total == 0 分岐は変更不要 —
        # チャンネルは必ず 1 列以上持つので「列 0」と「チャンネル 0」は同値。
        return sum(row[3] for row in self._prep)

    def header_text(self) -> str:
        """One-line context header: how many signals are shown of how many.

        #14: the header no longer names the active file — which file is
        active is shown by the FileBrowser's own selection highlight instead.
        """
        total = self._group_total()
        if total is None:
            return S.CHANNEL_HEADER_NO_FILE
        if total == 0:
            return S.CHANNEL_HEADER_EMPTY_TMPL
        return S.CHANNEL_HEADER_COUNT_TMPL.format(total=total, shown=self.shown_count())

    def empty_state(self) -> str:
        """Why the list is empty: none_selected / no_channels / no_match / has_rows."""
        total = self._group_total()
        if total is None:
            return "none_selected"
        if total == 0:
            return "no_channels"
        if self.shown_count() == 0:
            return "no_match"
        return "has_rows"

    def filter_query(self) -> str:
        """Current filter text (for the no_match placeholder message)."""
        return self._filter_text

    # ─── Refresh ─────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Manually trigger a refresh notification."""
        self._prep_valid = False  # FU-11: manually clear cache on explicit refresh
        self._notify("signals")

    # ─── Filter ──────────────────────────────────────────────────────────────

    def set_filter(self, text: str) -> None:
        """Set the incremental substring filter and notify subscribers."""
        self._filter_text = text
        self._notify("filter")

    # ─── Selection ───────────────────────────────────────────────────────────

    def set_selection(self, signal_keys: list[str]) -> None:
        """Replace the current selection with *signal_keys* (namespaced names)."""
        self._selection = list(signal_keys)

    def selected(self) -> list[str]:
        """Return the current selection as a list of namespaced signal names."""
        return list(self._selection)

    # ─── Tooltip (PC-19/DP14) ────────────────────────────────────────────────

    def _signal_by_key(self, key: str) -> Any | None:
        """Look up the active file's Signal whose namespaced name == key."""
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        try:
            for sig in self._app_vm.session.group_signals(active_key):
                if sig.name == key:
                    return sig
        except KeyError:
            return None
        return None

    def tooltip_for(self, key: str) -> str:
        """Lazily assemble a multi-line tooltip for *key* (PC-19).

        Sections (absent lines omitted for CSV/Derived): unit / sample count
        (raw recorded len) / origin (bus_type, channel_group_name, source_name) /
        comment / value_labels. Time range is intentionally excluded.
        """
        sig = self._signal_by_key(key)
        if sig is None:
            return ""
        md = sig.metadata or {}
        lines: list[str] = []
        unit = md.get("unit", "")
        if unit:
            lines.append(f"単位: {unit}")
        lines.append(f"サンプル数: {len(sig.timestamps)}")
        origin = " / ".join(
            b
            for b in (
                sig.bus_type,
                md.get("channel_group_name", ""),
                md.get("source_name", ""),
            )
            if b
        )
        if origin:
            lines.append(f"由来: {origin}")
        comment = md.get("comment", "")
        if comment:
            lines.append(f"コメント: {comment}")
        labels = _labels_tooltip(md)  # "ラベル: ..." or ""
        if labels:
            lines.append(labels)
        return "\n".join(lines)

    # ─── Event Handling ──────────────────────────────────────────────────────

    def _on_app_change(self, change: str) -> None:
        """Handle notifications from AppViewModel."""
        if change == "active_file":
            self._prep_valid = False  # FU-11: 別ファイルの prep を捨てる
            self._notify("signals")

    # ─── Introspection ───────────────────────────────────────────────────────

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of ViewModel state.

        ``signal_count`` is ``shown_count()`` — i.e. matched **columns**, which
        is what the header counts (E-2; today 1 Signal = 1 column so the value
        itself is unchanged, only its stated unit).
        """
        return {
            "active_file": self._app_vm.active_file_key,
            "filter_text": self._filter_text,
            "selection": list(self._selection),
            "signal_count": self.shown_count(),
        }
