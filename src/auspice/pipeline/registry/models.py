"""The shape of the registry file.

Pydantic models rather than free form YAML, for the same reason extraction uses a strict
schema: a registry with a typo in a FIPS code produces a spatial join that silently returns
nothing, and that failure looks exactly like "this county has no decisions".

Every field that is an assertion rather than an observation carries a ``source``. The
validator refuses a jurisdiction whose ``legal_framework`` has no source, because Dillon's
Rule versus home rule is a first order variable in the model and an unsourced claim about it
is not usable.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Any, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from auspice.domain import (
    BodyKind,
    CivicPlatform,
    DocumentKind,
    JurisdictionKind,
    LegalFramework,
    UseClass,
)

Slug = Annotated[str, Field(pattern=r"^[a-z]{2}-[a-z]{2}-[a-z0-9-]+$", min_length=8, max_length=64)]
Fips = Annotated[str, Field(pattern=r"^\d{2,10}$")]


class Cited(BaseModel):
    """A value together with where it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: str
    source: HttpUrl
    retrieved_on: date
    note: str | None = None


class ElectionRule(BaseModel):
    """How to derive this body's election calendar. See registry/elections.py."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    term_years: int = Field(ge=1, le=8)
    anchor_year: int = Field(ge=1900, le=2100, description="A year a general election is known to have been held")
    stagger_offset_years: int | None = Field(default=None, ge=1, le=7)
    explicit_dates: list[date] = Field(default_factory=list)
    source: HttpUrl
    retrieved_on: date

    @model_validator(mode="after")
    def _stagger_within_term(self) -> Self:
        if self.stagger_offset_years is not None and self.stagger_offset_years >= self.term_years:
            raise ValueError("stagger_offset_years must be smaller than term_years")
        return self


class BodySpec(BaseModel):
    """A body that can say no."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=3, max_length=200)
    kind: BodyKind
    seats: int = Field(ge=1, le=101)
    quorum: int | None = Field(default=None, ge=1)
    vote_threshold: str = Field(default="simple_majority")
    recommendation_is_binding: bool | None = None
    meeting_cadence: str | None = None
    statutory_decision_days: int | None = Field(default=None, ge=0, le=3650)
    election_rule: ElectionRule | None = None
    source: HttpUrl
    retrieved_on: date

    @field_validator("vote_threshold")
    @classmethod
    def _known_threshold(cls, value: str) -> str:
        allowed = {
            "simple_majority",
            "supermajority_two_thirds",
            "supermajority_three_quarters",
            "unanimity",
        }
        if value not in allowed:
            raise ValueError(f"vote_threshold must be one of {sorted(allowed)}")
        return value

    @model_validator(mode="after")
    def _quorum_fits(self) -> Self:
        if self.quorum is not None and self.quorum > self.seats:
            raise ValueError(f"quorum {self.quorum} exceeds seats {self.seats}")
        return self


class SourceSpec(BaseModel):
    """Where a class of document for this jurisdiction is published."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: DocumentKind
    platform: CivicPlatform
    url: HttpUrl
    refresh_hours: int = Field(default=24, ge=1, le=8760)
    platform_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class JurisdictionSpec(BaseModel):
    """One row of the registry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: Slug
    name: str = Field(min_length=3, max_length=200)
    kind: JurisdictionKind
    country: str = Field(default="US", pattern=r"^[A-Z]{2}$")
    region: str = Field(min_length=2, max_length=8, description="State or province code")
    fips: Fips | None = None
    admin_codes: dict[str, str] = Field(default_factory=dict)

    legal_framework: LegalFramework
    legal_framework_source: Cited

    civic_platform: CivicPlatform = CivicPlatform.unknown
    civic_platform_source: Cited | None = None

    target_use_classes: list[UseClass] = Field(min_length=1)
    why_in_scope: str = Field(
        min_length=20,
        description="One sentence on why this jurisdiction is in the beachhead. "
        "Forces the 40 counties to be a decision rather than a list.",
    )

    bodies: list[BodySpec] = Field(min_length=1)
    sources: list[SourceSpec] = Field(default_factory=list)

    notes: str | None = None

    @model_validator(mode="after")
    def _fips_matches_country(self) -> Self:
        if self.country == "US" and self.fips is None:
            raise ValueError("US jurisdictions must carry a FIPS code: the boundary fetch keys on it")
        return self

    @model_validator(mode="after")
    def _platform_has_source(self) -> Self:
        if self.civic_platform is not CivicPlatform.unknown and self.civic_platform_source is None:
            raise ValueError(
                f"{self.slug}: civic_platform is {self.civic_platform} but no source is given. "
                "Run `auspice registry probe` to detect it from the live site, or set it back "
                "to unknown."
            )
        return self

    @model_validator(mode="after")
    def _exactly_one_primary_decider(self) -> Self:
        deciders = [b for b in self.bodies if b.recommendation_is_binding is not True]
        if not deciders:
            raise ValueError(
                f"{self.slug}: every body is advisory, so nobody decides. At least one body must "
                "have recommendation_is_binding of false or null."
            )
        return self

    @property
    def boundary_geoid(self) -> str:
        """The GEOID the Census TIGERweb service keys county boundaries on."""
        if self.fips is None:
            raise ValueError(f"{self.slug} has no FIPS code")
        return self.fips


class Registry(BaseModel):
    """The whole file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    beachhead: str
    compiled_on: date
    compiled_by: str
    jurisdictions: list[JurisdictionSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _slugs_unique(self) -> Self:
        seen: set[str] = set()
        for j in self.jurisdictions:
            if j.slug in seen:
                raise ValueError(f"duplicate slug: {j.slug}")
            seen.add(j.slug)
        return self

    @model_validator(mode="after")
    def _fips_unique(self) -> Self:
        seen: set[str] = set()
        for j in self.jurisdictions:
            if j.fips is None:
                continue
            key = f"{j.country}:{j.fips}"
            if key in seen:
                raise ValueError(f"duplicate FIPS code: {key}")
            seen.add(key)
        return self

    def by_slug(self, slug: str) -> JurisdictionSpec:
        for j in self.jurisdictions:
            if j.slug == slug:
                return j
        raise KeyError(slug)


DEFAULT_REGISTRY_FILE = "jurisdictions.yaml"


def load_registry(path: Path | None = None) -> Registry:
    """Read and validate the registry file.

    Raises ``pydantic.ValidationError`` with every problem at once rather than the first one,
    which matters when hand editing 12 entries.
    """
    from auspice.config import get_settings

    resolved = path or (get_settings().registry_path / DEFAULT_REGISTRY_FILE)
    if not resolved.exists():
        raise FileNotFoundError(f"registry file not found: {resolved}")

    raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return Registry.model_validate(raw)
