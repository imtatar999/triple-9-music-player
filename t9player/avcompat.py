"""PyAV differences between versions (the Windows and Mac builds may use different ones)."""


def open_av(path):
    """av.open() that ignores broken tag text; newer PyAV (19+) dropped the metadata_errors option."""
    import av
    try:
        return av.open(path, metadata_errors="ignore")
    except TypeError:
        return av.open(path)
