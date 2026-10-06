import re

from server.parse.clean import normalize_for_match

HONORIFICS = r"\b(mr|mrs|ms|miss|dr|shri|smt|sri|kum|prof|capt|col|justice|ca|cs)\b\.?"
COMPANY_SUFFIX = (
    r"\b(limited|ltd|private|pvt|llp|inc|incorporated|co|company|corporation|corp)\b\.?"
)


def norm_person(name: str) -> str:
    s = normalize_for_match(name)
    s = re.sub(HONORIFICS, " ", s)
    s = re.sub(r"[^a-z\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_company(name: str) -> str:
    s = normalize_for_match(name)
    s = s.replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)  # remove bracketed former names
    s = re.sub(COMPANY_SUFFIX, " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def surname_key(norm: str) -> str:
    parts = norm.split()
    return parts[-1] if parts else ""


def initials_signature(norm: str) -> str:
    # "a k sharma" and "anil kumar sharma" → "aks"
    return "".join(p[0] for p in norm.split() if p)
