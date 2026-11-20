"""PicSpec: write down how your images should look, once, for any image model."""

from .judge import Report, Verdict, check_image
from .loop import Attempt, Outcome, generate_checked
from .request import Directive, Reference, Request, bare_request, build_request
from .spec import Category, Problem, Ref, Rule, Spec, SpecError, dumps, find, load, loads

__version__ = "0.4.0"

__all__ = [
    "Attempt", "Category", "Directive", "Outcome", "Problem", "Ref", "Reference", "Report", "Request", "Rule", "Spec", "SpecError", "Verdict",
    "bare_request", "build_request", "check_image", "dumps", "find", "generate_checked", "load", "loads", "__version__",
]
