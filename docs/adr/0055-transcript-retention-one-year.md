---
adr: 55
date: 2026-11-19
status: accepted
---

# Claude Code のセッションログの保持期間

## 背景

職務経歴書の作成や、本人の成長・AIの使い方の分析で、過去のセッションログ（`~/.claude/projects/**/*.jsonl`）を材料にしたい。

2026-11-19 に、あるワークスペースの jsonl 139件を最終更新日で見たところ、最も古いものは 2026-10-21 だった。
その日から30日前は 2026-10-20 で、既定値の30日による削除と境界が一致する。
このワークスペースは 2026-08 から使っているのに、8〜9月のセッションは1件も残っていなかった。
削除が実際に起きた記録は見ておらず、日付の一致からの推定である。

一次資料（settings-reference と claude-directory）で確認した仕様は次のとおり。

- `cleanupPeriodDays` は整数で、最小 `1`、既定 `30`。上限は書かれていない。`0` はバリデーションエラーになる
- 削除はセッションを開始した後、裏で走る。メッセージは出さない
- 対象は transcript だけでなく、`file-history/`、`plans/`、`debug/`、`paste-cache/`、`tasks/`、`shell-snapshots/` なども含む
- 孤立した worktree の自動削除も同じ期限を使う

Codex CLI のセッション（`~/.codex/sessions/YYYY/MM/`）には 2026-07 からの月のディレクトリが残っており、
30日で消える挙動は見られなかった。このADRは Claude Code だけを扱う。

## 決定

`settings.json.template` に `"cleanupPeriodDays": 365` を入れる。年に1回、ログを棚卸しして振り返る。
棚卸しのリマインダは、このリポジトリの外のサービスで設定する。

## 検討した代替案

- **3650日（実質無期限）**: 採らなかった。間が空きすぎると、何をしていたかを思い出せず、材料として使いにくい。
  また、ツール出力に混じった secret がディスクに残る期間が際限なく延びる
- **既定の30日のまま、別の場所へ定期的に退避する**: 採らなかった。退避先が増えると、secret を含むかもしれないファイルの置き場も増える。
  退避の仕組みを作って保守する手間もかかる
- **`0` で無効にする**: 仕様上できない（バリデーションエラーになる）

## 結果

- 1年分のセッションが、職務経歴書や振り返りの材料として残る
- secret を含むツール出力が、最大1年ディスクに残る。`guard-secret-read.py` と `permissions.deny` は読み取りを減らすが、
  出力に混じったものは消せない
- `file-history/` や `plans/` なども1年残るので、ディスク使用量が増える。量は測っていない
- 孤立した worktree が自動で消えるまでの期間も1年に延びる
- 棚卸しを忘れると、1年経ったログは黙って消える

## 根拠

- https://code.claude.com/docs/en/settings-reference.md （`cleanupPeriodDays`、`desktopSessionCleanupPeriodDays` の節。2026-11-19に取得）
- https://code.claude.com/docs/en/claude-directory.md （「Cleaned up automatically」の節。2026-11-19に取得）
