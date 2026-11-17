# Go パターンカタログ（Read の候補発見用）

AIが生成・提示した Go コードから、コード学習の Read（読解）の候補を見つけるための材料。
発火条件ではない。候補にできるかは `skills/code-learning/SKILL.md` の候補選定と「Read（読解）」の節、
`rules/learning-mode.md` の共通方針で判断する。

## 選定の基準

次の3つをすべて満たすパターンだけを載せる。項目の数は基準から決まるもので、固定の目標数は無い。

1. 公式の一次資料（Go の言語仕様、Go Code Review Comments、Effective Go、Go Blog、Go Wiki、Go FAQ、
   pkg.go.dev の公式・準公式パッケージのドキュメント）がそのパターンを扱っている
2. AIが書く Go のコードによく現れる
3. 一部を変えたときの挙動を予測でき、実行で確かめられる

慣例寄りの書き方（エラー分岐を先に返す、識別子の命名、interface を定義する場所など）は、基準3を満たさないので載せない。linter の指摘で扱う。
どのパターンがよく現れるか（基準2）は、測った値ではなく判断である。pilot の記録を見て入れ替える。

## 各項目の書き方

- 検出: コード上の目印
- 予測できる変更の例: 本人が変える場所に迷ってヒントを求めたときに、一つずつ出せる候補
- 採点の観点: 本人の予測と説明を採点するときにAIが見る観点
- 検証: 予測を実行で確かめる道具
- 出典: 主張の根拠にした一次資料
- 確認: 主張を何で確かめたか。「原文」はページの本文を読んで確かめたもの、「要約経由」はページの要約でしか確かめていないもの、「実行」は手元で動かして観測したもの（Go 1.27.3、2026-11-17）

**「予測できる変更の例」と「採点の観点」は本人に見せない。** 最初の依頼にも添えない。
見せると注目箇所を渡したことになり、ヒントなしの成功に数えられなくなる。
変更は使い捨てのコピーで行い、production のコードは変えない。

## 並行処理

### goroutine の寿命

- 検出: `go` 文、`sync.WaitGroup`（`Add` / `Done` / `Go`）、`errgroup.Group.Go`
- 予測できる変更の例: 終了条件（`ctx.Done()` の分岐、channel の close）を外す。`wg.Add` を goroutine の中へ移す
- 採点の観点: goroutine がいつ・どうやって終わるか。誰が寿命を持つか。カウンタが 0 のときの `Add` は `Wait` より前に起きる必要がある
- 検証: `go.uber.org/goleak` でテスト終了時に残った goroutine を検出する（`VerifyNone` は `t.Parallel` と併用できないので、並列テストでは `VerifyTestMain` を使う）。`go test -race`
- 出典: https://go.dev/wiki/CodeReviewComments （Goroutine Lifetimes）、https://pkg.go.dev/sync#WaitGroup 、https://pkg.go.dev/go.uber.org/goleak 、https://go.dev/blog/pipelines
- 確認: 原文（Goroutine Lifetimes、WaitGroup の `Add` の順序と、Go 1.25 で入った `WaitGroup.Go`、goleak の API と `t.Parallel` の制約、pipelines の goroutine リーク）

### channel の close とバッファ

- 検出: `make(chan ...)`、`close`、channel に対する `range`
- 予測できる変更の例: `close` を外す。バッファサイズを 0 にする、または増やす。close した後に送信する
- 採点の観点: 誰が close するか。close されないと `range` している側は止まる。バッファが 0 だと、送信側と受信側が揃うまで送信は進まない。close 済みの channel に送ると panic する
- 検証: `go test -timeout` を短くして、止まるかどうかを観測する。すべての goroutine が止まれば `fatal error: all goroutines are asleep - deadlock!` で落ちる
- 出典: https://go.dev/ref/spec （Channel types、Close）、https://go.dev/blog/pipelines
- 確認: 原文（nil channel は通信できない、容量がバッファの大きさ）。要約経由（送受信が揃ったときだけ進むこと、close 済みへの送信で panic）。実行（close しない `range` で deadlock、close 済みへの送信で `send on closed channel` の panic）

### select とキャンセル

- 検出: `select`、`ctx.Done()`、`time.After`
- 予測できる変更の例: `ctx.Done()` の分岐を外す。タイムアウトを短くする
- 採点の観点: ブロックする操作にキャンセルの経路があるか。`Done` が閉じたときに何を返すか
- 検証: ctx をキャンセルして、期限内に戻るかを確かめるテスト
- 出典: https://pkg.go.dev/context 、https://go.dev/doc/go1.23 （Timer の変更）
- 確認: 原文（`Done` は、この context の仕事を取り消すべきときに閉じる channel を返す）。Go 1.23 から、参照されなくなった Timer はすぐ GC の対象になり、Timer の channel は容量 0 になった（原文）。古い `go.mod` のコードでは挙動が違いうる

### context の伝播

- 検出: `context.Context` の引数、`context.Background()` / `context.TODO()`、ctx を持つ struct のフィールド、`WithCancel` / `WithTimeout`
- 予測できる変更の例: 受け取った ctx を `context.Background()` に差し替える。`cancel` を呼ばない
- 採点の観点: 伝播がどこで切れるか。`cancel` を呼ばないと、子の context は親が取り消されるまで残る。ctx は struct に持たず、第1引数で渡す
- 検証: `go vet`（lostcancel）、golangci-lint（contextcheck）、キャンセルが下流に届くかを確かめるテスト
- 出典: https://pkg.go.dev/context 、https://go.dev/wiki/CodeReviewComments （Contexts）、https://pkg.go.dev/cmd/vet 、https://golangci-lint.run/docs/linters/
- 確認: 原文（struct に持たない、第1引数、`cancel` を呼ばないと残る、vet が全経路を確かめる、contextcheck の説明）。実行（`cancel` を捨てると `go vet` が lostcancel で報告する）

### errgroup

- 検出: `errgroup.WithContext`、`g.Go`、`g.Wait`、`g.SetLimit`
- 予測できる変更の例: `errgroup.WithContext` を素の `errgroup.Group` に替える。各 goroutine の `ctx.Done()` の確認を外す。`SetLimit` を外す
- 採点の観点: 一つ失敗したとき、残りはどうなるか。`WithContext` が取り消すのは派生 ctx だけで、残りの goroutine が止まるのは ctx を見ている場合に限る。`Wait` が返すのは最初のエラーだけ
- 検証: 一つをエラーにして、他の goroutine が ctx を見て早く戻ることを確かめるテスト
- 出典: https://pkg.go.dev/golang.org/x/sync/errgroup
- 確認: 原文（最初のエラーで派生 ctx が取り消される、`Wait` は最初のエラーを返す）。「ctx を見ていない goroutine は止まらない」は、上の仕様からの推論で、実行では確かめていない

### ロックと値のコピー

- 検出: `sync.Mutex` / `sync.RWMutex`、`sync.WaitGroup` を含む struct、それを値で渡す・値レシーバで受ける箇所
- 予測できる変更の例: mutex を含む struct を値渡しにする。`Lock` / `Unlock` を外す
- 採点の観点: 値でコピーするとロックが別物になる。メソッドがポインタ型にある型の値はコピーしない。mutex を含む struct のレシーバはポインタにする
- 検証: `go vet`（copylocks）、`go test -race`（実行中に起きた競合しか検出しないので、並行にアクセスするテストが要る）
- 出典: https://go.dev/wiki/CodeReviewComments （Copying、Receiver Type）、https://pkg.go.dev/cmd/vet 、https://go.dev/doc/articles/race_detector 、https://pkg.go.dev/sync#WaitGroup （コピーしない）
- 確認: 原文（Copying、Receiver Type の mutex の記述、race detector は実行時に起きた競合だけを見つける、WaitGroup は最初に使った後でコピーしない）。実行（mutex を含む struct の値渡しを `go vet` が copylocks で報告する）

### 共有 map とデータ競合

- 検出: 複数の goroutine から触る map・slice・変数
- 予測できる変更の例: 同期を外す
- 採点の観点: どの goroutine がいつ触るか。同期はどこで取られているか。競合は、map・slice・文字列ではメモリの破壊につながりうる
- 検証: `go test -race`
- 出典: https://go.dev/ref/mem （Advice、Implementation Restrictions for Programs Containing Data Races）、https://go.dev/doc/articles/race_detector
- 確認: 原文（複数の goroutine が同時に触るデータの変更は直列化する、map などの競合はメモリ破壊につながりうる）。実行（同期なしの並行書き込みで `fatal error: concurrent map writes` が出た。1回の実行で観測しただけで、毎回出るとは限らない）

### worker pool と pipeline

- 検出: 固定数の worker、fan-out / fan-in、段階をつなぐ channel
- 予測できる変更の例: 下流を途中で止める（受信をやめる）。worker の数を変える
- 採点の観点: 下流が先に終わると、上流の送信は止まったまま goroutine が残る。done channel（または ctx）で明示的に取り消す
- 検証: キャンセルしたときに全段が止まるかを、goleak とテストで確かめる
- 出典: https://go.dev/blog/pipelines （Stopping short、Explicit cancellation）
- 確認: 原文（下流が止まると goroutine がリソースを抱えたまま残る、done channel を閉じて取り消す）

## 言語の性質

### ループ変数の捕捉

- 検出: ループ内で起動する goroutine やクロージャが、ループ変数を参照している箇所
- 予測できる変更の例: `go.mod` の `go` ディレクティブを 1.21 以下に下げる
- 採点の観点: Go 1.22 以降はループ変数が反復ごとに新しく作られ、それより前は全反復で共有される。挙動は `go.mod` の `go` のバージョンで決まる
- 検証: 両方のバージョン指定で実行する。`go vet`（loopclosure）は、ループ本体の最後の文（`go`・`defer`・errgroup の `Go` など）での参照しか報告しない。slice にためたクロージャの捕捉は報告しない
- 出典: https://go.dev/blog/loopvar-preview （Fixing For Loops in Go 1.22）、https://go.dev/ref/spec （For statements）、https://pkg.go.dev/golang.org/x/tools/go/analysis/passes/loopclosure
- 確認: 原文（blog の題名、loopclosure は 1.21 以前だけの問題で、最後の文だけを見る）。要約経由（spec の反復ごとの変数）。実行（`go 1.21` で `3 3 3`、`go 1.22` で `0 1 2`。vet は `go` 文の捕捉だけを報告し、slice にためたクロージャは報告しなかった）

### エラーのラップ

- 検出: `fmt.Errorf` の `%w`、`errors.Is` / `errors.As`、センチネルエラー、`_` への代入
- 予測できる変更の例: `%w` を `%v` に替える。エラーを `_` で捨てる
- 採点の観点: `%w` で包むと、呼び出し側が `errors.Is` / `errors.As` で判定できる。`%v` では判定できない。エラーを `_` で捨てない
- 検証: `errors.Is` の結果を確かめるテスト、golangci-lint（errcheck）
- 出典: https://go.dev/blog/go1.13-errors 、https://go.dev/wiki/CodeReviewComments （Handle Errors）、https://golangci-lint.run/docs/linters/
- 確認: 原文（`%w`、`errors.Is` / `errors.As`、`_` で捨てない、errcheck の説明）。実行（`%w` は `Is` が true、`%v` は false）

### nil の error と interface

- 検出: 具体型のポインタを `error` などの interface として返す関数、`if err != nil`
- 予測できる変更の例: `return nil` を、nil を入れた具体型のポインタ変数を返す形に変える
- 採点の観点: interface の値が nil になるのは、型と値の両方が無いときだけ。nil のポインタを入れた interface は nil ではない
- 検証: `err != nil` の結果を確かめるテスト
- 出典: https://go.dev/doc/faq#nil_error
- 確認: 原文（FAQ「Why is my nil error value not equal to nil?」）。実行（nil の `*myErr` を返した `error` は `!= nil` が true）

### 値レシーバとポインタレシーバ

- 検出: メソッド定義のレシーバ、レシーバのフィールドを書き換えるメソッド
- 予測できる変更の例: フィールドを書き換えるメソッドのレシーバを値に替える
- 採点の観点: レシーバを書き換えるメソッドはポインタレシーバにする。値レシーバでの変更は呼び出し側に残らない
- 検証: 呼び出し後のフィールドを確かめるテスト
- 出典: https://go.dev/wiki/CodeReviewComments （Receiver Type）、https://go.dev/doc/effective_go （Pointers vs. Values）
- 確認: 原文（Receiver Type「レシーバを書き換えるならポインタ」）。実行（値レシーバでは `n=0`、ポインタレシーバでは `n=1`）

### defer の評価タイミング

- 検出: `defer`、ループ内の `defer`、defer する関数に渡す引数
- 予測できる変更の例: 引数で渡している値を、クロージャ内の参照に替える。ループ内の defer を関数に切り出す
- 採点の観点: 引数は defer 文の時点で評価される。defer は積んだ逆順に、関数を抜けるときに実行される。ループ内で積んだ defer は関数を抜けるまで実行されない
- 検証: 実行順と値を出力する小さな再現
- 出典: https://go.dev/doc/effective_go （Defer）、https://go.dev/ref/spec （Defer statements）
- 確認: 原文（Effective Go: 引数は defer の実行時に評価される）。要約経由（spec の逆順）。実行（引数で渡すと変更前の値、クロージャで参照すると変更後の値。逆順で実行された）

### slice の共有と append

- 検出: `append`、部分スライス `s[i:j]`
- 予測できる変更の例: `append` の結果を受け直さない。部分スライスの要素を書き換える。容量の内側と外側で `append` する
- 採点の観点: 部分スライスは元の配列を共有する。容量の内側の `append` は元の配列を上書きし、容量を超えると新しい配列になる。大きな配列の一部を持ち続けると、配列全体がメモリに残る
- 検証: len / cap と要素を確かめる再現テスト
- 出典: https://go.dev/doc/effective_go （Slices、Append）、https://go.dev/blog/slices-intro 、https://go.dev/ref/spec （Appending to and copying slices）
- 確認: 原文（Effective Go: 配列が変わりうるので結果を受け直す、blog: スライスはデータをコピーしない、配列全体が残る）。要約経由（spec: 容量が足りなければ新しい配列）。実行（容量内の `append` が元の配列を上書きし、容量を超えた `append` は元に影響しなかった）

### map の性質

- 検出: map の読み書き、`v, ok := m[k]`、map に対する `range`
- 予測できる変更の例: `make` を外す。comma ok を外す。反復順に依存したテストを書く
- 採点の観点: nil の map への書き込みは panic する。無いキーの読み出しはゼロ値を返すので、有無は comma ok で区別する。反復順は決まっていない
- 検証: 再現テスト。反復順は、同じ map を何度か回して順序を比べる
- 出典: https://go.dev/doc/effective_go （Maps）、https://go.dev/ref/spec （Map types、For statements with range clause）
- 確認: 原文（Effective Go: comma ok、無いキーはゼロ値）。要約経由（spec: nil map には要素を足せない、反復順は決まっていない）。実行（nil map への書き込みで `assignment to entry in nil map` の panic、20回の反復で7種類の順序）

### table-driven tests

- 検出: ケースの slice をループで回すテスト、`t.Run`
- 予測できる変更の例: `t.Run` を外して、ループの中で直接 `t.Fatal` を呼ぶ
- 採点の観点: `t.Run` の中の `t.Fatal` が止めるのはそのサブテストだけで、他のケースは走る。`t.Run` が無いと、最初の `t.Fatal` で残りのケースが走らない。`t.Errorf` は記録した後もテストを続ける
- 検証: 一つのケースをわざと失敗させて実行する
- 出典: https://go.dev/wiki/TableDrivenTests 、https://pkg.go.dev/testing
- 確認: 原文（Wiki: `t.Run` を使う例、`t.Errorf` は失敗を記録しても続く）。要約経由（testing: `FailNow` は現在のテストを止める）。サブテストの扱いは資料に明記が無い。実行（`t.Run` ありでは a だけ失敗して b・c が走り、無しでは a で止まった）
