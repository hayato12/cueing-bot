"""スパイク 1：音源分離（Demucs）でボーカルだけを取り出し、ボーカルが入る小節（A メロの頭）を見つける。

使い方（リポジトリ直下で。demucs を入れた使い捨ての venv を使う）:
    # 1. 対象の曲を選び、手動キューから「A メロの頭」の正解を推定して tracks.csv に書く
    .venv/bin/python scripts/spikes/spike1_vocal_entry.py pick <エクスポート XML> <出力フォルダ>
    # 2. tracks.csv の曲を 1 曲ずつ別プロセスで分離し、時間とメモリを測る
    .venv/bin/python scripts/spikes/spike1_vocal_entry.py all <出力フォルダ> [mps|cpu]
    # 3. 検出した小節と正解を比べる
    .venv/bin/python scripts/spikes/spike1_vocal_entry.py report <出力フォルダ>

出力フォルダには曲名入りのファイルができるので、リポジトリの外（data/spike1/ など）を指定すること。
読むのは音源ファイルとエクスポート XML だけ。音源ファイルも Rekordbox の DB も書き換えない。
"""

import csv
import json
import random
import re
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100  # htdemucs が想定するサンプリング周波数
N_TRACKS = 10
SEED = 1  # 曲の選び方を毎回同じにするための乱数の種


# ---------------------------------------------------------------- 1. 曲を選ぶ


def bar_len(bpm: float) -> float:
    """1 小節の秒数（4/4 拍子）。"""
    return 4 * 60 / bpm


def guess_a_melo_bar(cue_secs: list[float], inizio: float, bpm: float) -> int | None:
    """手動のメモリーキューから「A メロの頭」の小節番号を推定する。

    cueing-theory.md 3.1 では、イントロのメモリーキューは L 小節ずつ並び、最後の 1 つが
    イントロの終わり（＝A メロの頭）になる。そこで、最初のメモリーキューから
    「間が 2L 小節以内」で続くキューをイントロのかたまりと見なし、その最後を正解とする。
    かたまりが 1 つだけ、またはキューが小節の頭にない曲は、推定があいまいなので使わない（None）。
    """
    unit = 8 if bpm > 120 else 4  # L（小節）
    bars = sorted((s - inizio) / bar_len(bpm) + 1 for s in cue_secs)
    if any(abs(b - round(b)) > 0.05 for b in bars):  # 小節の頭から 1/20 小節以上ずれたキューがある
        return None
    bars = [round(b) for b in bars]
    cluster = [bars[0]]
    for b in bars[1:]:
        if b - cluster[-1] > 2 * unit:
            break
        cluster.append(b)
    return cluster[-1] if len(cluster) >= 2 else None


def pick(export_path: str, out_dir: Path) -> None:
    root = ET.parse(export_path).getroot()
    by_id = {t.get("TrackID"): t for t in root.find("COLLECTION")}
    # HOUSE フォルダ（オーナーのプレイリストのフォルダ。UKG なども中にある）の曲だけを候補にする
    house = next(n for n in root.find("PLAYLISTS/NODE").findall("NODE") if n.get("Name") == "HOUSE")
    ids = sorted({t.get("Key") for t in house.iter("TRACK")})

    candidates = []
    for tid in ids:
        t = by_id[tid]
        tempos = t.findall("TEMPO")
        if len(tempos) != 1:  # テンポが途中で変わる曲は小節の計算が面倒なので除く
            continue
        inizio, bpm = float(tempos[0].get("Inizio")), float(tempos[0].get("Bpm"))
        mems = [float(m.get("Start")) for m in t.findall("POSITION_MARK") if m.get("Num") == "-1" and m.get("Type") == "0"]
        if len(mems) < 2:
            continue
        truth = guess_a_melo_bar(mems, inizio, bpm)
        if truth is None:
            continue
        path = urllib.parse.unquote(t.get("Location").removeprefix("file://localhost"))
        if not Path(path).exists():
            continue
        candidates.append({"name": f"{t.get('Artist')} - {t.get('Name')}", "path": path,
                           "bpm": bpm, "inizio": inizio, "truth_bar": truth})

    random.Random(SEED).shuffle(candidates)  # 決まった種で並べ替えて、先頭から選ぶ（偏りを減らすため）
    chosen = candidates[:N_TRACKS]
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "tracks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(chosen[0]))
        w.writeheader()
        w.writerows(chosen)
    print(f"候補 {len(candidates)} 曲から {len(chosen)} 曲を選びました: {out_dir / 'tracks.csv'}")
    for c in chosen:
        print(f"  {c['truth_bar']:>4} 小節目  {c['bpm']:.0f} BPM  {c['name']}")


# ---------------------------------------------------------------- 2. 1 曲を分離する


def decode(path: str) -> np.ndarray:
    """ffmpeg で音源を 44.1kHz・ステレオ・32bit float に変換して読み込む。形は (2, サンプル数)。"""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SAMPLE_RATE), "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).T.copy()


def separate_one(index: int, out_dir: Path, device: str) -> None:
    """tracks.csv の index 番目の曲を分離し、ボーカルの音量（拍ごと）と処理時間を JSON に書く。

    メモリを曲ごとに測るため、この関数は 1 曲ごとに別プロセスで呼ぶ（all から呼ばれる）。
    """
    import torch  # 重いライブラリは、使うときだけ読み込む
    from demucs.apply import apply_model
    from demucs.pretrained import get_model

    track = read_tracks(out_dir)[index]
    t0 = time.perf_counter()
    audio = decode(track["path"])
    t_decode = time.perf_counter() - t0

    model = get_model("htdemucs")  # 初回だけモデル（約 80MB）をダウンロードし、以後はキャッシュを使う
    model.eval()  # 学習ではなく推論のモードにする
    wav = torch.from_numpy(audio)
    # Demucs の慣習：曲全体の平均と標準偏差で正規化してから分離し、あとで戻す
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / ref.std()
    t1 = time.perf_counter()
    with torch.no_grad():  # 勾配（学習用の情報）を記録しない。メモリと時間の節約
        sources = apply_model(model, wav[None], device=device, split=True, overlap=0.25, progress=False)[0]
    if device == "mps":
        torch.mps.synchronize()  # GPU の処理が終わるのを待ってから時間を測る
    t_sep = time.perf_counter() - t1
    sources = sources * ref.std() + ref.mean()
    vocals = sources[model.sources.index("vocals")].mean(0).numpy()  # ボーカルだけ、モノラルにする

    # 拍ごとの音量（RMS を dB に）。拍の位置はエクスポートのビートグリッド（Inizio と BPM）から計算
    bpm, inizio = float(track["bpm"]), float(track["inizio"])
    beat = 60 / bpm
    n_beats = int((len(vocals) / SAMPLE_RATE - inizio) / beat)
    rms_db = []
    for i in range(n_beats):
        a = int((inizio + i * beat) * SAMPLE_RATE)
        b = int((inizio + (i + 1) * beat) * SAMPLE_RATE)
        rms = float(np.sqrt(np.mean(vocals[a:b] ** 2)) + 1e-9)
        rms_db.append(20 * np.log10(rms))

    result = {
        "index": index, "device": device, "duration_sec": len(vocals) / SAMPLE_RATE,
        "decode_sec": t_decode, "separate_sec": t_sep,
        "mps_driver_mb": torch.mps.driver_allocated_memory() / 2**20 if device == "mps" else None,
        "vocal_rms_db_per_beat": rms_db,
    }
    (out_dir / "results").mkdir(exist_ok=True)
    (out_dir / "results" / f"{index:02d}.json").write_text(json.dumps(result))


def run_all(out_dir: Path, device: str) -> None:
    """1 曲ずつ別プロセスで分離する。macOS の /usr/bin/time -l でピークのメモリも測る。"""
    n = len(read_tracks(out_dir))
    for i in range(n):
        proc = subprocess.run(
            ["/usr/bin/time", "-l", sys.executable, __file__, "one", str(out_dir), str(i), device],
            capture_output=True, text=True, env={"PYTORCH_ENABLE_MPS_FALLBACK": "1", "PATH": "/opt/homebrew/bin:/usr/bin:/bin"},
        )
        # /usr/bin/time -l の出力（標準エラー）から、ピークのメモリ使用量を拾う
        mem = {}
        for line in proc.stderr.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[1] in ("maximum resident set size", "peak memory footprint"):
                mem[parts[1]] = int(parts[0]) / 2**20  # バイト → MB
        if proc.returncode != 0:
            print(f"[{i}] 失敗:\n{proc.stderr[-2000:]}")
            continue
        p = out_dir / "results" / f"{i:02d}.json"
        r = json.loads(p.read_text())
        r["max_rss_mb"] = mem.get("maximum resident set size")
        r["peak_footprint_mb"] = mem.get("peak memory footprint")
        p.write_text(json.dumps(r))
        print(f"[{i}] 分離 {r['separate_sec']:.1f}s（曲 {r['duration_sec'] / 60:.1f} 分）"
              f" RSS {r['max_rss_mb']:.0f}MB footprint {r['peak_footprint_mb'] or 0:.0f}MB")


# ---------------------------------------------------------------- 3. 入りを検出して比べる


def detect_bar(rms_db: list[float], drop_db: float) -> tuple[int | None, float]:
    """ボーカルが入る小節（1 始まり）を返す。

    曲の中でボーカルが大きい所（拍ごとの音量の上位 5%）を基準にし、そこから drop_db 下までを
    「ボーカルがある」と見なす。ある拍が 1 小節（4 拍）のうち 2 拍以上ある小節が 2 小節続いたら、
    その最初の小節を入りとする（一瞬の声やノイズを拾わないため）。
    基準そのものが小さい（-40dB 未満）曲は「ボーカルなし」として None を返す。
    """
    db = np.array(rms_db)
    ref = float(np.percentile(db, 95))
    if ref < -40:
        return None, ref
    on = db >= ref - drop_db
    n_bars = len(on) // 4
    bar_on = [on[i * 4:(i + 1) * 4].sum() >= 2 for i in range(n_bars)]
    for i in range(n_bars - 1):
        if bar_on[i] and bar_on[i + 1]:
            return i + 1, ref
    return None, ref


def read_tracks(out_dir: Path) -> list[dict]:
    """tracks.csv を読む。表計算アプリで保存すると 1 行目に "tracks" という表題が入ることがあるので、飛ばす。"""
    f = open(out_dir / "tracks.csv", encoding="utf-8")
    if not f.readline().startswith("tracks"):
        f.seek(0)  # 表題がなければ先頭に戻る
    return list(csv.DictReader(f))


def report(out_dir: Path) -> None:
    tracks = read_tracks(out_dir)
    rows = []
    for i, tr in enumerate(tracks):
        p = out_dir / "results" / f"{i:02d}.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text())
        row = {"i": i, "name": tr["name"], "bpm": float(tr["bpm"]), "truth": int(tr["truth_bar"]),
               "sep_sec": r["separate_sec"], "min": r["duration_sec"] / 60,
               "rss_mb": r.get("max_rss_mb"), "footprint_mb": r.get("peak_footprint_mb")}
        for drop in (10, 15, 20):  # しきい値を変えると結果がどう動くかも見る
            bar, ref = detect_bar(r["vocal_rms_db_per_beat"], drop)
            row[f"bar@{drop}"] = bar
            row["ref_db"] = round(ref, 1)
        rows.append(row)
    with open(out_dir / "report.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    for drop in (10, 15, 20):
        hits = sum(1 for r in rows if r[f"bar@{drop}"] is not None and abs(r[f"bar@{drop}"] - r["truth"]) <= 1)
        exact = sum(1 for r in rows if r[f"bar@{drop}"] == r["truth"])
        print(f"［手動キューからの推定が正解］しきい値 -{drop}dB: 一致 {exact}/{len(rows)}、±1 小節以内 {hits}/{len(rows)}")

    # オーナーが聴いて決めた正解（merody_a_head 列）があれば、それでも比べる。
    # セルは「41（改行）メモ」や「3 or 11」のような形なので、1 行目の数字を全部拾い、どれかに入れば当たりとする
    if "merody_a_head" in tracks[0]:
        owner = {i: [int(x) for x in re.findall(r"\d+", tr["merody_a_head"].splitlines()[0])] for i, tr in enumerate(tracks)}
        for drop in (10, 15, 20):
            hits = sum(1 for r in rows if r[f"bar@{drop}"] is not None
                       and any(abs(r[f"bar@{drop}"] - b) <= 1 for b in owner[r["i"]]))
            print(f"［オーナーの正解］しきい値 -{drop}dB: ±1 小節以内 {hits}/{len(rows)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pick" and len(sys.argv) == 4:
        pick(sys.argv[2], Path(sys.argv[3]))
    elif cmd == "one" and len(sys.argv) == 5:
        separate_one(int(sys.argv[3]), Path(sys.argv[2]), sys.argv[4])
    elif cmd == "all" and len(sys.argv) in (3, 4):
        run_all(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) == 4 else "mps")
    elif cmd == "report" and len(sys.argv) == 3:
        report(Path(sys.argv[2]))
    else:
        raise SystemExit(__doc__)
