"""
Minimal in-memory stand-in for the Motor collections used by the ledger code.

Supports just what the balance/transaction paths use: equality, $gte/$lt/$ne/
$in/$nin/$or on (dotted) fields; $set/$unset updates; and the pipeline
balance update ($round/$add/$ifNull). Every awaited call yields to the event
loop first, so asyncio.gather() interleaves operations like a real server would.
"""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace

from bson import ObjectId

_MISSING = object()


def _get(doc, dotted):
    cur = doc
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _match_value(value, cond):
    # Array fields match element-wise, like MongoDB multikey queries.
    if isinstance(value, list) and not (isinstance(cond, dict) and "$exists" in cond):
        if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
            if set(cond) <= {"$in"}:
                return any(v in cond["$in"] for v in value)
            if set(cond) <= {"$nin"}:
                return not any(v in cond["$nin"] for v in value)
        elif not isinstance(cond, list):
            return cond in value
    if isinstance(cond, dict) and cond and all(k.startswith("$") for k in cond):
        for op, arg in cond.items():
            present = value is not _MISSING
            v = value if present else None
            comparable = present and v is not None
            if op == "$gte":
                ok = comparable and v >= arg
            elif op == "$gt":
                ok = comparable and v > arg
            elif op == "$lte":
                ok = comparable and v <= arg
            elif op == "$lt":
                ok = comparable and v < arg
            elif op == "$ne":
                ok = v != arg
            elif op == "$in":
                ok = v in arg
            elif op == "$nin":
                ok = v not in arg
            elif op == "$exists":
                ok = present == bool(arg)
            else:
                raise NotImplementedError(f"fake_mongo: unsupported query operator {op}")
            if not ok:
                return False
        return True
    if value is _MISSING:
        return cond is None
    return value == cond


def matches(doc, query):
    for key, cond in query.items():
        if key == "$or":
            if not any(matches(doc, sub) for sub in cond):
                return False
        elif key == "$and":
            if not all(matches(doc, sub) for sub in cond):
                return False
        elif not _match_value(_get(doc, key), cond):
            return False
    return True


def _eval(expr, doc):
    if isinstance(expr, str) and expr.startswith("$"):
        v = _get(doc, expr[1:])
        return None if v is _MISSING else v
    if isinstance(expr, dict):
        (op, args), = expr.items()
        vals = [_eval(a, doc) for a in args]
        if op == "$add":
            return sum(vals)
        if op == "$ifNull":
            return vals[0] if vals[0] is not None else vals[1]
        if op == "$round":
            return round(vals[0], vals[1])
        raise NotImplementedError(op)
    return expr


def _set_path(doc, dotted, value):
    parts = dotted.split(".")
    for part in parts[:-1]:
        doc = doc.setdefault(part, {})
    doc[parts[-1]] = value


def apply_update(doc, update):
    if isinstance(update, list):
        for stage in update:
            (op, fields), = stage.items()
            assert op == "$set", op
            computed = {k: _eval(v, doc) for k, v in fields.items()}
            for k, v in computed.items():
                _set_path(doc, k, v)
        return
    for op, fields in update.items():
        for k, v in fields.items():
            if op == "$set":
                _set_path(doc, k, v)
            elif op == "$unset":
                doc.pop(k, None)
            elif op == "$pull":
                current = _get(doc, k)
                if isinstance(current, list):
                    if isinstance(v, dict) and "$in" in v:
                        _set_path(doc, k, [x for x in current if x not in v["$in"]])
                    else:
                        _set_path(doc, k, [x for x in current if x != v])
            elif op == "$inc":
                _set_path(doc, k, (_get(doc, k) if _get(doc, k) is not _MISSING else 0) + v)
            else:
                raise NotImplementedError(op)


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        self._docs = sorted(self._docs, key=lambda d: (d.get(key) is None, d.get(key)), reverse=direction == -1)
        return self

    def limit(self, n):
        if n:
            self._docs = self._docs[:n]
        return self

    def skip(self, n):
        self._docs = self._docs[n:]
        return self

    async def to_list(self, length=None):
        await asyncio.sleep(0)
        return self._docs[:length] if length else list(self._docs)

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, docs=None):
        self.docs: list[dict] = [copy.deepcopy(d) for d in (docs or [])]

    def _project(self, doc):
        return copy.deepcopy(doc)

    async def find_one(self, query, projection=None, session=None):
        await asyncio.sleep(0)
        for doc in self.docs:
            if matches(doc, query):
                return self._project(doc)
        return None

    def find(self, query=None, projection=None, session=None):
        return _Cursor([self._project(d) for d in self.docs if matches(d, query or {})])

    async def count_documents(self, query, session=None):
        await asyncio.sleep(0)
        return sum(1 for d in self.docs if matches(d, query))

    async def insert_one(self, doc, session=None):
        await asyncio.sleep(0)
        doc.setdefault("_id", ObjectId())
        self.docs.append(copy.deepcopy(doc))
        return SimpleNamespace(inserted_id=doc["_id"])

    async def insert_many(self, docs, ordered=True, session=None):
        await asyncio.sleep(0)
        ids = []
        for doc in docs:
            doc.setdefault("_id", ObjectId())
            self.docs.append(copy.deepcopy(doc))
            ids.append(doc["_id"])
        return SimpleNamespace(inserted_ids=ids)

    async def update_one(self, query, update, upsert=False, session=None):
        await asyncio.sleep(0)
        for doc in self.docs:
            if matches(doc, query):
                apply_update(doc, update)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    async def find_one_and_update(self, query, update, upsert=False, return_document=None, session=None):
        from pymongo import ReturnDocument
        from pymongo.errors import DuplicateKeyError

        await asyncio.sleep(0)
        for doc in self.docs:
            if matches(doc, query):
                before = copy.deepcopy(doc)
                apply_update(doc, update)
                return copy.deepcopy(doc) if return_document == ReturnDocument.AFTER else before
        if not upsert:
            return None
        new_doc = {k: v for k, v in query.items() if not k.startswith("$") and not isinstance(v, dict)}
        if "_id" in new_doc and any(d.get("_id") == new_doc["_id"] for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key")
        apply_update(new_doc, update)
        new_doc.setdefault("_id", ObjectId())
        self.docs.append(new_doc)
        return copy.deepcopy(new_doc) if return_document == ReturnDocument.AFTER else None

    async def update_many(self, query, update, session=None):
        await asyncio.sleep(0)
        hit = [d for d in self.docs if matches(d, query)]
        for doc in hit:
            apply_update(doc, update)
        return SimpleNamespace(matched_count=len(hit), modified_count=len(hit))

    async def delete_many(self, query, session=None):
        await asyncio.sleep(0)
        before = len(self.docs)
        self.docs = [d for d in self.docs if not matches(d, query)]
        return SimpleNamespace(deleted_count=before - len(self.docs))


class FakeDb:
    def __init__(self, **collections):
        self._cols = {name: FakeCollection(docs) for name, docs in collections.items()}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._cols.setdefault(name, FakeCollection())

    def __getitem__(self, name):
        return getattr(self, name)
