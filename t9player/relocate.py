"""Songs that moved: match the ones the library knows (with their play counts) to files in a new place.

The library identifies a song by the path of its file, so after the music was moved to another folder or
drive the old entries point nowhere. find_moves() pairs every missing song with a file in the new place,
most reliable evidence first:

  1. the same folder structure under another root   (D:\\Music\\Album\\01 Song.mp3 -> E:\\Muzyka\\Album\\01 Song.mp3)
  2. the same file name and the same size
  3. the same file name when nothing else in play has it
  4. the same title and artist (and length) read from the tags - covers renamed files and a flattened layout

Every file is used for one song only, and anything not clearly identified is left alone.
"""

import os
import re
import unicodedata
from collections import defaultdict


def _norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _parts(path):
    return [p.casefold() for p in re.split(r"[\\/]+", path) if p]


def _tail(a, b):
    """How many trailing path components two paths share (the file name counts)."""
    n = 0
    for x, y in zip(reversed(a), reversed(b)):
        if x != y:
            break
        n += 1
    return n


def _name(path):
    return re.split(r"[\\/]+", path)[-1].casefold()


def _unique_best(scored):
    """[(score, item)] -> item with the single highest score, or None when the top is tied / empty."""
    if not scored:
        return None
    top = max(s for s, _ in scored)
    best = [i for s, i in scored if s == top]
    return best[0] if len(best) == 1 else None


def find_moves(missing, files, tags_of=None, prefetch=None):
    """missing: [Track]; files: {path: size} of what exists in the new place;
    tags_of(path) -> (title, artist, album, duration) or None; prefetch(paths) warms tags_of in bulk.
    Returns {old path: new path}."""
    moves = {}
    free = dict(files)
    left = list(missing)

    def index():
        idx = defaultdict(list)
        for path in free:
            idx[_name(path)].append(path)
        return idx

    def take(m, new):
        moves[m.path] = new
        free.pop(new, None)

    # 1 + 2: file name found; decide by folder structure, then by size
    idx = index()
    for m in list(left):
        cands = idx.get(_name(m.path), [])
        if not cands:
            continue
        mp = _parts(m.path)
        scored = [(_tail(mp, _parts(c)), c) for c in cands if c in free]
        best = _unique_best(scored)
        top = max((s for s, _ in scored), default=0)
        if best is not None and top >= 2:
            take(m, best)
            left.remove(m)
    idx = index()
    for m in list(left):
        cands = [c for c in idx.get(_name(m.path), []) if c in free and m.size and free[c] == m.size]
        if len(cands) == 1:
            take(m, cands[0])
            left.remove(m)
    # 3: file name only, when it is unambiguous on both sides
    idx = index()
    names = defaultdict(int)
    for m in left:
        names[_name(m.path)] += 1
    for m in list(left):
        cands = [c for c in idx.get(_name(m.path), []) if c in free]
        if len(cands) != 1 or names[_name(m.path)] != 1:
            continue
        if tags_of is not None and m.duration:
            tags = tags_of(cands[0])
            if tags and tags[3] and abs(tags[3] - m.duration) > 5:
                continue                        # same name, clearly another recording
        take(m, cands[0])
        left.remove(m)
    # 4: tags
    if left and free and tags_of is not None:
        if prefetch is not None:
            prefetch(list(free))
        by_tags = defaultdict(list)
        for path in free:
            tags = tags_of(path)
            if tags and tags[0]:
                by_tags[(_norm(tags[0]), _norm(tags[1]))].append((path, tags))
        for m in list(left):
            key = (_norm(m.title), _norm(m.artist or m.albumartist))
            scored = []
            for path, tags in by_tags.get(key, []):
                if path not in free:
                    continue
                if m.duration and tags[3] and abs(tags[3] - m.duration) > 2.5:
                    continue
                score = 1 + (2 if m.album and tags[2] and _norm(m.album) == _norm(tags[2]) else 0)
                if m.duration and tags[3]:
                    score += 1 if abs(tags[3] - m.duration) <= 1.0 else 0
                scored.append((score, path))
            best = _unique_best(scored)
            if best is not None:
                take(m, best)
                left.remove(m)
    return moves
