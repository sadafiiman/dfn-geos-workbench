"""Import-safety shim for mplstereonet (only used by the pydfnworks PDF report).

The stereonet plots are optional eye-candy in the generation report.  This
shim lets ``import mplstereonet`` succeed; calling real stereonet plotting
functions raises a clear error.  Install mplstereonet for full reports.
"""


def __getattr__(name):  # noqa: D105
    raise AttributeError(
        f"mplstereonet shim does not implement '{name}'. "
        "Install the real mplstereonet package for stereonet report figures."
    )
