# ADR 0002：Python に統一し、uv・pytest・ruff・pyright で開発する

- 状態：**承認**（2026-10-30、オーナー）
- 関係する記録：[requirements.md](../requirements.md) の 5 章（D2・決定 14）、[ADR 0001](0001-write-cues-to-master-db.md)、[スパイク 1](../spikes/01-vocal-detection.md)・[スパイク 4](../spikes/04-db-write.md)

## 背景

Phase 3 で、あとから変えにくいことのうち「何で書き、どう動かし、どう確かめるか」を決める。CLAUDE.md の未決定事項の「実装言語」「Python の環境管理ツール」と、requirements.md 5 章の注意（テストとリンターの道具は Phase 3 で決める）にあたる。

前提：

- 解析と ML の道具（Demucs、pyrekordbox、numpy など）は Python にしかない、または Python が一番そろっている
- master.db の読み書きは pyrekordbox に頼る（ADR 0001）。最新の 0.5.0 は Python 3.11 以上が必要。スパイクは Python 3.10・pyrekordbox 0.4.4 で動かした
- Python 3.10 は 2026-10 でサポートが終わる
- オーナーは TypeScript が主戦場で、Python は不慣れ（CLAUDE.md 3 章）
- 個人データを使わないテストは GitHub Actions（Linux）でも回す（決定 14）

## 決めること

1. 実装言語（CLI と MCP サーバーも含めて）
2. Python のバージョン
3. 環境管理ツール
4. テスト・リンター・フォーマッター・型チェック

## 1. 実装言語

| 案 | 内容 | 良い点 | 気になる点 |
|---|---|---|---|
| **A. Python に統一（推奨）** | 解析・推定・DB の読み書き・CLI・MCP サーバーを全部 Python で書く | 言語の境目がなく、データの受け渡しが関数呼び出しで済む。MCP には公式の Python SDK がある。テストと CI が 1 種類で済む | オーナーが不慣れな言語で全部書く |
| B. 解析は Python、CLI と MCP は TypeScript | Python を別プロセスとして呼び、JSON でやりとりする | CLI と MCP を慣れた言語で書ける | 2 つの言語の環境・テスト・CI が要る。境目の形（JSON）を両側で保つ必要がある。MVP の CLI は薄いので、分ける得が小さい |

**推奨は A。** MVP の CLI と MCP は推定と書き込みを呼ぶだけの薄い層なので、言語を分ける手間に見合わない。Python に慣れることも目的（CLAUDE.md 2 章の「音声解析・機械学習の学習」）に合う。

## 2. Python のバージョン

| 案 | 良い点 | 気になる点 |
|---|---|---|
| 3.10（スパイクのまま） | スパイクで動いた組み合わせのまま | 2026-10 でサポート終了。pyrekordbox 0.5.0 が使えない |
| 3.11 | pyrekordbox 0.5.0 が使える | 3.12 より選ぶ理由が特にない |
| **3.12（推奨）** | pyrekordbox 0.5.0 が使える。torch など重いライブラリも対応が進んでいて、新しすぎない | Demucs が 3.12 で入るかは Sprint 0 で確かめる |
| 3.13 | いちばん新しい | 重いライブラリ（torch、Demucs の依存）で対応が遅れていることがある |

**推奨は 3.12。** uv で Python 本体も入れるので、pyenv の 3.10 とは別に管理できる。Demucs が 3.12 で入らなければ 3.11 に下げる。

### pyrekordbox を 0.5.0 に上げることについて

スパイク 4 の書き込みは 0.4.4 で確かめた。0.5.0 に上げたら、DB に書くコードを最初に動かすとき（Sprint 3）に、テスト用の曲で書いて画面で確かめ直す（D7）。読み取りは Sprint 0 で、master.db のコピーで確かめる。

## 3. 環境管理ツール

| 案 | 良い点 | 気になる点 |
|---|---|---|
| **uv（推奨）** | Python 本体・仮想環境・依存・ロックファイルを 1 つで扱える。速い。`pyproject.toml` ＋ `uv.lock` で、npm の `package.json` ＋ `package-lock.json` に近い感覚で使える。GitHub Actions 用の公式の setup がある | 比較的新しい道具（ただし広く使われている） |
| Poetry | 実績が長い | Python 本体は別に入れる必要がある。uv より遅い |
| pip ＋ venv | 標準の道具だけ | ロックファイルがなく、再現性を自分で保つ必要がある |

**推奨は uv。**

## 4. テスト・リンター・フォーマッター・型チェック

| 役割 | 推奨 | 理由・ほかの案 |
|---|---|---|
| テスト | **pytest** | Python の事実上の標準。Jest に近い書き味。標準の unittest は書く量が多い |
| リンターとフォーマッター | **ruff** | 1 つでリンター（ESLint の役）とフォーマッター（Prettier の役）を兼ね、速い。flake8 ＋ black の組み合わせを置き換えられる |
| 型チェック | **pyright**（strict に近い設定から始める） | TypeScript の `strict` に近い感覚で型の抜けを指摘してくれる。VS Code の Pylance と同じ中身。mypy は実績が長いが遅く、推論が弱い。Astral の ty はまだ新しすぎる |

- 型の付いていないライブラリ（pyrekordbox、Demucs など）は、自分のコードとの境目で型を付けて包む。中まで strict にはしない
- 実行は `uv run pytest`、`uv run ruff check`、`uv run ruff format --check`、`uv run pyright` の 4 つ。CI（GitHub Actions、Linux）でも同じものを回し、通らなければマージしない（requirements.md 5 章）
- 重い依存（torch・Demucs）は、CI で入れなくても個人データを使わないテストが回るように、依存のグループを分ける（細かい分け方は Sprint 0 で決める）

## 決定

- **言語は Python に統一する**（CLI・MCP サーバーも含む）
- **Python は 3.12。** Demucs が入らなければ 3.11 に下げる
- **環境管理は uv**（`pyproject.toml` ＋ `uv.lock`）
- **テストは pytest、リンターとフォーマッターは ruff、型チェックは pyright**

ruff は、TypeScript でいう Biome に近い位置づけ（Rust 製で速く、リンターとフォーマッターを 1 つで兼ねる）。

## 結果

- CLAUDE.md の「実装言語」「Python の環境管理ツール」を、未決定事項から決定済みの技術方針に移した
- Sprint 0 で `pyproject.toml`・`uv.lock`・CI の設定を作る。スパイクのスクリプト（`scripts/spikes/`）は使い捨てなので、新しい環境には移さない
- Sprint 0 で確かめること：Python 3.12 で Demucs と pyrekordbox 0.5.0 が入るか。pyrekordbox 0.5.0 で master.db のコピーを読めるか
