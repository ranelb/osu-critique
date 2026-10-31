"""The glossary: the one place the site's vocabulary is written down.

The dashboard prints terms that mean something specific here — "band-corrected
miss rate", "excess", "improver", "comfort SR". A reader who does not know them
cannot check the page, and a tool that measures things owes the reader the
definitions. So every term is defined once, here, and everything else links to
these anchors:

- ``/learn`` renders the whole list (one page, no JavaScript, stable anchors),
- ``partials/gloss.html`` turns a label into a link with the one-liner as its
  ``title``, so hovering or long-pressing explains a number in place.

``docs/`` remains the authority for *formulas and internals*; each entry links
there rather than restating a derivation. This file is the authority for the
wording, which is why the page and the tooltips cannot disagree.
"""
from __future__ import annotations

#: fields: id (anchor), group, term, short (one line, used as a tooltip),
#: long (a paragraph), how (bullets: how the number is produced), doc.
GROUPS = (
    ("numbers", "the numbers"),
    ("profile", "the profile"),
    ("recommend", "the recommendations"),
)

TERMS = (
    {
        "id": "accuracy",
        "group": "numbers",
        "term": "accuracy",
        "short": "weighted hit quality: 300 = 100%, 100 = 1/3, 50 = 1/6, miss = 0",
        "long": "The game's own weighted score over every object in the play. It "
                "punishes a miss far more than a mistimed hit, which is why it is "
                "quoted next to the miss rate and not instead of it.",
        "how": ["read from the replay's recorded counts, not from our judgement",
                "a failed play only counts the part that was played"],
        "doc": "../metrics.md",
    },
    {
        "id": "ur",
        "group": "numbers",
        "term": "unstable rate",
        "short": "spread of hit errors, times ten: lower is steadier",
        "long": "The standard deviation of your hit errors (ms) multiplied by 10. "
                "It says nothing about whether you are early or late — a perfectly "
                "consistent +20 ms player has a UR near zero — so it is read "
                "alongside the signed hit error.",
        "how": ["std of the judged press errors, x10",
                "median per window, because a single bad map should not move it"],
        "doc": "../metrics.md",
    },
    {
        "id": "pp",
        "group": "numbers",
        "term": "pp",
        "short": "performance points, from the cached pp run (needs the [stars] extra)",
        "long": "Performance points as computed by rosu-pp for the replay's mods. "
                "It is only present for plays you have run `osu-critique pp` over, "
                "so a sum here is a sum of the cached plays, not of everything.",
        "how": ["joined from out/pp_by_replay.json",
                "Relax/Autopilot are unranked and get no pp"],
        "doc": "../metrics.md",
    },
    {
        "id": "band-corrected-miss-rate",
        "group": "profile",
        "term": "band-corrected miss rate",
        "short": "your miss rate minus your own median miss rate at the same star rating",
        "long": "The raw miss rate mostly says how hard the map is, not what it is "
                "made of: a 7-star map costs everyone misses. Every play is "
                "therefore compared with your own median miss rate in the same "
                "half-star band. What is left is the part that is about the "
                "material rather than the difficulty.",
        "how": ["bands are 0.5 stars wide and need 8 runs before they get a median",
                "plays in a band with no median are left out of the profile"],
        "doc": "../recommend.md",
    },
    {
        "id": "median-split",
        "group": "profile",
        "term": "median split",
        "short": "your plays, cut in two at the middle value of one material dimension",
        "long": "For each material dimension the plays are sorted by that number "
                "and cut at the median. The two halves are then compared: same "
                "player, same corpus, only the material differs. The split value "
                "is printed so the comparison can be checked, and the halves are "
                "yours, so the thresholds are not someone else's idea of hard.",
        "how": ["cut at the median of your plays, not at a fixed number",
                "at least 20 runs must end up on each side"],
        "doc": "../recommend.md",
    },
    {
        "id": "excess",
        "group": "profile",
        "term": "excess",
        "short": "the band-corrected miss rate of one half, in percentage points",
        "long": "Positive means you miss more than your own baseline at that star "
                "rating; zero means the material costs you nothing extra; negative "
                "means you do better than usual on it. A weakness needs the worse "
                "half at least 0.5 pp above the better half and 1.5x its excess.",
        "how": ["excess = miss rate - band median miss rate",
                "the gate also needs 20 runs per side"],
        "doc": "../recommend.md",
    },
    {
        "id": "sustained-density",
        "group": "profile",
        "term": "sustained density",
        "short": "how many notes per second the map's longest unbroken runs carry",
        "long": "A map is not hard because it has notes; it is hard where the notes "
                "do not stop. The analysis finds runs of consecutive objects with a "
                "steady gap and a steady required cursor speed, and this dimension "
                "is the median notes-per-second of those runs. High means real "
                "sustained pressure, low means the map is made of single spikes.",
        "how": ["same detector the play analysis uses (metrics/streams.find_runs)",
                "duration is notes/second inside the detected runs"],
        "doc": "../library.md",
    },
    {
        "id": "stream-share",
        "group": "profile",
        "term": "stream share",
        "short": "share of the map whose spacing is 2-4 circle radii",
        "long": "The spacing between consecutive objects, measured from the "
                "previous object's end (a slider's tail), bucketed in circle radii. "
                "2-4 r is the classic stream spacing: dense enough to feel "
                "continuous, wide enough to need reading.",
        "how": ["buckets: dense <= 2 r, stream 2-4 r, jump 4-7 r, bigjump > 7 r"],
        "doc": "../library.md",
    },
    {
        "id": "jump-spacing",
        "group": "profile",
        "term": "jump spacing",
        "short": "share of the map that is 4+ circle radii between objects",
        "long": "Wide spacing: the cursor has to travel, and the taps are far "
                "apart. Jump and bigjump spacing are summed because it is the same "
                "skill at two scales — reading a wide pattern and arriving on time.",
        "how": ["jump (4-7 r) plus bigjump (> 7 r) share of objects"],
        "doc": "../library.md",
    },
    {
        "id": "sharp-reversals",
        "group": "profile",
        "term": "sharp reversals",
        "short": "share of objects where the movement turns back on itself (>= 135 deg)",
        "long": "The turn angle between the incoming and outgoing cursor leg. A "
                "reversal means the cursor must stop and go back — a different "
                "motion from a flow pattern that keeps turning the same way. Maps "
                "full of them fail differently from maps full of smooth curves.",
        "how": ["angle measured at each object, using slider tails as ends",
                ">= 135 degrees counts as a reversal"],
        "doc": "../library.md",
    },
    {
        "id": "slider-density",
        "group": "profile",
        "term": "slider density",
        "short": "share of objects that are sliders",
        "long": "Sliders ask for a path, not a point: the cursor must be at the "
                "tail when the body ends. A map built of them trains flow aim and "
                "reading; a map of circles trains pure jumps. Both are swimming, "
                "just different strokes.",
        "how": ["sliders / objects, straight from the .osu"],
        "doc": "../library.md",
    },
    {
        "id": "comfort-sr",
        "group": "recommend",
        "term": "comfort SR",
        "short": "the median star rating of your recent plays",
        "long": "Your own level, measured rather than guessed: the median star "
                "rating over the profile window (90 days, or the whole corpus if "
                "that is thin). Every candidate has to sit within one star of it, "
                "which is why the page never suggests a 4-star map to a 7-star "
                "player or the reverse.",
        "how": ["median of the played maps' star ratings in the window",
                "candidates are gated to comfort +/- 1.0 star"],
        "doc": "../recommend.md",
    },
    {
        "id": "stretch",
        "group": "recommend",
        "term": "stretch",
        "short": "how far above your comfort SR to aim (0 = comfort, 1 = a step up)",
        "long": "The difficulty fit is a smooth curve that peaks slightly above "
                "your comfort rating: sitting exactly at your level trains nothing. "
                "The setting moves that peak between +0 and +0.6 stars and widens "
                "the tolerance as it goes. There is deliberately no weight slider — "
                "one difficulty knob is enough to explain and to test.",
        "how": ["peak = comfort + 0.6 x stretch, sigma = 0.35 + 0.5 x stretch",
                "the hard band stays +/- 1.0 star"],
        "doc": "../recommend.md",
    },
    {
        "id": "candidate-gates",
        "group": "recommend",
        "term": "candidate gates",
        "short": "std only, 0:40-4:30, >= 120 objects, within a star of comfort",
        "long": "What a map must clear before it can be suggested at all: osu! "
                "standard charts only, a drain length between 40 seconds and 4:30, "
                "at least 120 objects, a star rating (a map without one cannot be "
                "ranked), inside the comfort band, and not blacklisted. One "
                "difficulty per beatmapset per list, so a set cannot take every "
                "slot.",
        "how": ["short maps and mania are excluded, not down-weighted",
                "the page prints how many maps each gate removed"],
        "doc": "../recommend.md",
    },
    {
        "id": "new-bucket",
        "group": "recommend",
        "term": "new",
        "short": "a map you have never played",
        "long": "Never played by this player — not merely never analysed. A map "
                "you played only in Relax is not 'new': it is counted separately, "
                "because the claim would be false.",
        "how": ["checked against every run for the player, Relax included"],
        "doc": "../recommend.md",
    },
    {
        "id": "improver",
        "group": "recommend",
        "term": "improver",
        "short": "a map you played, did worse on than your level, and can beat",
        "long": "At least two attempts, and the latest one is 3 accuracy points "
                "below the median of your runs in the same star band (or the play "
                "failed). The card carries the proof: your best on this map, that "
                "band median, and the last attempt. The point is that you have "
                "already shown you can do better here.",
        "how": ["band median needs 5 runs, on 0.25-star bands",
                "the gap also scales the map's score"],
        "doc": "../recommend.md",
    },
    {
        "id": "maintain",
        "group": "recommend",
        "term": "maintain",
        "short": "a map you are good at and have not touched in 30+ days",
        "long": "At or above your band median, last played at least thirty days "
                "ago. Not new material and not a weakness: a check that the skill "
                "is still there. The thirty days is the same number the dashboard "
                "window uses, so 'stale' and 'this month' cannot disagree.",
        "how": ["staler maps score slightly higher, capped at 90 days"],
        "doc": "../recommend.md",
    },
    {
        "id": "blacklist",
        "group": "recommend",
        "term": "blacklist",
        "short": "maps or whole beatmapsets the recommender must never suggest",
        "long": "Written to out/blacklist.json when you press the x on a card, "
                "the map page or the listing. A difficulty or a whole set. "
                "Unblocking is the same button in settings — a list you cannot undo "
                "is a trap.",
        "how": ["set entries match on the candidate's set id, including future imports"],
        "doc": "../recommend.md",
    },
    {
        "id": "library-scan",
        "group": "recommend",
        "term": "library scan",
        "short": "the one-off pass that measures every installed map",
        "long": "Recommendations need to know what maps you own but have not "
                "played, so `osu-critique library scan` parses every .osu on disk "
                "once and stores its features in the derived index. It is not run "
                "on server boot: a cold scan takes a couple of minutes, and a stale "
                "candidate list is better than a frozen page. The dashboard reports "
                "how old the scan is.",
        "how": ["~150 s cold on 5.6k maps, under a second when nothing changed",
                "deleting the index loses it — rescan, the page says so"],
        "doc": "../library.md",
    },
)

BY_ID = {t["id"]: t for t in TERMS}

#: section order on /learn
SECTIONS = tuple(
    (key, label, [t for t in TERMS if t["group"] == key]) for key, label in GROUPS
)


def get(term_id: str) -> dict | None:
    return BY_ID.get(term_id)


def missing(ids) -> list[str]:
    """Ids with no entry — the guard the dashboard test uses."""
    return [i for i in ids if i not in BY_ID]
