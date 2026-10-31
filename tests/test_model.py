import dataclasses

from cueing_bot.model import TrackInput


def test_track_input_has_no_existing_cues() -> None:
    # 推定に正解（既存のキュー）が紛れ込まないように、TrackInput にはキューの項目を持たせない
    # （architecture.md 3 章）
    names = {f.name for f in dataclasses.fields(TrackInput)}
    assert not any("cue" in n.lower() for n in names)
