# This file includes the package version info


def _version_as_tuple(version_str):
    return tuple(int(i) for i in version_str.split(".") if i.isdigit())


__version__ = "0.5.5"

__version_info__: tuple[int, ...] = _version_as_tuple(__version__)
