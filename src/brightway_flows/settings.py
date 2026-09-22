"""What a curator configures about this installation, and nothing a build decides.

Two things live here today.  An API key, which is a secret and so belongs to
the machine rather than the repository.  And which vendor releases the
unit-process score comparison assesses, which is a choice about *this*
installation -- the releases a brightway project has been built for, and where
the expensive artifacts that come out of it are kept -- and not a rule about
the flow list.  A rule about the list is a curated file in ``data/``; a fact
about the machine is a setting.

Sources, in the order they win: an explicit argument, the environment, the
persisted ``settings.json`` in the data directory.  Nested settings are spelled
with a double underscore in the environment -- ``SCORE_COMPARISON__SAMPLE_SIZE``
-- because the prefix is empty and pydantic-settings needs a delimiter that no
field name contains.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import orjson
from pydantic import AliasChoices, BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    JsonConfigSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from brightway_flows.filesystem import APP_SETTINGS_FILEPATH, UNIT_PROCESS_SCORES_DIR


class AssessedRelease(BaseModel):
    """One vendor release whose unit processes are scored two ways.

    ``list_name`` and ``list_version`` are the source list's identity as the
    merge records it in ``elementary_flow_sources`` -- ``ecoinvent`` and ``3.8``
    -- and are how the comparison finds which consensus flow each vendor flow
    reached.  The brightway names are what the exporter opens.
    ``method_family`` is the vendor's own method as brightway namespaces it,
    and is whatever the release *ships*: ecoinvent 3.8 ships ``EF v3.0`` and
    3.12 ships ``EF v3.1``, and the comparison labels the gap rather than
    pretending 3.8 was scored with a method it never carried.
    """

    list_name: str
    list_version: str
    system_model: str
    brightway_project: str
    brightway_database: str
    method_family: str
    #: The artifact's file name under ``artifact_dir``.
    artifact: str
    #: brightway activity codes scored whatever the sample says.  On the
    #: release rather than beside the sample, because a code is brightway's
    #: hash of one import: the same activity has another code in 3.12.
    reference_activities: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        """``ecoinvent-3.8-apos``: what the tables and the pages call it."""
        return f"{self.list_name}-{self.list_version}-{self.system_model}"


#: The activity the comparison was diagnosed on -- `electricity
#: production, wind, >3MW turbine, onshore` in Sweden, as brightway codes it in
#: an import of ecoinvent 3.8 -- which the seeded sample of 500 did not happen
#: to draw.  Its EF v3.0 numbers are quoted in that issue, so an export that
#: carries it can be checked against them.
WIND_SE_3_8 = "b09e51ef9d976bc64905c74fd99842fc"


def _default_releases() -> list[AssessedRelease]:
    return [
        AssessedRelease(
            list_name="ecoinvent",
            list_version="3.8",
            system_model="apos",
            brightway_project="ecoinvent-3.8-apos",
            brightway_database="ecoinvent-3.8-apos",
            method_family="EF v3.0",
            artifact="unit-process-scores-ecoinvent-3.8-apos.json",
            reference_activities=[WIND_SE_3_8],
        ),
        AssessedRelease(
            list_name="ecoinvent",
            list_version="3.12",
            system_model="cutoff",
            brightway_project="ecoinvent-3.12-cutoff",
            brightway_database="ecoinvent-3.12-cutoff",
            method_family="EF v3.1",
            artifact="unit-process-scores-ecoinvent-3.12-cutoff.json",
        ),
    ]


class ScoreComparisonSettings(BaseModel):
    """Which releases the score comparison reads, and from where.

    The sample is seeded so that the same seed over the same release names the
    same unit processes, and an artifact regenerated after a brightway upgrade
    can be diffed against the one before it.  A release's
    ``reference_activities`` are included whatever the sample says.
    """

    artifact_dir: Path = UNIT_PROCESS_SCORES_DIR
    sample_size: int = Field(default=500, gt=0)
    sample_seed: int = 79
    releases: list[AssessedRelease] = Field(default_factory=_default_releases)

    def artifact_path(self, release: AssessedRelease) -> Path:
        return self.artifact_dir / release.artifact

    def release(self, key: str) -> AssessedRelease:
        """The configured release called *key*.

        :raises KeyError: naming the keys that are configured, so a typo on
            the command line reads as one rather than as an empty run.
        """
        for release in self.releases:
            if release.key == key:
                return release
        raise KeyError(
            f"{key!r} is not a configured release; "
            f"configured: {', '.join(r.key for r in self.releases) or 'none'}"
        )


class AppSettings(BaseSettings):
    commonchemistry_api_key: SecretStr | None = Field(
        default=None,
        # Accept persisted JSON field name and env-var style key.
        validation_alias=AliasChoices("commonchemistry_api_key", "COMMONCHEMISTRY_API_KEY"),
    )
    score_comparison: ScoreComparisonSettings = Field(
        default_factory=ScoreComparisonSettings
    )

    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
        extra="ignore",
        json_file=str(APP_SETTINGS_FILEPATH),
        json_file_encoding="utf-8",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Env vars override persisted platformdirs settings.
        return (
            init_settings,
            env_settings,
            JsonConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


@functools.cache
def get_settings() -> AppSettings:
    return AppSettings()


def save_commonchemistry_api_key(token: str) -> None:
    cleaned = token.strip()
    if not cleaned:
        raise ValueError("Token must not be empty.")

    payload: dict[str, Any] = {}
    if APP_SETTINGS_FILEPATH.exists():
        current = orjson.loads(APP_SETTINGS_FILEPATH.read_bytes())
        if isinstance(current, dict):
            payload.update(current)
    payload["commonchemistry_api_key"] = cleaned
    APP_SETTINGS_FILEPATH.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
    get_settings.cache_clear()
