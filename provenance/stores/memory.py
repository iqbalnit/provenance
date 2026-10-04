"""In-memory stand-ins for the Firestore and GCS client surfaces we use.

Used by tests and by the offline demo mode (no GCP credentials needed). They
implement only the calls provenance/stores/firestore.py and provenance/data/ofac.py make.
"""
from __future__ import annotations

import copy
from pathlib import Path


class AlreadyExists(Exception):
    pass


class _Snap:
    def __init__(self, data):
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return copy.deepcopy(self._data)


class _Doc:
    def __init__(self, store, path):
        self._store, self._path = store, path

    def collection(self, name):
        return _Col(self._store, f"{self._path}/{name}")

    def create(self, data):
        if self._path in self._store:
            raise AlreadyExists(self._path)
        self._store[self._path] = copy.deepcopy(data)

    def set(self, data, merge=False):
        if merge and self._path in self._store:
            self._store[self._path].update(copy.deepcopy(data))
        else:
            self._store[self._path] = copy.deepcopy(data)

    def get(self):
        return _Snap(self._store.get(self._path))


class _Col:
    def __init__(self, store, path):
        self._store, self._path = store, path

    def document(self, doc_id):
        return _Doc(self._store, f"{self._path}/{doc_id}")

    def stream(self):
        prefix = self._path + "/"
        for k, v in sorted(self._store.items()):
            if k.startswith(prefix) and "/" not in k[len(prefix):]:
                yield _Snap(v)


class FakeFirestore:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def collection(self, name):
        return _Col(self.store, name)


class _Blob:
    def __init__(self, files, name):
        self._files, self.name = files, name
        self.metadata = files.get(name, {}).get("metadata")

    def upload_from_filename(self, path, content_type=None):
        self._files[self.name] = {"data": Path(path).read_bytes(), "metadata": self.metadata}

    def download_to_filename(self, path):
        Path(path).write_bytes(self._files[self.name]["data"])


class _Bucket:
    def __init__(self, files):
        self._files = files

    def blob(self, name):
        return _Blob(self._files, name)

    def get_blob(self, name):
        return _Blob(self._files, name) if name in self._files else None


class FakeGCS:
    def __init__(self):
        self.buckets: dict[str, dict] = {}

    def bucket(self, name):
        return _Bucket(self.buckets.setdefault(name, {}))
