"""デザイントークン基盤 (spec 2026-07-15-design-token-pipeline).

tokens は pure Python (VM から安全に import 可)。Qt 依存の適用フックは
theme.apply、QSS 断片生成は theme.qss を明示 import する (eager re-export
すると pure-Python VM の純粋性が壊れるため、ここでは re-export しない)。
"""
