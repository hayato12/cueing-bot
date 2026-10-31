"""data フォルダへの保存と読み出し（architecture.md 4 章）。

置き場はリポジトリの外の data フォルダ（`config.data_dir()`）。ここでは JSON の読み書きだけを行い、
中身の意味は `model`・`evaluate` が持つ。
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from cueing_bot.evaluate.results import EvalRecord, record_from_dict, record_to_dict
from cueing_bot.model import CueType, Estimate, EstimatedCue, ReviewReason, Role

ESTIMATES_SCHEMA_VERSION = 1


# --- 推定結果 --------------------------------------------------------------------


def _reasons_to_list(reasons: Iterable[ReviewReason]) -> list[dict[str, str]]:
    return [{"code": r.code, "message": r.message} for r in reasons]


def _reasons_from_list(items: Iterable[Mapping[str, Any]]) -> tuple[ReviewReason, ...]:
    return tuple(ReviewReason(str(r["code"]), str(r["message"])) for r in items)


def estimate_to_dict(e: Estimate) -> dict[str, Any]:
    return {
        "track_id": e.track_id,
        "fingerprint": e.fingerprint,
        "estimator": e.estimator,
        "track_review": _reasons_to_list(e.track_review),
        "cues": [
            {
                "cue_type": c.cue_type.name,
                "beat_index": c.beat_index,
                "role": c.role.value,
                "review": _reasons_to_list(c.review),
            }
            for c in e.cues
        ],
    }


def estimate_from_dict(d: Mapping[str, Any]) -> Estimate:
    return Estimate(
        track_id=str(d["track_id"]),
        fingerprint=str(d["fingerprint"]),
        cues=tuple(
            EstimatedCue(
                cue_type=CueType[str(c["cue_type"])],
                beat_index=int(c["beat_index"]),
                role=Role(str(c["role"])),
                review=_reasons_from_list(c.get("review", [])),
            )
            for c in d["cues"]
        ),
        track_review=_reasons_from_list(d.get("track_review", [])),
        estimator=str(d["estimator"]),
    )


def save_estimates(path: Path, estimates: Iterable[Estimate]) -> None:
    """推定結果を 1 つの JSON に書く（実行ごと、中は曲ごと）。"""
    data = {
        "schema_version": ESTIMATES_SCHEMA_VERSION,
        "estimates": [estimate_to_dict(e) for e in estimates],
    }
    _write_json(path, data)


def load_estimates(path: Path) -> dict[str, Estimate]:
    """推定結果を読み、曲の ID ごとにまとめる。同じ曲が 2 回あれば誤りにする。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != ESTIMATES_SCHEMA_VERSION:
        raise ValueError(f"推定結果の形の版が違います：{data.get('schema_version')}")
    out: dict[str, Estimate] = {}
    for item in data["estimates"]:
        e = estimate_from_dict(item)
        if e.track_id in out:
            raise ValueError(f"同じ曲の推定が 2 つあります：ID={e.track_id}")
        out[e.track_id] = e
    return out


# --- 評価の結果 ------------------------------------------------------------------


def save_eval_record(directory: Path, record: EvalRecord) -> Path:
    """`eval/` に日時付きの名前で保存する。"""
    estimator = "+".join(record.estimators) or "none"
    name = f"{record.created_at:%Y%m%d-%H%M%S}-{record.dataset.kind}-{estimator}.json"
    path = directory / _safe_name(name)
    _write_json(path, record_to_dict(record))
    return path


def load_eval_records(directory: Path) -> list[EvalRecord]:
    """`eval/` の記録を全部読む。形の版が違う古い記録は飛ばす。"""
    if not directory.is_dir():
        return []
    out: list[EvalRecord] = []
    for p in sorted(directory.glob("*.json")):
        try:
            out.append(record_from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except (ValueError, KeyError):
            continue
    return out


# --- 書き込みの記録 --------------------------------------------------------------


def written_track_ids(directory: Path) -> set[str]:
    """アプリが書いた曲の ID（`writes/` の記録から）。評価データ a から外すのに使う。

    記録の形は Sprint 3（S6）で決めるが、少なくとも `{"tracks": [{"track_id": ...}, ...]}` を持たせる。
    読めない記録があったら、黙って飛ばさずに誤りにする（外し漏れると評価の数字が甘くなるため）。
    """
    if not directory.is_dir():
        return set()
    ids: set[str] = set()
    for p in sorted(directory.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        try:
            ids.update(str(t["track_id"]) for t in data["tracks"])
        except (KeyError, TypeError) as e:
            raise ValueError(f"書き込みの記録を読めません：{p.name}") from e
    return ids


# --- 共通 -----------------------------------------------------------------------


def _safe_name(name: str) -> str:
    """推定の名前に `/` などが入っても、ほかのフォルダに書かないようにする。"""
    return "".join(ch if ch.isalnum() or ch in "-_.+" else "_" for ch in name)


def _write_json(path: Path, data: Any) -> None:
    """一時ファイルに書いてから名前を変える。途中で止まっても、壊れた JSON を残さない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def now() -> datetime:
    """記録の日時（ローカル時刻、秒まで）。テストで差し替えやすいように関数にしている。"""
    return datetime.now().astimezone().replace(microsecond=0)
