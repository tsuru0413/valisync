"""ChannelBrowserVM — physical-channel browser for the active file.

Presents the currently selected file as one row per **physical channel** (E-2).
その行が提示する **列** (LD-14 の ``Name[i]`` / ``.field``) の出所は
``session.column_names_of()`` — ローダーの ``ColumnRecord`` が唯一の正典で、
列 Signal の列挙には依存しない (E-3 / spec 追補 S1)。反転後 (T6) はローダーが
列 Signal を発行しないため、列を group_signals から数える実装は全行が 1 列の葉に
潰れ ``Mat[1]`` 以降が木・フィルタ・D&D・プレビュー・エクスポートから同時に消える。
Supports incremental substring filtering (matched against *column* names) and
selection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from valisync.core.loaders.signal_group_manager import KEY_SEPARATOR
from valisync.gui import strings as S
from valisync.gui.viewmodels.observable import Observable

if TYPE_CHECKING:
    from valisync.gui.viewmodels.app_viewmodel import AppViewModel

# (physical_name, unit, base_key, columns) — filter independent。columns はその
# 物理チャンネルが提示する列の表示名タプル (ColumnRecord 由来、記録の無い
# グループでは観測した Signal 名)。**列 Signal への参照は一切持たない** —
# 反転後は列 Signal 自体が存在しない。
_PrepRow = tuple[str, str, str, tuple[str, ...]]

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

    The single place with this logic -- ``_scan_filter()`` (feeding both
    ``tree_groups()`` and ``shown_count()`` through the memo) and
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
        self._row_by_base_key: dict[str, int] = {}
        # フィルタ 1 パス分の結果メモ (フィルタ文字列, 生存行, 一致列総数)。
        # 無効化は prep のライフサイクルと不可分 (_invalidate_prep)。
        self._filter_memo: tuple[str, list[_TreeRow], int] | None = None
        # 列名走査を実際に走らせた回数 (inspect() から観測する perf 前提の pin)。
        self._filter_scans: int = 0

    def _invalidate_prep(self) -> None:
        """prep とフィルタメモをまとめて捨てる (両者は不可分)。

        メモは prep が指す列名タプルの上でしか意味を持たない。_ensure_prep も
        再構築時にメモを落とすので**現状はどちらか一方でも結果は正しい**が、
        それは「_ensure_filter_memo が必ず _ensure_prep の後にメモを読む」という
        順序への暗黙依存で、順序が変われば静かに stale を配り始める。無効化点
        (refresh / active_file 切替) を単一の入口に寄せ、「_prep_valid が False
        なのにメモが生きている」中間状態自体を作らない。

        E-3: 旧 _group_sigs (ファイル 1 本ぶんの列 Signal 実体への強参照) は
        廃止した。列は ColumnRecord 由来の文字列なので、VM は Signal を **一度も
        掴まない** — TeardownService._drain が「何も解放できないのに
        pending_signals() だけ減る」最も観測しづらい壊れ方が構造的に起きない。
        """
        self._prep_valid = False
        self._filter_memo = None
        self._prep = []
        self._row_by_base_key = {}

    def _columns_of(self, group_key: str, display_name: str) -> tuple[str, ...] | None:
        """物理チャンネル *display_name* の列名 (ColumnRecord 由来)。記録が無ければ None。

        ``session.column_names_of()`` は「記録が無い」を返り値で表現できない —
        記録を持たないローダー (CSV/Derived) と真のスカラーは、どちらも
        ``(display_name,)`` になる。**両者を区別する必要はない**: どちらの場合も
        「観測した Signal がそのまま 1 列」なので、呼び出し側が観測列名を使えば
        必ず正しい (真のスカラーでは観測名 == display_name で一致する)。

        逆に記録から実リーフ名が出た場合 (``Mat`` -> ``Mat[0]…`` / ``Mono`` ->
        ``Mono[0]``) は記録が正典で、観測より優先しなければならない。反転後は
        観測が物理チャンネル 1 本しか無いため、観測を優先すると ``Mono`` /
        ``P`` / ``Q`` のような「展開したのに 1 列」の行が、実在しない合成キーを
        葉として晒す (C1 のバグそのもの)。

        KeyError を握るのは**注入セッション**のため — production の
        ``Session.column_names_of`` は表を ``dict.get`` で引くので未知 key でも
        ``(display_name,)`` を返し、ここへ KeyError は来ない。一方
        ``column_names_of`` を差し替えた単体テストの偽 session は投げうるので、
        その場合も行を作れるように握る (観測列がそのまま列になる)。
        """
        try:
            cols = self._app_vm.session.column_names_of(group_key, display_name)
        except KeyError:
            return None
        if not cols or cols == (display_name,):
            return None
        return cols

    def _ensure_prep(self) -> None:
        """物理チャンネル単位の (name, unit, base_key, columns) を active file ごとに
        1 度だけ作る。

        行のグループ化キーはローダー由来の metadata['physical_channel'] — 文字列
        解析では ACC.Speed (チャンネル名) と P.x (構造化フィールド) を区別できない。
        **列は session.column_names_of() (ColumnRecord) から取る**: 反転後は
        1 物理チャンネル = Signal 1 個になり、列 Signal を数える実装は全行が
        1 列の葉に潰れる (S1)。

        列名タプルは prep と同寿命で保持する。E-2 が拒否したのは「Signal.name が
        別に存在する状態で作る **小文字化した重複コピー**」(旧 _prep の 68 MB /
        名前キャッシュ案の ≈33 MB) であって、反転後はこのタプルが列名の唯一の
        実体になる。捨てると入力停止のたびに全列ぶんの f-string を作り直すことに
        なり、フィルタ 1 回のコストが構造的に悪化する (実測は T9)。フィルタは
        _matches() が都度 lower() するので、小文字化コピーは今後も持たない。

        記録を持たない行 (CSV/Derived・注入セッション) だけが観測列名を溜める。
        prod の配列行は記録が最初の 1 本で確定するので、264k 本の一時リストは
        作らない。

        session.group_signals は遅延アクセス時に読むので、monkeypatch した session
        (テスト) も初回アクセスで尊重される。
        """
        active_key = self._app_vm.active_file_key
        if self._prep_valid and self._prep_key == active_key:
            return
        self._filter_memo = None  # prep が変われば絞り込み結果も無効
        if not active_key:
            self._prep = []
            self._row_by_base_key = {}
            self._prep_key = active_key
            self._prep_valid = True
            return
        prep: list[_PrepRow] = []
        row_by_base_key: dict[str, int] = {}
        # row -> 観測列名。_columns_of が None を返した行だけが入る。
        observed: dict[int, list[str]] = {}
        for sig in self._app_vm.session.group_signals(active_key):
            orig = _orig_of(sig.name)
            md = sig.metadata or {}
            # CSV/Derived は physical_channel を持たない = 1 列 1 物理チャンネル
            # (意図的逸脱・コントローラ決定 2)。直接添字は CSV で KeyError になる。
            phys = str(md.get("physical_channel") or orig)
            # base_key は「親をグループ化するための合成ハンドル」であって Signal キー
            # ではない (Mono / P / Q は実在しない)。葉の key には決して使わない。
            base_key = f"{active_key}{KEY_SEPARATOR}{phys}"
            row = row_by_base_key.get(base_key)
            if row is None:
                row = len(prep)
                row_by_base_key[base_key] = row
                cols = self._columns_of(active_key, phys)
                if cols is None:
                    observed[row] = [orig]
                    cols = ()  # ループ後に観測列で差し替える
                # unit は物理チャンネル 1 本につき 1 つ — ローダーは同一プローブの
                # metadata を全列へ配る (mdf_loader の pairs ループ) ので「列ごとの
                # unit」は存在しない。親行の Unit を空にするのは tree model の責務
                # (UX-29)。
                prep.append((phys, str(md.get("unit", "")), base_key, cols))
            elif row in observed:
                observed[row].append(orig)
        for row, names in observed.items():
            phys, unit, base_key, _placeholder = prep[row]
            prep[row] = (phys, unit, base_key, tuple(names))
        self._prep = prep
        self._row_by_base_key = row_by_base_key
        self._prep_key = active_key
        self._prep_valid = True

    def _column_key(self, column_name: str) -> str:
        """列の表示名を名前空間つき Signal キーへ。

        反転後は「Signal がまだ存在しない時点」で組み立てるので、Signal から
        読み出すことはできない (鋳造は session.resolve_signal が要求時に行う)。
        _prep_key は _ensure_prep 後は必ず active_file_key と一致する。
        """
        return f"{self._prep_key}{KEY_SEPARATOR}{column_name}"

    def _total_columns(self) -> int:
        """prep が提示する列の総数 (フィルタ非依存)。"""
        return sum(len(row[3]) for row in self._prep)

    def _ensure_filter_memo(self) -> tuple[list[_TreeRow], int]:
        """現在のフィルタでの (生存行, 一致列総数) を 1 パスで求め、フィルタ文字列を
        キーにメモする。

        述語自体はモジュール関数 _matches() に一本化 — tree_groups()・shown_count()
        (共に本メソッド経由)・column_names_for() が同じ _matches() を通ることで
        「ヘッダーの件数」と「木に出る子行」が乖離できない構造にする (C3)。

        メモが要る理由: _notify("filter") は 3 消費者へ fan-out するが全員が同じ問い
        を聞く — SignalTreeModel._on_vm_change -> _rebuild -> tree_groups() /
        _refresh_state -> header_text() -> shown_count() / 同 -> empty_state() ->
        shown_count() (signal_tree_model.py:78-85・channel_browser_view.py:207-218)。
        走るのは打鍵ごとではなく **入力停止ごと** (200 ms シングルショット debounce・
        channel_browser_view.py:41,107-110,220-222) だが、その 1 回で同じ列名走査が
        3 回走っていた (prod 264k 列で実測 3.00 パス)。間に結果を変えるものは無いので
        フィルタ文字列キーのメモ 1 個で 3 -> 1 に畳める。

        追加メモリは実質ゼロ: 保持するのは生存行のタプル (prod 4,324 行) と int
        だけで、**列ごとの小文字名は持たない** (それが旧 _prep の 68 MB /
        名前キャッシュ案の ≈33 MB の本体)。列名そのものは prep が 1 部だけ持ち
        (_ensure_prep の docstring)、子行も件数もそこから賄う。
        """
        self._ensure_prep()
        fl = self._filter_text.lower()
        memo = self._filter_memo
        if memo is not None and memo[0] == fl:
            return memo[1], memo[2]
        rows, total = self._scan_filter(fl)
        self._filter_memo = (fl, rows, total)
        return rows, total

    def _scan_filter(self, fl: str) -> tuple[list[_TreeRow], int]:
        """メモが無いときの実走査 (生存行, 一致列総数)。fl は小文字化済み。"""
        rows: list[_TreeRow] = []
        single: tuple[str, str] | None
        if not fl:
            # フィルタ空 = 実列数がそのまま提示列数 (列名の照合はしない)。
            for name, unit, base_key, cols in self._prep:
                single = (
                    (cols[0], self._column_key(cols[0])) if len(cols) == 1 else None
                )
                rows.append((name, unit, base_key, len(cols), single))
            return rows, self._total_columns()
        # ここから先だけが列名走査。メモが効いていれば入力停止 1 回につき 1 度しか
        # 増えない — テストはこの数を見る。
        self._filter_scans += 1
        matched_total = 0
        for name, unit, base_key, cols in self._prep:
            hits = 0
            single = None
            for col in cols:
                if not _matches(col, fl):
                    continue
                hits += 1
                if hits == 1:
                    single = (col, self._column_key(col))
            if hits == 0:
                continue  # 一致列 0 の行は出さない
            matched_total += hits
            # column_count は **フィルタ非依存の実列数** のまま (_group_total の供給元)。
            # 葉/親の判定に使わないこと — 使うと「絞って 1 列に落ちた行」がドラッグ
            # 不能な親のままになり、今日できる「絞って→ドラッグ」を壊す。
            rows.append(
                (name, unit, base_key, len(cols), single if hits == 1 else None)
            )
        return rows, matched_total

    def shown_count(self) -> int:
        """現在のフィルタに一致した **列** の総数 (行数ではない)。

        件数表示が列基準 (ユーザー決定 2) なので total (_group_total) と単位を
        揃える。header_text/empty_state は件数しか要らないので、per-signal
        オブジェクトはここでも作らない (FU-22 B の残 ~263ms の再発防止)。
        """
        return self._ensure_filter_memo()[1]

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
        return self._ensure_filter_memo()[0]

    def column_names_for(self, base_key: str) -> list[tuple[str, str, str]]:
        """base_key の物理チャンネルの列を (orig, unit, key) で返す。

        走査はその行の列名タプルだけ — group_signals 全走査 (prod 264,004) を
        展開のたびに走らせない (O(n^2) 回避)。返すのは **現在のフィルタに一致する
        列だけ** (フィルタ空なら全列) で、述語は _matches() に一本化 — 件数と
        子行が乖離できない構造にする (C3)。unit は行 (物理チャンネル) のもの —
        列ごとの unit は存在しない (_ensure_prep の docstring)。
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
        _name, unit, _bk, cols = self._prep[row]
        fl = self._filter_text.lower()
        return [(c, unit, self._column_key(c)) for c in cols if _matches(c, fl)]

    # ─── Header / empty-state (FB-05/09) ────────────────────────────────────

    def _group_total(self) -> int | None:
        """Return the active file's filter-independent total **column** count, or
        None (no file active, or its key was already dropped from the session —
        FU-22 B).

        値は prep の列数和。T1 の ``session.total_column_count()`` を production
        から**直接は呼ばない**: (a) shown_count() と別ソースにすると「total <
        shown」の自己矛盾を構造的に許してしまう (C2 — prod で「4,324 ch 中
        264,004 ch を表示」に相当する壊れ方)、(b) 全チャンネル skip の 0ch
        グループや、group_signals だけを差し替えた単体セッションで total と行が
        食い違う。両者が一致することは実ファイルの契約テスト
        (test_group_total_agrees_with_session_total_column_count) が pin する。

        shown_count() が列を数える以上 total も列で数える (C2)。empty_state() の
        total == 0 分岐は変更不要 — チャンネルは必ず 1 列以上持つので「列 0」と
        「チャンネル 0」は同値。

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
        return self._total_columns()

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
        # FU-11: manually clear cache on explicit refresh. メモも同じ入口で落とす
        # (_invalidate_prep の docstring — prep を捨てた瞬間にメモも無効)。
        self._invalidate_prep()
        self._notify("signals")

    # ─── Filter ──────────────────────────────────────────────────────────────

    def set_filter(self, text: str) -> None:
        """Set the incremental substring filter and notify subscribers."""
        self._filter_text = text
        # メモは **フィルタ文字列をキー** に持つので、ここで明示的に捨てる必要は
        # ない (キーが変われば _ensure_filter_memo が自動で走査し直す)。捨てると
        # 「b を打って backspace で a に戻る」ような往復で prod ~170ms の再走査を
        # 無駄に払うことになる。stale になり得るのは prep が変わったときだけで、
        # そちらは _invalidate_prep が一括で面倒を見る。
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
        """Look up the Signal for *key* (namespaced column key)。

        反転後は列 Signal が group_signals に居ない (1 物理チャンネル = Signal 1 個)
        ため、走査で外れたら session.resolve_signal へ落とす — 列キーはそこで
        要求時に鋳造される (E-1)。値は読まないので遅延契約は保たれる
        (tooltip が見るのは timestamps の長さと metadata だけ)。

        **警告 — この形を他所へ複製しないこと**: ``resolve_signal`` は鋳造した列を
        ``_resolved_by_key`` へ登録する。E-4a で LRU が入ったので恒久滞留はしなく
        なったが、ホバー 1 回ごとに**非 pin の枠を食ってプロット中でない列を押し出す**
        (spec §5.5)。ここで許容できるのは
        ``tooltip_for`` に production の呼出元が 1 つも無い (FU-22 B で ToolTipRole が
        SignalTreeModel から外れた) からであって、設計として正しいからではない。
        **PC-19 を復活させるならこの経路は使えない** — 鋳造しないメタデータ取得口が要る
        (``has_column`` は真偽しか返さないので代用にならない)。
        """
        active_key = self._app_vm.active_file_key
        if not active_key:
            return None
        session = self._app_vm.session
        try:
            for sig in session.group_signals(active_key):
                if sig.name == key:
                    return sig
        except KeyError:
            return None
        return session.resolve_signal(key)

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
            self._invalidate_prep()  # FU-11: 別ファイルの prep とメモを捨てる
            self._notify("signals")

    # ─── Introspection ───────────────────────────────────────────────────────

    def inspect(self) -> dict[str, Any]:
        """Return a structured snapshot of ViewModel state.

        ``signal_count`` is ``shown_count()`` — i.e. matched **columns**, which
        is what the header counts (E-2; today 1 Signal = 1 column so the value
        itself is unchanged, only its stated unit).

        ``filter_scans`` is the number of column-name scans performed so far,
        snapshotted **on entry** so it excludes the one this very call's
        ``shown_count()`` may trigger. That is what lets a test bracket a
        filter fan-out with two ``inspect()`` calls and count the scans in
        between; taking it after would fold this call's own scan into the
        "before" reading and make the bracket unusable. Reading it into a local
        (rather than relying on dict-literal evaluation order) keeps that
        property when the keys are reordered.
        """
        scans = self._filter_scans
        return {
            "active_file": self._app_vm.active_file_key,
            "filter_text": self._filter_text,
            "selection": list(self._selection),
            "signal_count": self.shown_count(),
            "filter_scans": scans,
        }
