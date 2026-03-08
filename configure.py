import collections
import ipaddress
import json
import logging
import time
from typing import Annotated
from typing import Any
from typing import cast
from typing import override
from typing import TYPE_CHECKING

import annotated_types as at
import pandas as pd
import pooch  # pyright: ignore[reportMissingTypeStubs]
import pydantic
import pydantic_settings
import rattler.platform
import rich.logging


def main():
    handler = rich.logging.RichHandler()
    logging.basicConfig(handlers=[handler])
    handler.setFormatter(None)
    pooch.utils.LOGGER = logger = logging.getLogger('pooch')
    logger.setLevel(logging.INFO)
    logging.captureWarnings(True)

    github = _GithubMeta()
    obj = _Data().model_dump()
    obj['github'] = {'git': _weighted(github.git), 'web': _weighted(github.web)}
    with open('build/tmp/data.json', 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))


class _GithubMeta(pydantic_settings.BaseSettings):
    git: list[pydantic.IPvAnyNetwork]
    web: list[pydantic.IPvAnyNetwork]

    model_config = pydantic_settings.SettingsConfigDict(extra='ignore')

    if TYPE_CHECKING:
        def __init__(self): ...

    @override
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pydantic_settings.BaseSettings],
        init_settings: pydantic_settings.PydanticBaseSettingsSource,
        env_settings: pydantic_settings.PydanticBaseSettingsSource,
        dotenv_settings: pydantic_settings.PydanticBaseSettingsSource,
        file_secret_settings: pydantic_settings.PydanticBaseSettingsSource,
    ):
        headers = {'X-GitHub-Api-Version': '2022-11-28'}
        json_file = pooch.retrieve(  # pyright: ignore[reportUnknownMemberType]
            'https://api.github.com/meta',
            known_hash=None,
            path=pooch.os_cache('pooch') / time.strftime('%Y.%m'),
            downloader=pooch.HTTPDownloader(headers=headers),  # pyright: ignore[reportArgumentType]
        )
        return (
            pydantic_settings.JsonConfigSettingsSource(settings_cls, json_file),
        )


def _weighted(networks: list[pydantic.IPvAnyNetwork]):
    v4 = [net for net in networks if isinstance(net, ipaddress.IPv4Network)]
    n = max([net.num_addresses for net in v4])
    return dict(collections.ChainMap(*[
        dict.fromkeys(map(str, net.hosts()), n // net.num_addresses)
        for net in v4
    ]))


class _Listen(pydantic.BaseModel):
    port: Annotated[pydantic.NonNegativeInt, at.Le(65535)]


class _ServerSettings(pydantic.BaseModel):
    root: str
    proxy_store: str


class _CondaSettings(_Listen):
    channels: list[str]
    mirrors: list[str]
    mirrors_with_zst: list[str]
    intel: _Listen
    platforms: list[rattler.platform.PlatformLiteral] = list(
        rattler.platform.PlatformLiteral.__args__)


class _HTTPSettings(pydantic.BaseModel):
    server: _ServerSettings


class _MIMETypes(pydantic.BaseModel):
    types: dict[str, str]


class _Data(pydantic_settings.BaseSettings):
    conda: _CondaSettings
    http: _HTTPSettings
    mime: _MIMETypes

    if TYPE_CHECKING:
        def __init__(self): ...

    @override
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pydantic_settings.BaseSettings],
        init_settings: pydantic_settings.PydanticBaseSettingsSource,
        env_settings: pydantic_settings.PydanticBaseSettingsSource,
        dotenv_settings: pydantic_settings.PydanticBaseSettingsSource,
        file_secret_settings: pydantic_settings.PydanticBaseSettingsSource,
    ):
        headers = {
            'Accept': 'application/vnd.github.raw+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        csv_file = pooch.retrieve(  # pyright: ignore[reportUnknownMemberType]
            'https://api.github.com/repos/mime-types/mime-types-data/contents/data/ext_mime.db',
            known_hash=None,
            path=pooch.os_cache('pooch') / time.strftime('%Y.%m'),
            downloader=pooch.HTTPDownloader(headers=headers),  # pyright: ignore[reportArgumentType]
        )
        series = cast(
            'pd.Series[Any]',
            pd.read_csv(csv_file, sep=r'\s+', header=None, usecols=[0, 1])
              .groupby(1)
              .agg(' '.join)
              .squeeze()
        )
        init_kwargs = {'mime': {'types': series.to_dict()}}
        return (
            pydantic_settings.PyprojectTomlConfigSettingsSource(settings_cls),
            pydantic_settings.InitSettingsSource(settings_cls, init_kwargs),
        )


if __name__ == '__main__':
    main()
