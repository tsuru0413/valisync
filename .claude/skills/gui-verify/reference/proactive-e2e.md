# 先回り E2E の HOW（ユーザーより先に課題を見つける）

> merge/done 宣言の前に、Claude が実アプリを**実スケール**で動かして各ユーザー可視効果を実 observable で確認する手順。FU-01〜17 が全て「ユーザーが触って初めて発覚」だった手戻りを塞ぐ。

## ユーザージャーニー雛形

変更を diff でなく、この操作列のどの区間に参加するかで捉える:

**開く → ブラウズ → フィルタ → プロット → 解析 → 閉じる**

- **開く**: ファイルダイアログ／Ctrl+O／Welcome CTA／Recent MRU。
- **ブラウズ**: ChannelBrowser のツリー・ソート・ツールチップ・スクロール。
- **フィルタ**: 検索ボックスへの**実打鍵**（per-keystroke の debounce/キャッシュ/backspace/大小切替）。
- **プロット**: D&D／ダブルクリック／Add で波形追加、軸・ズーム・パン。
- **解析**: カーソル設置・移動・Δ・範囲統計・オフセット・readout。
- **閉じる**: タブ/パネル削除・ソース Remove・レイアウト保存。

各区間で「ユーザーが何を見て/計測して合格と判断するか」を列挙し、それぞれに E2E タイプ（入力/perf/描画）を割り当てる。

## prod スケール駆動（perf/描画は必須）

小データでは FU-11（330k で 17s フリーズ）/12/16 は顕在化しない。スケールしうる効果は本番相当データで駆動する:

- 生成（未生成なら）: `uv run python scripts/generate_demo_mf4.py --profile prod --out demo_data/prod_demo.mf4`（~33万ch/~1.36GB/120s）。生成物は gitignore・非コミット。
- 既存があれば `demo_data/prod_demo.mf4` を再利用。
- 軽い機能確認は `--profile quick`（0.17GB）で足りるが、**perf/描画の合否判定を quick で代替しない**（prod スケールでのみ出る問題を隠す）。

## 実アプリ起動と観測

- 起動: `uv run valisync`（perf/描画は上記 prod データを開く）。
- **スクショ観測**: `QT_QPA_PLATFORM=windows` で撮る（offscreen は全文字が□＝豆腐）。描画の正しさ（レンジ/クリップ/色/線）・ハイライト・挿入線・dimmed source はスクショ目視で判定。
- **perf 実測**: `time.perf_counter()` の wall-clock か call-count を計測し**目標値 vs 実測**で判定（体感でなく数値）。per-keystroke など操作単位のレイテンシは1操作ずつ計測。
- **入力経路**: realgui（Layer C・実 OS 入力＋スクショ）。手順は `reference/realgui-recipe.md`。

## 「Claude が先に見つける」観測チェックリスト

各ユーザー可視効果につき、done 宣言の前に自分で確認する:

- [ ] 実アプリを**実スケール**で起動し、その効果に至るジャーニーを実際に操作した。
- [ ] 効果を**実 observable** で確認した（入力=realgui スクショ／perf=prod 実測値／描画=スクショ）。嘘プロキシ（`isVisible`/`setText`1回/小データ perf）で代替していない。
- [ ] perf/描画は `prod_demo.mf4`（330k）で実測し、目標を満たした。
- [ ] E2E 証拠が**変更した挙動そのもの**を実経路で通している（同名だが別コードのテストではない）。
- [ ] フリーズ・空描画・座標ずれ・stale 表示・省略欠けなど、ユーザーが最初に気づく違和感を実画面で探した。
