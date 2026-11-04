"""Import-safety shim for h5py (used only by PFLOTRAN H5 helpers in pydfnworks).

The mesh-generation / meshing / UGE-conversion workflow does not touch HDF5.
Install the real h5py wheel to use PFLOTRAN H5 input/output features.
"""


def File(*args, **kwargs):  # noqa: N802
    raise NotImplementedError(
        "h5py is not installed (lightweight shim active). Install h5py to "
        "use pydfnworks PFLOTRAN HDF5 features (dump_h5_files / parse_pflotran_h5)."
    )


class Group:  # pragma: no cover - placeholder
    pass
