---
adr: 11
date: 2026-09-15
status: accepted
---

# Codexのモデル間移行を検証可能なMarkdown handoffで行う

## 背景

ADR 0010で、設計・探索・実装・レビューの性質に応じてモデルと推論強度を切り替えると決めた。
しかし会話履歴だけを移行先へ渡すと、弱いモデルが確定済み判断を再解釈し、対象外の変更や
受入条件を満たさないコードを生成しても、入力欠落として検知できない。compactionやfresh subagentでは
会話記憶も永続しない。

OpenAI公式はsubagentへbounded taskを渡し、主agentが要件と判断を保持してsummaryを受け取る形を
案内している。Superpowersもtask brief、report、review package、ledgerをファイルへ置き、会話履歴
ではなく成果物とGitを正本にする。

## 決定

- 実装、探索、修正、セキュリティレビュー、最終レビューを別モデルへ移す前、およびモデル・
  推論強度の昇格、降格、再レビューで実行主体を変える前にMarkdown handoffを作る
- Superpowersのtask brief / review packageがあれば正本として再利用し、handoffからpathと
  SHA-256で参照する。無ければ`.superpowers/handoffs/<task-id>.md`本文を正本にする
- handoffへ目的と対象外、Git状態、確定判断、所有範囲、受入条件、制約、未解決事項、
  model + reasoning effort、返却レポート契約を記録する
- `bin/validate-codex-handoff.py`で必須項目、branch、HEAD、worktree fingerprint、参照hash、
  実行可能なmodel + effortの組み合わせをspawn前に検証する
- validatorは呼出し元の`--repo`を事前に`resolve()`せず、相対pathはcwd、絶対pathはfilesystem
  rootのdirectory FDから各componentを`O_NOFOLLOW`で辿ってGit実行前に固定する。継承された
  `GIT_*`環境を除去して必要な設定だけを明示する。Gitが返したtop-levelを別のdirectory FDで開き、同じdeviceと
  inodeでなければfail-closedで拒否する。一致したroot FDはvalidate / read終了まで保持し、Git
  subprocess、fingerprint、handoff・参照成果物のopenを同じinodeへ束縛する
- fingerprint作成ではGitにworktree内容の変換・diff生成をさせない。index entryをmanifestとしてhashし、
  tracked/untracked fileはrepository rootから各directory componentを`O_NOFOLLOW`で固定して開き、
  clean/process filterを通さない生bytesをhashする。初期化済みsubmoduleも`git status`を使わず、
  HEAD tree・index・生bytesを比較してから実HEADをhashする。submoduleはroot FDから
  `O_NOFOLLOW`で開いたdirectory inodeをGit subprocessのworking tree、raw file読込、nested再帰で
  共有し、検査中にpathが差し替わっても文字列pathからrepository外を再解決しない。内部に
  tracked・untracked差分があれば内容を曖昧に要約せずfail-closedで拒否する
- handoffと参照成果物も同じroot FD起点のcomponent単位openで読み、中間・最終componentの
  symlinkを拒否する。pathの文字列解決と実file openの間にrepository外へ差し替えられる窓を残さない
- 初回validateは、FD固定で読んだhandoffと参照成果物から`INPUT_DIGEST`を返す。受信agentは
  pathを直接読まず、同じdigestを指定したvalidatorの`read`から検証済みbytesを全行取得する。
  各chunkで入力全体のdigestを再照合し、差し替えがあれば内容を返さず停止する
- 全custom agentへ受信ガードを生成し、最初に同じvalidatorを実行してhandoffと参照成果物を
  全文読む。不備・古さ・矛盾があれば推測せず`NEEDS_CONTEXT`を返す
- 別モデルへ再移行する場合は、最新状態で新しいhandoffを作る

## 検討した代替案

### A. 会話履歴とspawn promptだけで引き継ぐ

採らない。欠落した要件と、移行先が勝手に補った解釈を区別できず、compaction後の再現性もない。

### B. handoffを文章規約だけで必須にする

採らない。ファイルが無い、空欄がある、Git状態が古い場合もspawn自体は進み、規約違反を
検知できない。validatorと受信ガードを併用する。

### C. task briefとreview packageをhandoffへ複製する

採らない。正本が複数になり、どちらかだけ更新される。pathとhashで参照し、内容は複製しない。

### D. branchとHEADだけで鮮度を判定する

採らない。同じHEAD上のstage済み・未stage・未追跡差分を検知できない。handoff自身を除く
worktree内容のfingerprintも記録する。

### E. validator成功後は受信agentの確認を省く

採らない。spawn対象やhandoff pathの取り違えを受信境界で検知できない。期待model + effortも
受信agent側で照合する。

### F. dirty submoduleをsuperprojectの`-dirty`表現としてhashする

採らない。submodule内部の異なる差分が同じ表現へ畳まれ、handoff後の内容差し替えを検知できない。
cleanな実HEADだけをhashし、内部差分がある状態ではhandoff作成・受信を停止する。

### G. validate成功後は同じpathをそのまま一度だけ読む

採らない。handoff自身はfingerprintから除外され、参照成果物も同一worktree上にあるため、検証後から
全文読込までの差し替えを検知できない。agentの直接読込を禁じ、digest固定のvalidated readerから
同一bytesを取得する。

### H. `git diff --no-ext-diff --no-textconv`をfingerprintへ使う

採らない。external diffとtextconvを止めても、repositoryの`.gitattributes`とlocal configで定義した
clean/process filterはworktree内容の変換時に実行され得る。read-only validatorからrepository定義の
commandを起動しないため、Gitはindex manifestの列挙だけに使い、内容はOSのfile descriptorから読む。

## 結果

良くなること:

- 弱いモデルへ切り替えても、確定済み判断と受入条件の入力欠落を機械的に検知できる
- compactionやfresh subagent後も、Gitとファイルから同じ作業境界を復元できる
- Superpowers成果物を再利用し、同じ要件の二重管理を避けられる
- モデルと推論強度の指定がhandoffにも残り、実行先との不一致をfail-closedにできる

諦めること・既知のリスク:

- handoff作成とhash更新の手間が増える
- validatorはspawn toolそのものを横取りできないため、親・受信agentが規約に従う必要は残る
- validated readerの使用は受信agentの規約遵守に依存し、OS sandboxがhandoff pathへの直接読込を
  技術的に禁止するものではない
- worktree fingerprintはファイル内容の鮮度を示すが、外部サービスや未記録の会話判断は示さない
- dirty submoduleを含むworktreeはhandoffできず、submodule側をcommitまたは復元してcleanにする必要がある
- モデル名や推論強度が更新されたらvalidatorのallowlist更新が必要になる

## 根拠

- OpenAI Docs: https://developers.openai.com/codex/subagents
- `docs/adr/0010-codex-adaptive-model-routing.md`
- Superpowers `subagent-driven-development` skill

入力handoffを受け取った後の`codex exec`起動、最終回答回収、resume、重複実行抑止は、
`docs/adr/0013-codex-review-runner.md`の専用runnerが担当する。
