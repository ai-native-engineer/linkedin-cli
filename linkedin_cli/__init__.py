"""linkedin-cli package."""

from importlib.metadata import PackageNotFoundError, version

from .api import LinkedInWriteAPI
from .api import DeletePlan
from .api import PostPlan


try:
    __version__ = version("linkedin-cli")
except PackageNotFoundError:
    __version__ = "0.1.0"


__all__ = ["DeletePlan", "LinkedInWriteAPI", "PostPlan", "__version__"]
