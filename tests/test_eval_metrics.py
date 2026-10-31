from cueing_bot.evaluate.metrics import Level, evaluate
from cueing_bot.evaluate.truth import TrackTruth
from cueing_bot.model import Beat, CueType, Estimate, EstimatedCue, ReviewReason, Role

BEATS = tuple(Beat(i * 500.0, i % 4 + 1) for i in range(800))
FULL = {
    Role.INTRO_END: (128,),
    Role.INTRO_END_MINUS_2L: (64,),
    Role.MAIN_HOT: (320, 512),
    Role.OUTRO_HOT: (576,),
}


def truth(track_id: str = "t", roles: dict[Role, tuple[int, ...]] | None = None) -> TrackTruth:
    return TrackTruth(track_id, BEATS, FULL if roles is None else roles)


def est(
    track_id: str = "t",
    *,
    intro: int | None = 128,
    minus_2l: int | None = 64,
    hots: tuple[int, ...] = (320, 512),
    outro: int | None = 576,
    review: bool = False,
) -> Estimate:
    cues: list[EstimatedCue] = []
    if intro is not None:
        cues.append(EstimatedCue(CueType.MEMORY, intro, Role.INTRO_END))
    if minus_2l is not None:
        cues.append(EstimatedCue(CueType.MEMORY, minus_2l, Role.INTRO_END_MINUS_2L))
    pads = (CueType.HOT_A, CueType.HOT_B, CueType.HOT_C)
    cues += [EstimatedCue(pads[i], b, Role.MAIN_HOT) for i, b in enumerate(hots)]
    if outro is not None:
        cues.append(EstimatedCue(CueType.HOT_H, outro, Role.OUTRO_HOT))
    reasons = (ReviewReason("main_unclear", "メインが分からない"),) if review else ()
    return Estimate(track_id, "fp", tuple(cues), reasons, "test-v0")


def test_perfect_estimate_hits_everything() -> None:
    ev = evaluate([truth()], {"t": est()})
    s = ev.scores
    for role in FULL:
        assert s.roles[role].precision().value == 1.0
        assert s.roles[role].recall().value == 1.0
    assert (s.m2.num, s.m2.den) == (1, 1)
    assert (s.m3.num, s.m3.den) == (1, 1)
    assert (s.m4.num, s.m4.den) == (0, 1)


def test_two_beats_off_is_a_miss_but_same_bar_and_four_beats_off_is_within_one_bar() -> None:
    s = evaluate([truth()], {"t": est(intro=130, minus_2l=68)}).scores
    intro = s.roles[Role.INTRO_END]
    assert intro.hits == {Level.SAME_BEAT: 0, Level.SAME_BAR: 1, Level.WITHIN_1_BAR: 1}
    minus = s.roles[Role.INTRO_END_MINUS_2L]
    assert minus.hits == {Level.SAME_BEAT: 0, Level.SAME_BAR: 0, Level.WITHIN_1_BAR: 1}
    assert s.m2.num == 0


def test_main_hot_counts_precision_and_recall_separately() -> None:
    ev = evaluate([truth()], {"t": est(hots=(320, 400, 512))})
    hot = ev.scores.roles[Role.MAIN_HOT]
    assert (hot.precision().num, hot.precision().den) == (2, 3)
    assert (hot.recall().num, hot.recall().den) == (2, 2)
    assert ev.tracks[0].all_correct is False  # 余計なキューがあれば全的中ではない


def test_main_hot_pairs_nearest_first() -> None:
    ev = evaluate([truth()], {"t": est(hots=(516, 320))})
    outcome = ev.tracks[0].roles[Role.MAIN_HOT]
    assert outcome.estimated == (320, 516)
    assert sorted(outcome.diffs) == [0, 4]


def test_no_truth_and_no_estimate_is_counted_as_correct_none() -> None:
    roles = {**FULL, Role.OUTRO_HOT: ()}
    s = evaluate([truth(roles=roles)], {"t": est(outro=None)}).scores
    outro = s.roles[Role.OUTRO_HOT]
    assert (outro.none_tracks, outro.none_correct) == (1, 1)
    assert outro.precision().value is None  # 出していないので分母 0
    assert s.m2.num == 1


def test_estimate_when_truth_is_none_is_a_false_positive() -> None:
    roles = {**FULL, Role.OUTRO_HOT: ()}
    s = evaluate([truth(roles=roles)], {"t": est()}).scores
    outro = s.roles[Role.OUTRO_HOT]
    assert (outro.none_tracks, outro.none_correct) == (1, 0)
    assert (outro.precision().num, outro.precision().den) == (0, 1)
    assert s.m2.num == 0


def test_missing_estimate_counts_as_nothing_found_and_needs_review() -> None:
    s = evaluate([truth("a"), truth("b")], {"a": est("a")}).scores
    assert s.n_missing_estimate == 1
    assert s.roles[Role.INTRO_END].recall().value == 0.5
    assert (s.m4.num, s.m4.den) == (1, 2)


def test_unknown_role_is_skipped_and_track_leaves_m2() -> None:
    roles = {r: b for r, b in FULL.items() if r != Role.INTRO_END_MINUS_2L}
    ev = evaluate([truth(roles=roles)], {"t": est(minus_2l=999)})
    s = ev.scores
    assert s.roles[Role.INTRO_END_MINUS_2L].n_tracks == 0
    assert s.roles[Role.INTRO_END_MINUS_2L].n_estimated == 0
    assert ev.tracks[0].all_correct is None
    assert s.m2.den == 0


def test_m3_and_m4_split_by_review() -> None:
    truths = [truth("ok"), truth("flag_hit"), truth("bad")]
    estimates = {
        "ok": est("ok"),
        "flag_hit": est("flag_hit", review=True),
        "bad": est("bad", intro=0),
    }
    s = evaluate(truths, estimates).scores
    assert (s.m2.num, s.m2.den) == (2, 3)
    assert (s.m3.num, s.m3.den) == (1, 2)  # 要確認なしは ok と bad
    assert (s.m4.num, s.m4.den) == (1, 3)


def test_cue_level_review_reason_also_flags_the_track() -> None:
    base = est()
    flagged = Estimate(
        base.track_id,
        base.fingerprint,
        (
            *base.cues[1:],
            EstimatedCue(CueType.MEMORY, 128, Role.INTRO_END, (ReviewReason("x", "x"),)),
        ),
        (),
        base.estimator,
    )
    assert flagged.needs_review
    assert evaluate([truth()], {"t": flagged}).scores.m4.num == 1
