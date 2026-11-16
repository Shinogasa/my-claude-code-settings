# Go パターンカタログ（コード学習の候補発見用）

AIが生成・提示した Go コードから、コード学習（主に Explain の読解）の候補を
見つけるための材料。発火条件ではない。候補にできるかは `skills/code-learning/SKILL.md` の
候補選定と `rules/learning-mode.md` の共通方針で判断する。
各パターンは「検出の目安」「問う範囲」「検証 route」で書く。問う範囲は読解で本人に
説明させる範囲であり、答えや観点の一覧を先に渡すためのものではない。

## 並行処理

### goroutine の寿命

- 検出: `go` 文、`errgroup.Group.Go`、`sync.WaitGroup` を伴う起動
- 問う範囲: その goroutine はいつ・どうやって終わるか。誰が寿命を持つか。エラーはどこへ行くか
- 検証: `go test -race`、終了を確かめる再現テスト。一次資料: Go Code Review Comments「Goroutine Lifetimes」、Go Concurrency Patterns: Pipelines

### channel の close とバッファ

- 検出: `make(chan ...)`、close、range over channel
- 問う範囲: 誰が close するか。バッファサイズの根拠は何か。close されないと誰が止まるか
- 検証: 送信側が close する形になっているかをコードで確認。一次資料: Go Concurrency Patterns: Pipelines

### select とキャンセル

- 検出: `select`、`time.After`、`ctx.Done()`
- 問う範囲: ブロックする操作にキャンセルの経路があるか。タイムアウトはどう扱われるか
- 検証: ctx をキャンセルして戻ることを確かめるテスト。一次資料: pkg.go.dev/context

### context の伝播

- 検出: `context.Context` 引数、`context.Background()` / `TODO()` の出現、struct のフィールド
- 問う範囲: 伝播チェーンがどこで切れるか。なぜ struct に持たないか。cancel は誰が呼ぶか
- 検証: `go vet`（lostcancel）、golangci-lint（contextcheck）。一次資料: Go Code Review Comments「Contexts」

### errgroup

- 検出: `errgroup.WithContext`、`g.Go`、`g.Wait`、`SetLimit`
- 問う範囲: 一つ失敗したとき残りはどうなるか。並列数に上限はあるか。WaitGroup でなく errgroup を選んだ理由は何か
- 検証: エラー時に他がキャンセルされるテスト。一次資料: pkg.go.dev/golang.org/x/sync/errgroup

### ロックか channel かの選択

- 検出: `sync.Mutex` / `RWMutex`、`sync.Once`、`atomic`、mutex を含む struct の値渡し
- 問う範囲: 共有状態の保護か、所有権の受け渡しか。なぜその道具か。mutex を含む struct をコピーしていないか
- 検証: `go vet`（copylocks）、`go test -race`。一次資料: Go Memory Model

### 共有 map とデータレース

- 検出: 複数 goroutine から触る map・slice・変数
- 問う範囲: どの goroutine がいつ触るか。同期はどこで取られているか
- 検証: `go test -race`。一次資料: Go Memory Model

### worker pool と pipeline

- 検出: 固定数の worker、fan-out / fan-in、段階をつなぐ channel
- 問う範囲: 並列数の決め方。下流が先に終わったとき上流はどうなるか
- 検証: キャンセル時の全段停止を確かめるテスト。一次資料: Go Concurrency Patterns: Pipelines

## 言語の idiom

### エラーの扱い

- 検出: `fmt.Errorf` の `%w`、`errors.Is` / `As`、センチネルエラー、`_` への代入
- 問う範囲: ラップする理由と、呼び出し側が何で判定するか。捨ててよいエラーか
- 検証: エラー経路のテスト、golangci-lint（errcheck）。一次資料: Go Code Review Comments「Error Handling」「Error Strings」

### interface の置き場所

- 検出: interface の定義、関数の引数・戻り値の型
- 問う範囲: 定義が使う側にあるか。なぜ interface か、具体型では何が困るか
- 検証: 一次資料: Effective Go「Interfaces」、Go Code Review Comments「Interfaces」

### レシーバと命名

- 検出: メソッド定義、レシーバ名、公開・非公開の識別子
- 問う範囲: ポインタと値の選択と、その型での一貫性。名前の長さとスコープの対応
- 検証: 一次資料: Go Code Review Comments「Receiver Type」「Variable Names」

### defer の評価タイミング

- 検出: `defer`、ループ内の defer、defer した関数への引数
- 問う範囲: 引数はいつ評価されるか。ループ内で積んだ defer はいつ解放されるか
- 検証: 実行順を確かめる小さな再現。一次資料: Effective Go「Defer」

### slice と map の性質

- 検出: `append`、部分スライス、nil map への書き込み
- 問う範囲: append の結果をなぜ受け直すか。部分スライスが元の配列を保持し続ける条件は何か
- 検証: len / cap を確かめる再現テスト。一次資料: Effective Go「Slices」「Maps」

### 早期 return と happy path

- 検出: エラー分岐の書き方、深いネスト
- 問う範囲: なぜエラー側を先に返すか。正常系のインデントを浅く保つ理由は何か
- 検証: 一次資料: Go Code Review Comments「Indent Error Flow」

### table-driven tests

- 検出: テストコードの構造、ケースの並べ方
- 問う範囲: なぜテーブルにまとめるか。エラー経路のケースが含まれているか
- 検証: テストの実行。一次資料: Go Wiki「TableDrivenTests」
