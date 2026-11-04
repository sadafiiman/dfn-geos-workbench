"""Import-safety shim for seaborn (only used by the pydfnworks PDF report).

Implements ``kdeplot`` with scipy's Gaussian KDE so the report still works;
everything else degrades gracefully to matplotlib.
"""

import matplotlib.pyplot as plt  # noqa: F401
import numpy as np

try:
    from scipy.stats import gaussian_kde
except Exception:  # pragma: no cover
    gaussian_kde = None


def kdeplot(data, color="k", **kwargs):  # noqa: ARG001
    data = np.asarray(data, dtype=float)
    if gaussian_kde is None or data.size == 0:
        return plt.hist(data, bins=30, color=color, alpha=0.5)
    kde = gaussian_kde(data)
    xs = np.linspace(data.min(), data.max(), 200)
    return plt.plot(xs, kde(xs), color=color)


def histplot(data, **kwargs):  # noqa: ARG001
    return plt.hist(np.asarray(data).ravel(), bins=30, alpha=0.6)


def set_theme(**kwargs):  # noqa: ARG001
    pass
