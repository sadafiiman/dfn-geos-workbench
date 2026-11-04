"""Minimal pandas compatibility shim (only what pydfnworks uses at import/run time).

pydfnworks uses pandas in ``process_generator_output.py`` for a couple of
small DataFrame operations (P21 computation).  This shim implements exactly
those operations so the full pandas wheel is not required for
generation + meshing workflows.  Install real pandas when available;
this shim is only used when pandas is missing from the environment.
"""

__version__ = "0.0.1-shim"


class Series(list):
    """Tiny list wrapper with the boolean-mask / reduction ops pydfnworks uses."""

    def __eq__(self, other):  # noqa: D105
        return Series([v == other for v in self])

    def __ne__(self, other):  # noqa: D105
        return Series([v != other for v in self])

    def __gt__(self, other):  # noqa: D105
        return Series([v > other for v in self])

    def __ge__(self, other):  # noqa: D105
        return Series([v >= other for v in self])

    def __lt__(self, other):  # noqa: D105
        return Series([v < other for v in self])

    def __le__(self, other):  # noqa: D105
        return Series([v <= other for v in self])

    def __and__(self, other):  # noqa: D105
        return Series([bool(a) and bool(b) for a, b in zip(self, other)])

    def __or__(self, other):  # noqa: D105
        return Series([bool(a) or bool(b) for a, b in zip(self, other)])

    def sum(self):  # noqa: D102
        return sum(v for v in self if v is not None)

    def tolist(self):  # noqa: D102
        return list(self)


class DataFrame:
    """Column store supporting the handful of operations pydfnworks needs."""

    def __init__(self, data=None, columns=None):
        self._cols = {}
        if isinstance(data, dict):
            keys = list(data.keys())
            for k in keys:
                self._cols[k] = list(data[k])
            self._columns = list(columns or keys)
        else:
            data = [] if data is None else data
            try:
                data = list(data)
            except TypeError:  # scalar
                data = [data]
            self._columns = list(columns or [])
            for name in self._columns:
                self._cols.setdefault(name, [])
            for row in data:
                for name, value in zip(self._columns, row):
                    self._cols.setdefault(name, []).append(value)
        self._nrows = len(next(iter(self._cols.values()))) if self._cols else 0

    @property
    def columns(self):  # noqa: D102
        return list(self._columns)

    def __len__(self):  # noqa: D105
        return self._nrows

    def __getitem__(self, name):
        if isinstance(name, list):  # multi-column projection
            return DataFrame({k: self._cols[k] for k in name})
        return Series(self._cols[name])

    def _rows(self, mask):
        if isinstance(mask, Series):
            mask = list(mask)
        return [i for i, flag in enumerate(mask) if bool(flag)]

    def _loc_get(self, mask, column):
        rows = self._rows(mask)
        if column is None or column == slice(None):
            return DataFrame({k: [v[i] for i in rows] for k, v in self._cols.items()})
        return Series([self._cols[column][i] for i in rows])

    class _Loc:
        def __init__(self, df):
            self._df = df

        def __getitem__(self, key):
            mask, column = key
            return self._df._loc_get(mask, column)

    @property
    def loc(self):  # noqa: D102
        return DataFrame._Loc(self)


def read_csv(path, *args, **kwargs):  # pragma: no cover - not used by pydfnworks core
    raise NotImplementedError(
        "pandas.read_csv is not available in the lightweight shim. "
        "Install the real pandas package for this feature."
    )
