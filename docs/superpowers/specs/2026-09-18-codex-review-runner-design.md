# Codex review runner設計

## 目的

cross-model handoffを受け取ったreview agentを`codex exec`で一度だけ起動し、入力の全行読了、
最終回答、turn完了を機械的に確認する。最終回答が通常のreport fileへ出なかった場合もJSONLから
回収し、必要な場合だけ同じsessionを一度resumeする。空pollやreport不在を理由に新しいreviewを
自動起動しない。

## 初回スコープ

初回実装は次に限定する。

- read-onlyなsecurity reviewとintegration review
- schema 1のcross-model handoff
- `gpt-5.6-luna`、`gpt-5.6-terra`、`gpt-5.6-sol`、`gpt-6-astra`、
  `gpt-5.5`と、validatorが許可するreasoning effort
- Markdown reportの契約検査
- 初回turnと、条件を満たした場合のresume 1回
- fixture JSONLとstub `codex`による外部modelを呼ばないテスト

runnerはreview内容、model tier、review範囲を自動決定しない。親AIがADR 0010に従って
model + effortを選び、ADR 0011に従ってhandoffへ目的、対象範囲、受入条件、返却契約を記録する。

## コンポーネント境界

### `bin/validate-codex-handoff.py`

既存責務を維持する。

- handoff frontmatterと必須section
- branch、HEAD、worktree fingerprint
- 参照成果物pathとSHA-256
- model + reasoning effortの組み合わせ
- `INPUT_DIGEST`固定のvalidated read

review processの起動、JSONL解釈、report回収、resume、lockは担当しない。

### `bin/run-codex-review.py`

新しいorchestration境界とする。

- validator precheckと`INPUT_DIGEST`取得
- validatorのdigest付き`read --document handoff`が返した検証済みbytesから、task IDと
  必須document集合を決定
- task lockとrun directory作成
- review promptの生成と`codex exec`起動
- JSONLの逐次保存・構文検査・安全な進捗表示
- report候補の選択とMarkdown契約検査
- validated read rangeの完全性検査
- resume-onceと最終状態確定
- `manifest.json`と最終`report.md`の保存

promptを任意ファイルから受け取らない。handoffをreview指示の正本とし、runnerが
validator path、handoff path、`INPUT_DIGEST`、model + effort、report contractを含む固定promptを
stdinへ生成する。これによりpromptの二重管理、path traversal、shell展開、古いprompt再利用を避ける。

## CLI

```bash
python3 ~/.codex/bin/run-codex-review.py \
  --repo <repository> \
  --handoff <repository-relative-handoff> \
  --model gpt-5.6-terra \
  --reasoning-effort high \
  --contract security
```

引数契約:

- `--repo`: Git repository。既定は現在directory
- `--handoff`: repository内のschema 1 handoff。絶対pathも受け付けるが、validatorが同じ
  repository内の非symlink通常fileとして検証できる場合だけ許可する
- `--model`と`--reasoning-effort`: 必須かつ常にペア。handoff metadataとも一致させる
- `--contract`: `security`または`integration`

provider、profile、`--oss`、`--local-provider`、sandbox、任意のconfig override、任意prompt、
出力directoryを公開引数にしない。runnerがread-only sandboxとprivate成果物rootを固定し、
providerは現在のCodex設定を継承する。

runnerはhandoff pathを直接openしてmetadataをparseしない。subprocess argvでvalidatorの`validate`を
実行して`INPUT_DIGEST`を取得し、同じdigest、model、effortを指定した
`read --document handoff --start-line 1`から得た全行だけをparseする。headerが最終行までの一括取得を
示さない場合はprecheckを失敗にする。参照documentの有無はこの検証済みfrontmatterから決める。
precheck readは`--start-line 1 --line-count 1000000`を明示し、出力が1 MiBを超えるhandoff、
100万行を超えるhandoff、headerが`lines 1-<total> of <total>`でないhandoffを拒否する。

validated handoffの`返却レポート契約` sectionと`--contract`も照合する。securityは
`Findings`、`Confidence`、`Human confirmation required`、integrationは`Strengths`、`Issues`、
`Recommendations`、`Assessment`、`Ready to commit`をcase-sensitiveな独立markerとして一度ずつ
要求する。反対contractの終端markerが混在する、必須markerが無い、重複する場合は
`CONTRACT_MISMATCH`としてCodex起動前に拒否する。

processの終了コードは固定する。

- `0`: `COMPLETED`、`COMPLETED_RECOVERED`、`COMPLETED_RESUMED`
- `2`: usage errorまたは`FAILED_PRECHECK`
- `3`: `ALREADY_RUNNING`
- `4`: `FAILED_EXECUTION`
- `5`: `FAILED_OUTPUT`
- signal終了: `128 + signal number`。manifestのstateは`CANCELLED`

## `codex exec`起動契約

初回turnはshell文字列ではなく引数配列で次を実行し、生成promptをstdinへ渡す。

```text
codex exec
  --json
  --output-last-message <new-run-dir>/last-message.initial.md
  --model <model>
  --config model_reasoning_effort="<effort>"
  --config sandbox_mode="read-only"
  --sandbox read-only
  --cd <repository>
  -
```

- `--json`と`--output-last-message`は常に併用する
- sessionを永続化しない`--ephemeral`はresume不能になるため使わない
- providerを変更する`--oss`、`--local-provider`、provider関連`--config`は使わない
- user config、rules、hooksを無効化するflagは使わない
- environmentはCodex認証に必要な現在の環境を継承するが、内容を列挙・保存しない
- stdoutはowner-onlyのJSONL event fileへ保存する。child stderrはfileまたは親terminalへ転記せず、
  drainしながらbytes数とSHA-256だけをmanifestへ記録する
- stdoutとstderrはselectorまたは専用readerで同時にdrainし、一方のpipe充満でchildを
  deadlockさせない。上限到達時はそのstreamを放置せずchild process groupを終了する
- runnerの標準エラーには状態名、event件数、session ID、成果物pathだけを出し、
  reasoning、command output、環境変数、report本文は表示しない

resumeは初回`thread.started.thread_id`を明示し、`--last`を使わない。

```text
codex exec resume
  --json
  --output-last-message <new-run-dir>/last-message.resume.md
  --model <model>
  --config model_reasoning_effort="<effort>"
  --config sandbox_mode="read-only"
  <session-id>
  -
```

resumeのpromptは「入力読了は完了済みであり、新しいreviewや再読を始めず、指定契約の最終report
だけを返す」と固定する。resume eventの`thread.started.thread_id`が初回session IDと一致しなければ
失敗にする。ローカルCLIのresumeには`--sandbox`が無いため、公式config keyの
`sandbox_mode="read-only"`を`-c`で明示し、session継承だけに依存しない。

## private成果物とlock

成果物rootはrepository内の`.superpowers/review-runs/`に固定する。実行前にGitのignore対象で
あることを確認し、追跡対象または判定不能ならfail-closedで停止する。repository rootから各path
componentを`O_NOFOLLOW`で開き、symlinkを拒否する。runnerは`umask 077`を設定し、作成directoryを
`0700`、fileを`0600`にする。既存の`.superpowers/`が広いmodeでも、新規
`review-runs/`以下はowner-onlyにする。

実装時にrepositoryの`.gitignore`へ`.superpowers/review-runs/`を明記する。global ignoreだけに
依存しない。runnerはさらに`git check-ignore`で対象run pathがignoreされることと、
`git ls-files --error-unmatch`で追跡済みでないことを確認する。検査が矛盾・失敗した場合は
artifactを作る前に停止する。

```text
.superpowers/review-runs/
├── locks/
│   └── <task-id>.lock
└── <task-id>/
    └── <run-id>/
        ├── events.initial.jsonl
        ├── last-message.initial.md
        ├── events.resume.jsonl        # resumeした場合だけ
        ├── last-message.resume.md     # resumeした場合だけ
        ├── report.md                  # 成功時だけ
        └── manifest.json
```

- task IDはvalidated handoffから取得し、既存のallowlist形式を満たす値だけをpathへ使う
- lock fileを`fcntl.flock(LOCK_EX | LOCK_NB)`でprocess lifetimeに束縛する
- 同じtask IDのlock取得に失敗した実行はCodexを起動せず`ALREADY_RUNNING`で終了する
- 別task IDは並行実行できる
- run IDはUTC時刻と128-bitのcryptographic random値から作り、exclusive createする
- 新規run directoryだけを参照し、以前のreport、JSONL、manifestを回収候補にしない
- runner自身が作るfileはdirectory FDから`O_CREAT | O_EXCL | O_NOFOLLOW`で開く。Codex CLIが
  作成する`last-message.*.md`は回収時に同じdirectory FDから`O_NOFOLLOW`で開き、regular file、
  owner、mode、link countを検査する。symlink、hard link、group/other permission付きfileを拒否する
- event logは64 MiB、各report候補と生成promptは1 MiB、discard前のstderrは8 MiBを上限とする。
  超過時はchildを終了し、成功へ畳まず失敗状態にする

## JSONLとsession ID

stdoutを1行ずつ読み、各行がJSON objectであることを検査してから保存する。空行、壊れたJSON、
未知のevent typeはmanifestへ件数を記録するが、成功・失敗の根拠には数えない。壊れたJSON、
JSON object以外、または既知eventの必須field不正は`FAILED_OUTPUT`にする。未知eventが追加されても、
既知の完了根拠がすべて揃えば成功できる。

- 最初の有効な`thread.started.thread_id`をsession IDとする
- 同じattempt内で異なるsession IDが出た場合は失敗にする
- `turn.failed`またはtop-level `error`があれば失敗にする
- `turn.completed`を最低1件要求する
- `item.completed`以外の途中eventをreportまたは読了証拠にしない
- 空のPTY poll、runner側のpoll timeout、途中の空`agent_message`は状態遷移条件にしない

## report候補の選択

attempt終了後、次の順で一つだけ選ぶ。

1. 新しいrun directoryの`--output-last-message` file
2. 1が不在、空、UTF-8不正、size超過、契約不成立の場合だけ、JSONLの最後の非placeholder
   `item.completed` / `agent_message`

placeholderは空白だけのmessageと、trim後が完全一致する`Please continue.`である。JSONL fallbackは
「契約に合う過去messageを逆順探索」せず、最後の非placeholder messageだけを検査する。これにより
途中の暫定reportを最終回答として採用しない。採用したbytesを新しい`report.md`へatomicに保存する。

### security contract

次を順番どおり要求する。

- `## Findings`
- `## Confidence`と、`Confidence: sufficient`または`Confidence: insufficient`のどちらか一つ
- 任意の`## Missing evidence`
- `## Human confirmation required`と、
  `Human confirmation required: yes`または`Human confirmation required: no`のどちらか一つ

`Findings`は`No findings`、または`Severity: Critical|High|Medium|Low`を一つ以上含む。runnerは
所見の技術的妥当性を評価しないが、次の整合性はfail-closedで検査する。

- `No findings`と`Severity:`は同時に存在しない
- `Severity: Critical`または`Confidence: insufficient`なら、
  `Human confirmation required: yes`である
- `Confidence: sufficient`かつCriticalなしの場合だけ
  `Human confirmation required: no`を許可する

契約値はmanifestへ転記し、runnerがseverity、confidence、人間確認要否を書き換えない。

### integration contract

次を順番どおり要求する。

- `## Strengths`
- `## Issues`
- `### Critical`、`### Important`、`### Minor`
- `## Recommendations`
- `## Assessment`
- `Ready to commit: Yes|No|With fixes`のいずれか一つ

各sectionは空であってはならない。所見なしの場合も各severity subsectionの本文に正確な
`None`を要求する。

## validated read range検査

必要なdocumentは`handoff`と、handoff metadataで`none`ではない`requirements`、
`review-package`である。runner自身のprecheck readはagentの読了証拠へ数えない。

証拠として数えるのは、JSONLの`item.completed` / `command_execution`のうち、次をすべて満たす
ものだけとする。

- `status == completed`かつ`exit_code == 0`
- outer shellとinner commandをstrictにtokenizeでき、control operator、pipe、redirection、
  command substitution、複数commandを含まない
- 実行本体が、runnerのprecheckで解決してpromptへ埋め込んだ絶対pathの`rtk` executable、
  `sys.executable`、repository内`validate-codex-handoff.py read`の引数列と完全一致する。
  相対path、別のPython、`rtk`以外のwrapperは許可しない
- handoff、repository、expected model、expected effort、`INPUT_DIGEST`がprecheck値と一致する
- `--document`、`--start-line`、`--line-count`が重複なく一度ずつ指定される
- `aggregated_output`の先頭行が
  `DOCUMENT: <document> lines <start>-<end> of <total>`と完全一致する
- command引数から計算した期待rangeとheaderのrangeが一致する

agent message、reasoning、失敗したcommand、単なる`echo`、command output途中の`DOCUMENT:`は
証拠にしない。documentごとに全receiptの`total`が同じであることを確認し、rangeをstart順へ並べる。
最初が1、隣接rangeが`previous_end + 1`、最後がtotalであり、overlapとduplicateが0件の場合だけ
読了済みとする。したがって`1-4759`の後に`1-600`を再読した実行は失敗になる。

## 状態機械

```text
PRECHECK
  ├─ handoff/ignore/path不正                  -> FAILED_PRECHECK
  ├─ 同taskのlock取得失敗                    -> ALREADY_RUNNING
  └─ valid                                   -> RUNNING

RUNNING
  ├─ process exit != 0 / error / turn.failed -> FAILED_EXECUTION
  └─ exit 0 + turn.completed                  -> COLLECTING

COLLECTING
  ├─ range不完全                             -> FAILED_OUTPUT
  ├─ primary report有効                      -> COMPLETED
  ├─ JSONL fallback有効                      -> COMPLETED_RECOVERED
  └─ range完全、reportだけ無効               -> RESUME_ONCE

RESUME_ONCE
  ├─ exit 0 + same session + turn.completed
  │    + valid report                         -> COMPLETED_RESUMED
  └─ その他                                  -> FAILED_OUTPUT
```

成功状態は`COMPLETED`、`COMPLETED_RECOVERED`、`COMPLETED_RESUMED`だけとする。resumeでreportを
JSONL fallbackから回収した場合も`COMPLETED_RESUMED`とし、report sourceを別fieldへ記録する。

resumeを許可する条件はすべての入力rangeが初回turnで完全、初回processがexit 0、
`turn.completed`あり、session IDあり、reportだけが無効であること。execution failure、range不足、
session ID不明、異なるsession、lock競合ではresumeしない。resume失敗後に新しいreviewを自動起動しない。
resume attemptのeventも同じreceipt検査へ加え、validated read commandが1件でも追加された場合は
初回rangeとのduplicate / overlapとして`FAILED_OUTPUT`にする。resumeはreport回収だけを行い、入力を
再読したturnを成功へ畳まない。

## manifest

`manifest.json`はrun directory作成直後に`RUNNING`で作成し、状態遷移ごとに同じdirectory内のtemporary fileへ
書いて`os.replace`する。最低限、次を持つ。

```json
{
  "schema_version": 1,
  "task_id": "...",
  "run_id": "...",
  "state": "COMPLETED",
  "model": "gpt-5.6-terra",
  "reasoning_effort": "high",
  "contract": "security",
  "sandbox": "read-only",
  "provider_policy": "inherit-unchanged",
  "input_digest": "...",
  "session_id": "...",
  "attempts": [],
  "read_receipts": {},
  "report_source": "output-last-message",
  "human_confirmation_required": false,
  "started_at": "...",
  "finished_at": "..."
}
```

`attempts`にはattempt種別、exit code、`turn.completed`有無、error event件数、event file名、
report候補file名、stderr bytes数とSHA-256を記録する。full argv、prompt、environment、stderr本文、report本文、
`~/.codex/config.toml`はmanifestへ入れない。run directory作成後に発生した全失敗は、
terminal stateと固定reason codeをmanifestへ残す。run directory作成前のusage、unsafe repository、
ignore不成立、lock競合はmanifestを作らず、固定終了コードと安全なpathだけを標準エラーへ返す。

## error handlingとsignal

- usage、handoff、unsafe path、Git ignore判定不能はCodex起動前にfail-closedにする
- JSONL parse error、size超過、report UTF-8不正、receipt矛盾は`FAILED_OUTPUT`にする
- child起動不能、non-zero exit、`turn.failed`、top-level errorは`FAILED_EXECUTION`にする
- `SIGINT` / `SIGTERM`を受けたらchild process groupへ同じsignalを送り、猶予後に終了させ、
  manifestを`CANCELLED`へ更新する。新しいreviewやresumeは起動しない
- 初回ではwall-clock timeout、retry/backoff、kill後の自動再実行を実装しない。長時間実行中は
  event種別と経過時間だけを定期表示し、停止と無進捗を人間が区別できるようにする

## security boundary

この変更はuser input、external integration、permissionsへ該当する。実装では次を必須にする。

- subprocessはshellを使わずargv配列で起動し、generated promptだけをstdinへ渡す
- handoffとartifact pathはrepository root内、非symlink、allowlist済みcomponentに限定する
- handoff metadataはvalidatorのdigest付き`read`が返したbytesだけからparseする
- task ID、model、effort、contractをallowlist検証する
- artifact rootがGit ignore対象であることをfail-closedで確認する
- owner-only modeとnon-symlink directoryを確認してからevent/reportを開く
- environmentを列挙・manifest化しない。provider、credential、profileを変更しない
- report、JSONL、stderrを標準出力へ転記しない
- childへ認証情報、config全文、repository外fileを読まないよう固定promptで指示する
- manifestのerrorは秘密を含み得る例外全文ではなく、固定reason codeと安全なpathへ正規化する
- 実装完了前に`security-reviewer`のTerra + high + read-onlyで意味レビューする

## テスト

`tests/test_codex_review_runner.py`を追加し、一時repository、fixture JSONL、PATH先頭のstub `codex`で
検証する。外部model、実credential、実`~/.codex/config.toml`を使わない。最低限、次をREDから作る。

1. exit 0、`turn.completed`、完全range、valid output fileで`COMPLETED`になる
2. output file不在でも最後のagent messageから`COMPLETED_RECOVERED`になる
3. 空messageと`Please continue.`をreportにせず、最後の正式reportを選ぶ
4. exit 0でも`turn.completed`が無ければ成功しない
5. reportが有効でもrangeにgapがあれば成功しない
6. 一括read後の分割再読をoverlap/duplicateとして失敗にする
7. agent message内の偽`DOCUMENT:`を読了証拠にしない
8. `rtk python3 ... validate-codex-handoff.py read`だけを許可し、異なるwrapper、digest、model、
   effort、handoffのreceiptを拒否する
9. 入力読了済みでreportだけ無い場合、正確なsession IDを一度だけresumeする
10. resume成功時に新しい`codex exec`を起動しない
11. resume失敗時に2回目のresumeまたは新しいreviewを起動しない
12. `--last`、provider変更flag、shell起動がstub argvに現れない
13. 同task lock中はCodexを起動せず`ALREADY_RUNNING`になる
14. 別runが古いreportを再利用しない
15. symlink path、Git追跡対象artifact root、unsafe modeをfail-closedで拒否する
16. event、report、stderrのsize上限超過を成功へ畳まない
17. security / integration contractの欠落・重複・順序違反、およびCritical / confidenceと
    human confirmationの矛盾を拒否する
18. handoffの返却契約とCLI `--contract`の欠落・混在・重複をprecheckで拒否する
19. manifestにprompt、environment、config全文、credential形式の値を入れない
20. setup後の`~/.codex/bin/run-codex-review.py`がrepository `bin/`への既存link経路で配布される
21. 過去の二重読込fixtureが失敗し、resume成功fixtureが再実行なしで成功する

実装後はunit test、Python compile、setup test、routing/README契約test、diff checkを実行する。
外部modelを呼ぶsmoke testは初回の自動suiteへ含めない。

## 文書同期

実装時に次を同期する。

- `README.md`: runnerの用途、成果物、失敗時の確認場所
- `codex/MODEL_ROUTING.md`: 別モデルreviewはrunner経由、model + effortペア、provider不変
- `docs/adr/0013-codex-review-runner.md`: 実装で判断が変われば新ADRで置換
- `.gitignore`: `.superpowers/review-runs/`をrepository-localにignoreする
- `setup.sh`: `bin/`の既存配布を利用し、preflightでrunner欠落を検知
- `tasks/backlog.md`: 初回除外項目を別タスクとして維持

## 初回に含めないもの

| 項目 | 初回の扱い | 後続判断 |
|---|---|---|
| `--output-schema` / JSON Schema report | 導入しない | Markdown runner安定後にschema移行を比較する |
| 任意agent用の汎用runner | 導入しない | write権限と成功条件を別設計できる場合だけ検討する |
| Web UI | 導入しない | CLI/manifestだけでは運用上不足した証拠が出た場合に検討する |
| retry/backoffの一般化 | 導入しない | transient failure分類と課金上限を定義してから検討する |
| validatorの`read-plan` / 機械可読receipt | 変更しない | JSONL command解析の限界が実測された場合に比較する |
| 複数provider対応・自動切替 | 導入しない | ADR 0010どおりprovider不変・fail-closedを維持する |
| review範囲の自動選択 | 導入しない | runnerとは別にseverityと保証境界のpolicyを設計する |
| 高度なmodel router | 導入しない | ADR 0010の代表task実測後に再評価する |
| 全custom agent profile再評価 | 導入しない | 既存backlogの独立タスクで行う |
| gatewayの空引数問題 | 導入しない | gateway互換性の独立タスクで扱う |
| コード学習統合 | 導入しない | ADR 0012を所有する別ブランチの統合後に扱う |
| resume失敗後の新規review自動実行 | 禁止する | 二重課金防止の既定として維持する |
| 外部modelを毎回呼ぶintegration test | 導入しない | 明示実行のsmoke testとfixture suiteを分離する |
