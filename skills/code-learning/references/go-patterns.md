# Go パターンカタログ（Read の候補発見用）

AIが生成・提示した Go コードから、コード学習の Read（読解）の候補を見つけるための材料。
発火条件ではない。候補にできるかは `skills/code-learning/SKILL.md` の候補選定と「Read（読解）」の節、
`rules/learning-mode.md` の共通方針で判断する。

各パターンは次の4項目で書く。

- 検出: コード上の目印
- 予測できる変更の例: 本人が変える場所に迷ってヒントを求めたときに、一つずつ出せる候補
- 採点の観点: 本人の予測と説明を採点するときにAIが見る観点
- 検証: 予測を実行で確かめる道具と一次資料

**「予測できる変更の例」と「採点の観点」は本人に見せない。** 最初の依頼にも添えない。
見せると注目箇所を渡したことになり、ヒントなしの成功に数えられなくなる。
変更は使い捨てのコピーで行い、production のコードは変えない。

実行で確かめられる予測が立つものだけを載せる。好みや慣例に近い項目（早期の return、命名など）は
Read の対象にせず、linter の指摘で扱う。

## 並行処理

### goroutine の寿命

- 検出: `go` 文、`errgroup.Group.Go`、`sync.WaitGroup` を伴う起動
- 予測できる変更の例: 終了条件（`ctx.Done()` の分岐、channel の close）を外す
- 採点の観点: goroutine がいつ・どうやって終わるか。誰が寿命を持つか。エラーはどこへ行くか
- 検証: `go.uber.org/goleak` でテスト終了時の goroutine 残留を検出する（`VerifyNone` は `t.Parallel` と併用できないので、並列テストでは `VerifyTestMain` を使う）。`go test -race`。一次資料: Go Code Review Comments「Goroutine Lifetimes」、Go Blog「Go Concurrency Patterns: Pipelines and cancellation」

### channel の close とバッファ

- 検出: `make(chan ...)`、`close`、channel に対する `range`
- 予測できる変更の例: `close` を外す。バッファサイズを 0 にする、または増やす
- 採点の観点: 誰が close するか。close されないと誰が止まるか。バッファサイズによって送信側のブロックがどう変わるか
- 検証: `go test -timeout` を短くして、止まるかどうかを観測する（全 goroutine が止まれば `all goroutines are asleep - deadlock!` で落ちる）。goleak。一次資料: Go Blog「Go Concurrency Patterns: Pipelines and cancellation」、The Go Programming Language Specification「Channel types」

### select とキャンセル

- 検出: `select`、`time.After`、`ctx.Done()`
- 予測できる変更の例: `ctx.Done()` の分岐を外す。タイムアウトを短くする
- 採点の観点: ブロックする操作にキャンセルの経路があるか。タイムアウトしたとき何が返るか
- 検証: ctx をキャンセルして、期限内に戻るかを確かめるテスト。一次資料: pkg.go.dev/context

### context の伝播

- 検出: `context.Context` の引数、`context.Background()` / `context.TODO()` の出現、ctx を持つ struct のフィールド
- 予測できる変更の例: 受け取った ctx を `context.Background()` に差し替える。`defer cancel()` を外す
- 採点の観点: 伝播がどこで切れるか。cancel は誰が呼ぶか。なぜ ctx を struct に持たないか
- 検証: `go vet`（lostcancel）、golangci-lint（contextcheck）、キャンセルが下流に届くかを確かめるテスト。一次資料: Go Code Review Comments「Contexts」、pkg.go.dev/context

### errgroup

- 検出: `errgroup.WithContext`、`g.Go`、`g.Wait`、`g.SetLimit`
- 予測できる変更の例: `errgroup.WithContext` を素の `errgroup.Group` に替える。各 goroutine の `ctx.Done()` の確認を外す。`SetLimit` を外す
- 採点の観点: 一つ失敗したとき、残りはどうなるか。`WithContext` が取り消すのは派生 ctx だけで、残りの goroutine が止まるのは ctx を見ている場合に限る。素の `errgroup.Group` では残りは最後まで走る。`Wait` が返すのは最初のエラーだけ。並列数に上限はあるか
- 検証: 一つをエラーにして、他の goroutine が ctx を見て早く戻ることを確かめるテスト。一次資料: pkg.go.dev/golang.org/x/sync/errgroup

### ロックか channel か

- 検出: `sync.Mutex` / `sync.RWMutex`、`sync.Once`、`sync/atomic`、mutex を含む struct を値で渡している箇所
- 予測できる変更の例: `Lock` / `Unlock` を外す。mutex を含む struct のレシーバを値レシーバに替える
- 採点の観点: 共有状態の保護か、所有権の受け渡しか。なぜその道具か。値でコピーするとロックが別物になること
- 検証: `go test -race`（実行中に起きた競合だけを検出するので、並行にアクセスするテストが要る）、`go vet`（copylocks）。一次資料: The Go Memory Model

### 共有 map とデータ競合

- 検出: 複数の goroutine から触る map・slice・変数
- 予測できる変更の例: 同期を外す
- 採点の観点: どの goroutine がいつ触るか。同期はどこで取られているか
- 検証: `go test -race`。map では、ランタイムが `concurrent map writes` で落ちることもある（必ずではない）。一次資料: The Go Memory Model

### worker pool と pipeline

- 検出: 固定数の worker、fan-out / fan-in、段階をつなぐ channel
- 予測できる変更の例: 下流を途中で止める（受信をやめる）。worker の数を変える
- 採点の観点: 並列数の決め方。下流が先に終わったとき、上流の送信はどうなるか
- 検証: キャンセルしたときに全段が止まるかを、goleak とテストで確かめる。一次資料: Go Blog「Go Concurrency Patterns: Pipelines and cancellation」

## 言語の性質

### ループ変数の捕捉

- 検出: ループ内で起動する goroutine やクロージャが、ループ変数を参照している箇所
- 予測できる変更の例: `go.mod` の `go` ディレクティブを 1.21 以下に下げる
- 採点の観点: Go 1.22 以降は、ループ変数が反復ごとに新しく作られる。それより前は全反復で共有される。挙動は `go.mod` の `go` のバージョンで決まる
- 検証: 両方のバージョン指定でテストを実行する。`go vet`（loopclosure）。一次資料: Go Blog「Fixing For Loops in Go 1.22」、Go 1.22 Release Notes

### エラーの扱い

- 検出: `fmt.Errorf` の `%w`、`errors.Is` / `errors.As`、センチネルエラー、`_` への代入
- 予測できる変更の例: `%w` を `%v` に替える。エラーを `_` で捨てる
- 採点の観点: ラップする理由と、呼び出し側が何で判定するか。捨ててよいエラーか
- 検証: `errors.Is` の結果を確かめるテスト、golangci-lint（errcheck）。一次資料: pkg.go.dev/errors、Go Blog「Working with Errors in Go 1.13」

### defer の評価タイミング

- 検出: `defer`、ループ内の `defer`、defer する関数に渡す引数
- 予測できる変更の例: 引数で渡している値をクロージャ内の参照に替える。ループ内の defer を関数に切り出す
- 採点の観点: 引数は defer 文の時点で評価されること。ループ内で積んだ defer は関数を抜けるまで実行されないこと
- 検証: 実行順と値を出力する小さな再現。一次資料: Effective Go「Defer」、The Go Programming Language Specification「Defer statements」

### slice と map の性質

- 検出: `append`、部分スライス、nil map への書き込み
- 予測できる変更の例: `append` の結果を受け直さない。部分スライスの要素を書き換える。map の `make` を外す
- 採点の観点: 容量を超えた `append` で配列が作り直されること。部分スライスが元の配列を共有すること。nil map への書き込みで panic すること
- 検証: len / cap と要素を確かめる再現テスト。一次資料: Go Blog「Go Slices: usage and internals」、Effective Go「Slices」「Maps」

### table-driven tests

- 検出: ケースの slice をループで回すテスト、`t.Run`
- 予測できる変更の例: `t.Run` を外して、ループの中で直接 `t.Fatal` を呼ぶ
- 採点の観点: `t.Run` があると、一つのケースの `t.Fatal` が他のケースを止めないこと。失敗したケースが名前で分かること
- 検証: 一つのケースをわざと失敗させて実行する。一次資料: Go Wiki「TableDrivenTests」、pkg.go.dev/testing
