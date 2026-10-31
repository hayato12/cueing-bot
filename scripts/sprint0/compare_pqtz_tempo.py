"""Sprint 0: 解析ファイルの PQTZ（グリッド）が、XML エクスポートの TEMPO と同じかを確かめる（ADR 0003）。

使い方（Mac）:

    uv run python scripts/sprint0/compare_pqtz_tempo.py <rekordbox から書き出した XML>

XML に入っている曲ごとに、TEMPO から計算した拍の時刻と PQTZ の拍の時刻を比べ、
いちばん大きいずれ（ms）と、TEMPO の拍番号（Battito）と PQTZ の小節内の拍番号が合うかを出す。
曲名は出さず、曲の ID だけを出す。
"""

from __future__ import annotations

import argparse
import bisect
from pathlib import Path
from typing import Any

from pyrekordbox.rbxml import RekordboxXml  # pyright: ignore[reportMissingTypeStubs]

from cueing_bot import config
from cueing_bot.library.reader import TrackReadError, open_library
from cueing_bot.model import Beat


def expected_beats(tempos: list[Any], end_ms: float) -> list[tuple[float, int]]:
    """TEMPO の列から、拍の時刻（ms）と小節内の拍番号の列を作る。"""
    out: list[tuple[float, int]] = []
    for i, tp in enumerate(tempos):
        start = float(tp.Inizio) * 1000.0
        stop = float(tempos[i + 1].Inizio) * 1000.0 if i + 1 < len(tempos) else end_ms + 1.0
        step = 60_000.0 / float(tp.Bpm)
        n = 0
        while start + n * step < stop - 1e-6:
            out.append((start + n * step, (int(tp.Battito) - 1 + n) % 4 + 1))
            n += 1
    return out


def compare(beats: tuple[Beat, ...], tempos: list[Any]) -> tuple[float, int, int]:
    """(いちばん大きいずれ ms, 拍番号が合わない拍の数, 比べた拍の数) を返す。"""
    # 最後の拍が丸めで切れないよう、終わりに 50 ms の余裕を持たせる
    exp = expected_beats(tempos, beats[-1].time_ms + 50.0)
    times = [t for t, _ in exp]
    worst = 0.0
    mismatched = 0
    for b in beats:
        i = bisect.bisect_left(times, b.time_ms)
        cands = [j for j in (i - 1, i) if 0 <= j < len(exp)]
        j = min(cands, key=lambda k: abs(times[k] - b.time_ms))
        worst = max(worst, abs(times[j] - b.time_ms))
        if exp[j][1] != b.beat_in_bar:
            mismatched += 1
    return worst, mismatched, len(beats)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("xml", type=Path)
    args = parser.parse_args()

    xml: Any = RekordboxXml(str(args.xml))
    with open_library(config.rekordbox_dir(), config.data_dir() / "tmp") as lib:
        print("id\tTEMPO の数\tPQTZ の拍\t最大のずれ(ms)\t拍番号の不一致")
        for tr in xml.get_tracks():
            tempos = list(getattr(tr, "tempos", []) or [])
            if not tempos:
                continue
            # pyrekordbox は XML の Location を先頭の "/" なしで返すので、DB の FolderPath に合わせる
            location = str(tr.Location)
            if not location.startswith("/"):
                location = "/" + location
            track_id = lib.track_id_for_path(location)
            if track_id is None:
                print(f"?\t{len(tempos)}\t-\t-\tDB に見つからない")
                continue
            try:
                t = lib.track_input(track_id)
            except TrackReadError as e:
                print(f"{track_id}\t{len(tempos)}\t-\t-\t{e}")
                continue
            worst, mism, n = compare(t.beats, tempos)
            print(f"{track_id}\t{len(tempos)}\t{n}\t{worst:.1f}\t{mism}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
