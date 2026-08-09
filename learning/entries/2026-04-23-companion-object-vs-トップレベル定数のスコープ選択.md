---
date: 2026-04-23
title: "companion object vs トップレベル定数のスコープ選択"
result: hit
axis: null
---

# companion object vs トップレベル定数のスコープ選択


**問いかけ:** 今回 `MIN_SUPPORTED_VERSION` をトップレベル定数ではなく companion object に置いた。「なぜ companion object にしたの？トップレベルでも同じ結果じゃない？」と聞かれたら、スコープの観点からどう説明する？

**自分の説明:**
companion object はそのクラスに属する。トップレベル定数だと外部から読まれる可能性がある。今回の定数は外部で利用する想定もないので、このクラスのスコープだけで利用するように companion object にした。

**補足:**
トップレベル `private` はファイルスコープなので、同一ファイルに別クラスを追加した瞬間にアクセス可能になる。companion object + `private` ならクラススコープに完全に閉じるため、意図しない参照を構造的に防げる。「スコープを最小に保つ」原則の正確な適用。
