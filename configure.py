import collections
import contextlib
import datetime
import ipaddress
import json
import logging
import os
import platform
import re
import shutil
import sys
import sysconfig
from typing import Annotated
from typing import Any
from typing import BinaryIO
from typing import cast
from typing import NamedTuple
from typing import override
from typing import TYPE_CHECKING
import warnings

import annotated_types as at
import pandas as pd
import platformdirs
import pooch  # pyright: ignore[reportMissingTypeStubs]
import pydantic
import pydantic_settings
import rattler.platform
import requests
import rich.logging
import tqdm.rich


def main():
    handler = rich.logging.RichHandler()
    logging.basicConfig(handlers=[handler])
    handler.setFormatter(None)
    pooch.utils.LOGGER = logger = logging.getLogger('pooch')
    logger.setLevel(logging.INFO)
    logging.captureWarnings(True)

    _fetch_minijinja_cli()
    github = _GithubMeta()
    obj = _Data().model_dump()
    obj['github'] = {'git': _weighted(github.git), 'web': _weighted(github.web)}
    with open('build/tmp/data.json', 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))


def _fetch_minijinja_cli():
    if shutil.which('minijinja-cli'):
        return
    fname = _minijinja_cli_fname()
    headers = {
        'Accept': 'application/octet-stream',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    known_hash = None
    for name, size, url in sorted(_GitHubRelease().assets, reverse=True):
        if name == fname + '.sha256':
            sha256 = pooch.retrieve(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                url,
                known_hash,
                downloader=_Downloader(size=size, headers=headers),
            )
            known_hash = _parse(sha256, fname)  # pyright: ignore[reportUnknownArgumentType]
        elif name == fname:
            dst = os.environ['CONDA_PREFIX']
            if sys.platform == 'win32':
                member = 'minijinja-cli.exe'
                processor = pooch.Unzip([member])
                dst = os.path.join(dst, 'Library', 'bin', member)
            else:
                member = fname.replace('.tar.xz', '/minijinja-cli')
                processor = pooch.Untar([member])
                dst = os.path.join(dst, 'bin', os.path.basename(member))
            [src] = pooch.retrieve(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                url,
                known_hash,
                processor=processor,
                downloader=_Downloader(size=size, headers=headers),
            )
            try:
                os.link(src, dst)  # pyright: ignore[reportUnknownArgumentType]
            except OSError:
                shutil.copy(src, dst)  # pyright: ignore[reportUnknownArgumentType]


class _GitHubReleaseAsset(NamedTuple):
    name: str
    size: int
    url: str


class _GitHubRelease(pydantic_settings.BaseSettings):
    assets: list[_GitHubReleaseAsset]

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
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        json_file = pooch.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            path=platformdirs.user_cache_dir('minijinja', 'mitsuhiko'),
            base_url=f'https://api.github.com/repos/mitsuhiko/minijinja/releases/',
            version=datetime.date.today().strftime('%Y.%m'),
            registry={'latest': None},
        ).fetch(
            fname='latest',
            downloader=_Downloader(headers=headers),
        )
        return (
            pydantic_settings.JsonConfigSettingsSource(settings_cls, json_file),  # pyright: ignore[reportUnknownArgumentType]
        )


def _minijinja_cli_fname():
    ext_suffix: str = sysconfig.get_config_var('EXT_SUFFIX')
    if ext_suffix.endswith('-win_amd64.pyd'):
        return 'minijinja-cli-x86_64-pc-windows-msvc.zip'
    if ext_suffix.endswith('-x86_64-linux-gnu.so'):
        return 'minijinja-cli-x86_64-unknown-linux-gnu.tar.xz'
    if ext_suffix.endswith('-darwin.so'):
        match platform.machine():
            case 'arm64':
                return 'minijinja-cli-aarch64-apple-darwin.tar.xz'
            case 'x86_64':
                return 'minijinja-cli-x86_64-apple-darwin.tar.xz'
            case _:
                pass
    raise NotImplementedError('Unsupported platform')


def _parse(path: str, fname: str):
    with open(path, encoding='ascii') as f:
        sha256 = f.read(64)
        if not (
            re.fullmatch(r'[0-9a-f]{64}', sha256)
            and f.read(2) == ' *'
            and f.read(len(fname)) == fname
            and f.read() == '\n'
        ):
            f.seek(0)
            try:
                raise ValueError(f.read())
            finally:
                f.close()
                os.unlink(path)
    return sha256


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
        json_file = pooch.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            path=pooch.os_cache('pooch'),  # pyright: ignore[reportUnknownMemberType]
            base_url='https://api.github.com/',
            version=datetime.date.today().strftime('%Y.%m'),
            registry={'meta': None},
        ).fetch(
            fname='meta',
            downloader=_Downloader(headers=headers),
        )
        return (
            pydantic_settings.JsonConfigSettingsSource(settings_cls, json_file),  # pyright: ignore[reportUnknownArgumentType]
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
        csv_file = pooch.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            path=pooch.os_cache('pooch'),  # pyright: ignore[reportUnknownMemberType]
            base_url='https://api.github.com/repos/mime-types/mime-types-data/contents/data/',
            version=datetime.date.today().strftime('%Y.%m'),
            registry={'ext_mime.db': None},
        ).fetch(
            fname='ext_mime.db',
            downloader=_Downloader(headers=headers),
        )
        series = cast(
            'pd.Series[Any]',
            pd.read_csv(csv_file, sep=r'\s+', header=None, usecols=[0, 1])  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
              .groupby(1)
              .agg(' '.join)
              .squeeze()
        )
        init_kwargs = {'mime': {'types': series.to_dict()}}  # pyright: ignore[reportUnknownMemberType]
        return (
            pydantic_settings.PyprojectTomlConfigSettingsSource(settings_cls),
            pydantic_settings.InitSettingsSource(settings_cls, init_kwargs),
        )


class _Downloader:
    def __init__(
        self,
        *,
        size: int | None = None,
        headers: dict[str, str] | None = None,
    ):
        self._size = size
        self._headers = headers.copy() if headers else {}

    def __call__(
        self,
        url: str,
        output_file: str | BinaryIO,
        pooch: pooch.Pooch,
    ):
        with contextlib.ExitStack() as stack:
            if isinstance(output_file, str):
                output_file = stack.enter_context(open(output_file, 'w+b'))
            if self._size and output_file.seekable():
                output_file.truncate(output_file.tell() + self._size)
            return _download(url, output_file, self._size, self._headers)


class _ProgressBar(Any):
    def __init__(self, output_file: BinaryIO, total: int | None):
        self.initial = 0
        self._output_file = output_file
        self._total = total

    def close(self):
        if hasattr(self, 'impl'):
            self.impl.close()

    def reset(self):
        self.impl.n = self.initial

    def update(self, n: int, /):
        self.impl.update(n)

    @property
    def total(self):
        return self._total

    @total.setter
    def total(self, value: int):
        try:
            prog = self.impl
        except AttributeError:
            if self._total is None:
                self._total = value
                if self._output_file.seekable():
                    self._output_file.truncate(self._output_file.tell() + value)
            elif value != self._total:
                raise _BadContentLength(
                    f'Expected {self._total} bytes, '
                    f'got {value} from the Content-Length header',
                )
            with warnings.catch_warnings(
                action='ignore',
                category=tqdm.TqdmExperimentalWarning,
            ):
                self.impl = tqdm.rich.tqdm(
                    total=self._total,
                    unit='B',
                    unit_scale=True,
                )
        else:
            if value != prog.total - prog.n:
                if value == prog.total and self._output_file.seekable():
                    raise _Restart()
                raise _BadContentLength(
                    f'Expected {prog.total - prog.n} bytes left, '
                    f'got {value} from the Content-Length header',
                )
            self.initial = prog.n


def _download(
    url: str,
    output_file: BinaryIO,
    total: int | None,
    headers: dict[str, str],
):
    accept_ranges = True
    initial = output_file.tell() if output_file.seekable() else 0
    last_exc = None
    progressbar = _ProgressBar(output_file, total)
    try:
        for _ in range(42):
            downloader = pooch.HTTPDownloader(progressbar, headers=headers)
            try:
                return downloader(url, output_file, None)
            except BaseException as e:
                e.__context__ = last_exc
                restart = False
                match e:
                    case _Restart():
                        accept_ranges = False
                        headers.pop('Range', None)
                        restart = True
                    case requests.RequestException():
                        if r := e.response:
                            if r.status_code >= 400:
                                raise
                            if (
                                accept_ranges and
                                r.headers.get('Accept-Ranges', 'none') != 'none'
                            ):
                                if n := progressbar.impl.n:
                                    headers['Range'] = f'bytes={n}-'
                            elif progressbar.impl.n != progressbar.initial:
                                if not output_file.seekable():
                                    raise
                                restart = True
                    case _:
                        raise
                if restart:
                    output_file.seek(initial)
                    total = progressbar.total
                    progressbar.close()
                    progressbar = _ProgressBar(output_file, total)
                last_exc = e
        assert last_exc
        raise last_exc
    finally:
        progressbar.close()


class _BadContentLength(Exception): pass
class _Restart(Exception): pass


if __name__ == '__main__':
    main()
