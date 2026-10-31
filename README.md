# cueing-bot

DJ 楽曲を解析し、Rekordbox のキュー（Memory Cue・Hot Cue）の下書きを自動で打つアプリ。自信のないところには「要確認」を付け、DJ が要確認のところだけ聴いて直せるようにする。

目標は、キュー打ちに使う時間を今の 1/3 以下にすること（[concept.md](docs/concept.md)）。

> 開発中（Sprint 0）。まだキューは打てない。

## 必要なもの

- macOS（開発は MacBook Pro M4 / 16GB）。CI は Linux で回す
- [uv](https://docs.astral.sh/uv/)（Python 本体もこれで入る。Python 3.12）
- Rekordbox 7.2.18（書き込みを確かめたバージョン）

## セットアップ

```sh
uv sync               # 開発の依存だけ（CI と同じ。npm ci に近い）
uv sync --all-groups  # Mac で音源も扱うとき（Demucs・torch。重い）
```

`uv sync` はロックファイルどおりに入れ直すので、`--all-groups` を付けずに実行すると Demucs・torch が外れる。Mac では毎回 `uv sync --all-groups` を使う。

## 開発のコマンド

| やること | コマンド |
|---|---|
| テスト | `uv run pytest` |
| 個人データを使うテスト（Mac だけ） | `uv run pytest -m personal_data` |
| リンター | `uv run ruff check` |
| フォーマット | `uv run ruff format`（確かめるだけなら `--check`） |
| 型チェック | `uv run pyright` |

CI（GitHub Actions）でも同じ 4 つを回す。PR の進め方とレビューの観点は [REVIEW.md](REVIEW.md) と [requirements.md](docs/requirements.md) 5 章。

## データの置き場

音源・ライブラリのデータ・推定結果は、リポジトリの外の data フォルダ（既定は `~/llm/cueing-bot/data/`）に置く。リポジトリには入れない。

## ドキュメント

- [concept.md](docs/concept.md)：なぜ作るか
- [cueing-theory.md](docs/cueing-theory.md)：キューの打ち方のルール
- [requirements.md](docs/requirements.md)：要件と完成の定義
- [architecture.md](docs/architecture.md)：全体の構成
- [docs/adr/](docs/adr/)：技術的な意思決定
- [development-process.md](docs/development-process.md)：進め方と現在地
