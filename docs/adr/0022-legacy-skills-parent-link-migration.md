---
adr: 22
date: 2026-09-30
status: accepted
---

# 旧形式の skills 親symlinkを setup.sh が自動移行する

## 背景

2026-08-26 の `f207b3b` で、`setup.sh` は skills の配布を「`<host>/skills` を repo の `skills/` へ
ディレクトリごとリンク」から「manifest に従って skill ごとにリンク」へ変えた。移行処理は入れなかった。

旧形式の親symlinkが残る環境では、skill ごとの宛先が repo 内の実物に解決されるため、
`validate_link_target_topology` が自己参照として拒否し、`setup.sh --all` が exit 2 で止まる。
この検査は正しい。通せば repo 内に自己参照リンクができる。

2026-09-03 の `540b207` は、この状況（Codex 側）を「`--replace-conflicts` でも拒否し、何も変えない」
としてテストで固定した。結果として、旧形式の環境は `setup.sh` だけでは直せない。

実害として、2026-09-30 に新しい shared skill を配布しようとしたところ、Claude 側の旧形式リンクで
`setup.sh --all` が止まり、Codex への配布もできなかった。さらに旧形式のままだと、claude.ai の skill 同期
（`~/.claude/skills/synced/`）が repo の作業ツリー内へ書き込み、`git stash -u` に巻き込まれ、
テストの skill 分類から除外する対処も必要になっていた。

## 決定

- 選択したホストの親パスが symlink で、解決先が**この repo の `skills/`** と一致し、
  親ディレクトリもsymlink解決後にrepoの外にあるときだけ、旧形式と確定する
- 旧形式と確定したものは、フラグ無しで自動移行する。repo の `skills/` 直下で git に追跡されていない項目
  （`synced` など）を新しい実ディレクトリへ運び、親symlinkを実ディレクトリに差し替える
- 確定できないもの（別の場所へのsymlink、壊れたsymlink）は、今までどおり拒否して何も変えない
- 移行は「親リンクが残っている」か「完成した実ディレクトリがある」のどちらかでしか止まらないようにし、
  途中状態が残っていたら次の実行で上書きせずに止まる
- `540b207` の「repo を指す親symlinkを拒否する」契約はこのADRで置き換える。拒否の契約は
  「repo 以外を指す親symlink」に残す

## 検討した代替案

### A. `--replace-conflicts` のときだけ移行する

既存の「置換は明示フラグの下で」という方針に揃う。しかし旧形式は `f207b3b` 以降に作られることが無く、
由来も解決先の一致で確定できるため、利用者に選ばせる判断が残らない。フラグを要求すると、
`setup.sh` を叩いて止まり、フラグを付け直すという手間だけが残るため採らない。

### B. `setup.sh` は拒否のまま、移行は専用コマンドにする

`setup.sh` の責務が増えない。しかし移行は一度きりの作業で、拒否メッセージから別コマンドへ誘導する
二段構えは、案Aと同じく手間だけが増える。移行の検査（解決先・追跡外項目・途中状態）は
`setup.sh` の preflight と同じ情報を使うため、別コマンドに分けると同じ検査を二重に持つことになり採らない。

### C. 親symlinkであれば解決先を問わず移行する

判定が単純になる。しかし別 clone や自作の skill 置き場を指す symlink まで外し、向こうの skill が
黙って読み込まれなくなる。形が同じでも由来が違うものを区別できないため採らない。

### D. 追跡外項目を運ばずに移行する

実装が単純になる。しかし `synced/` を置き去りにする。同期は次回に再ダウンロードされるが、
`.trash/` に退避されていた skill や、利用者が repo 内に直接置いたものは戻らないため採らない。

## 結果

良くなること:

- 旧形式の環境でも `setup.sh` だけで現行形式になる
- claude.ai の同期が repo の作業ツリーへ書き込まなくなる
- 別の場所を指すリンクは今までどおり守られる

諦めること・既知のリスク:

- `setup.sh` が初めて、フラグ無しで利用者の配置を書き換える経路を持つ。判定条件を広げる変更は、
  このADRを見直してから行う
- 移行の途中でプロセスが強制終了された場合は、一時ディレクトリが残る。次の実行で検出して止まるが、
  戻すのは手作業になる
- ownership 状態はリンクの所有を記録しないため、判定は解決先の一致だけに依存する

## 根拠

- `git show f207b3b^:setup.sh`（旧形式のディレクトリリンク）
- `setup.sh` の `build_targets`、`validate_link_target_topology`
- `bin/setup-state.py` の `backup_conflict`
- `tests/test_setup_preflight.py` の `test_codex_rejects_agent_skills_parent_symlink_to_repository`（`540b207`）
- https://code.claude.com/docs/en/skills （Symlinked folders、Reserved name `synced`、synced skill の保存先）
- `docs/superpowers/specs/2026-09-30-claude-skills-legacy-link-migration-design.md`
