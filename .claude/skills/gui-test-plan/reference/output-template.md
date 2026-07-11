# 分析ブロック出力テンプレート

各タスクにつき以下を出力する（writing-plans がプランへ織り込む）:

## Task <id>: <name>
- **変更種別**: <VM/純ロジック | ウィジェット構成・状態 | 入力イベント→ハンドラ | perf | 描画>
- **触れるユーザージャーニー**: <開く→ブラウズ→フィルタ→プロット→解析→閉じる のどの区間か。可視挙動不変なら「無し」>
- **E2E 受け入れ**（ユーザー可視の効果ごと）:
  - <効果>: E2E タイプ=<入力経路(realgui) | perf | 描画> / 実 observable=<スクショ目視 / prod スケール実測(値vs目標) / activePopupWidget 等> / **prod スケール要否**=<要（prod_demo.mf4）| 不要（理由）> / 実経路 exercise=<変更挙動を実際に通す手段>
- **必要レイヤー**: A=<必須> / B=<要/不要＋理由> / 入力経路 E2E(C)=<要/不要＋理由> / perf E2E=<要/不要> / 描画 E2E=<要/不要>
- **入力経路の再現性**: <sendEvent 再現可 | Layer C 専用（理由）| 新規＝手法確立要 → gui-verify reference/realgui-recipe 誘導>
- **受け入れ要件**:
  - **Red**: <失敗するテスト（コードまたは明確な記述）>
  - **Green**: <最小実装の方針>
  - **Verify（/run・/verify 用チェックリスト）**:
    - 起動: `uv run valisync`（perf/描画は prod スケールデータで）
    - 手順: <ユーザージャーニーの操作手順>
    - 観測: <ユーザーが実際に見て/計測して合格と判断する項目（嘘プロキシ不可）>
- **②実質性チェック**: <観測項目→「自動アサート可（API 名）」/「視覚・実測（スクショ/計測＋/verify）」の割当。naive（スクショのみ・VM 再チェック・小データ perf）なら指摘>
- **①証拠ゲート**: `- [ ] uv run pytest --realgui tests/realgui/test_X.py + 証拠添付`（該当時のみ）
- **realgui 掴み点監査**（ゾーン幾何＝frame 幅/grip 寸法/軸幅 等を変える変更時のみ）: <既存 realgui の全掴み点を境界マージンで再チェック。move/QDrag ゾーンへの誤侵入は assert 失敗でなくハング>
- **honest layering note**: <ある場合。例「ハンドラ直叩きは Layer B ではない」「isVisible は画面内の証拠でない」>

> 非 GUI・可視挙動不変のタスクは「Layer A のみ・E2E 不要・標準 Red/Green」とだけ返す。
