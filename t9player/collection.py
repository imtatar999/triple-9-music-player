"""Albums and artists built from the tracks' tags (no Qt, fast enough for 50k tracks)."""

import re
from collections import Counter

# separators between several artists in one tag
_ARTIST_SPLIT = re.compile(
    r"\s*(?:;|/| feat\.? | ft\.? | featuring | x | & |, | with | w/ )\s*", re.IGNORECASE)
# "(feat. G Herbo)" / "[ft. X & Y]" / "(with Juice WRLD)" inside a title
_TITLE_FEAT = re.compile(r"[(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+([^)\]]+)[)\]]", re.IGNORECASE)


def norm(text):
    return re.sub(r"\s+", " ", (text or "").strip()).casefold()


def split_artists(artist, title=""):
    """['Juice WRLD', 'G Herbo'] from 'Juice WRLD feat. G Herbo' and/or '... (feat. G Herbo)'."""
    names = []
    for part in _ARTIST_SPLIT.split(artist or ""):
        part = part.strip()
        if part:
            names.append(part)
    for group in _TITLE_FEAT.findall(title or ""):
        for part in _ARTIST_SPLIT.split(group):
            part = part.strip()
            if part:
                names.append(part)
    seen = set()
    out = []
    for name in names:
        key = norm(name)
        if key and key not in seen:
            seen.add(key)
            out.append(name)
    return out


def _track_sort(t):
    return (t.disc or 0, t.track or 0, norm(t.title))


class Album:
    __slots__ = ("key", "title", "artist", "year", "tracks", "duration", "plays", "cover_track", "genre")

    def __init__(self, key, tracks):
        self.key = key
        self.tracks = sorted(tracks, key=_track_sort)
        first = self.tracks[0]
        self.title = first.album
        album_artists = Counter((split_artists(t.albumartist) or [""])[0] for t in self.tracks if t.albumartist)
        if album_artists:
            self.artist = album_artists.most_common(1)[0][0]
        else:
            primary = Counter((split_artists(t.artist) or [t.display_artist])[0] for t in self.tracks)
            self.artist = primary.most_common(1)[0][0] if len(primary) <= 2 else "Various artists"
        years = Counter(t.year for t in self.tracks if t.year)
        self.year = years.most_common(1)[0][0] if years else ""
        genres = Counter(t.genre for t in self.tracks if t.genre)
        self.genre = genres.most_common(1)[0][0] if genres else ""
        self.duration = sum(t.duration for t in self.tracks)
        self.plays = sum(t.plays for t in self.tracks)
        # the cover: the first track (in album order) - most tagging tools put the art on all of them
        self.cover_track = first


class Artist:
    __slots__ = ("key", "name", "tracks", "albums", "plays", "duration", "cover_track")

    def __init__(self, key, name, tracks):
        self.key = key
        self.name = name
        self.tracks = sorted(tracks, key=lambda t: (norm(t.album), _track_sort(t)))
        self.albums = []
        self.plays = sum(t.plays for t in tracks)
        self.duration = sum(t.duration for t in tracks)
        # picture: a cover from their most played song (or the first one)
        self.cover_track = max(tracks, key=lambda t: (t.plays, -self.tracks.index(t)))


class Collection:
    """Snapshot of albums and artists for a list of tracks."""

    def __init__(self, tracks):
        by_album = {}
        for t in tracks:
            if not t.album:
                continue
            # group by the main album artist: "Juice WRLD, Lil Yachty" is still a Juice WRLD album
            key = (norm((split_artists(t.albumartist) or [""])[0]), norm(t.album))
            by_album.setdefault(key, []).append(t)
        # an album tagged with album artist on some tracks only: merge into one
        merged = {}
        for (aa, name), items in by_album.items():
            if not aa:
                partner = next((k for k in by_album if k[1] == name and k[0]), None)
                if partner is not None:
                    merged.setdefault(partner, []).extend(items)
                    continue
            merged.setdefault((aa, name), []).extend(items)
        self.albums = {}
        for key, items in merged.items():
            akey = "␟".join(key)
            self.albums[akey] = Album(akey, items)

        by_artist = {}
        names = {}
        for t in tracks:
            for name in split_artists(t.artist or t.albumartist, t.title) or ["Unknown artist"]:
                k = norm(name)
                by_artist.setdefault(k, []).append(t)
                names.setdefault(k, Counter())[name] += 1
        self.artists = {}
        for k, items in by_artist.items():
            name = names[k].most_common(1)[0][0]
            self.artists[k] = Artist(k, name, items)
        for album in self.albums.values():
            k = norm(album.artist)
            if k in self.artists:
                self.artists[k].albums.append(album)
        for artist in self.artists.values():
            artist.albums.sort(key=lambda a: (a.year or "9999", norm(a.title)))

    def albums_sorted(self, by="title"):
        items = list(self.albums.values())
        if by == "year":
            items.sort(key=lambda a: (a.year or "0000", norm(a.title)), reverse=True)
        elif by == "artist":
            items.sort(key=lambda a: (norm(a.artist), norm(a.title)))
        elif by == "plays":
            items.sort(key=lambda a: (-a.plays, norm(a.title)))
        else:
            items.sort(key=lambda a: norm(a.title))
        return items

    def artists_sorted(self, by="name"):
        items = list(self.artists.values())
        if by == "songs":
            items.sort(key=lambda a: (-len(a.tracks), norm(a.name)))
        elif by == "plays":
            items.sort(key=lambda a: (-a.plays, norm(a.name)))
        else:
            items.sort(key=lambda a: norm(a.name))
        return items

    def album_of(self, track):
        if not track.album:
            return None
        aa = norm((split_artists(track.albumartist) or [""])[0])
        key = "␟".join((aa, norm(track.album)))
        if key in self.albums:
            return self.albums[key]
        name = norm(track.album)
        return next((a for a in self.albums.values() if norm(a.title) == name), None)

    def artist_named(self, name):
        return self.artists.get(norm(name))
