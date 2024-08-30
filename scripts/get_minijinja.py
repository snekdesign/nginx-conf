# /// script
# requires-python = '>=3.12'
# dependencies = [
#   'pandas >=2.1.1',
#   'pooch >=1.8.1',
#   'pydantic-settings >=2.3.0',
#   'rich >=9.12.0',
#   'tqdm >=4.56.0',
# ]
# ///

import abc
from collections.abc import Callable
import contextlib
import dataclasses
import os
import platform
import re
import sysconfig
from typing import Any
from typing import BinaryIO
from typing import Literal
from typing import NamedTuple
from typing import NotRequired
from typing import override
from typing import Protocol
from typing import TYPE_CHECKING
from typing import TypedDict
import warnings

import pandas as pd
import platformdirs
import pooch  # pyright: ignore[reportMissingTypeStubs]
import pydantic
import pydantic_settings
import requests
import rich.logging
import tqdm.rich


def main():
    asset = _parse_args()
    pooch.get_logger().handlers[:] = [rich.logging.RichHandler()]
    known_hash = None
    for name, size, url in sorted(_GitHubRelease().assets, reverse=True):
        if name == asset + '.sha256':
            sha256 = pooch.retrieve(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                url,
                known_hash,
                downloader=_GitHubReleaseDownloader(size),
            )
            known_hash = _extract(sha256, asset)  # pyright: ignore[reportUnknownArgumentType]
        elif name == asset:
            member = asset.replace('.tar.xz', '/minijinja-cli')
            if member == asset:
                processor = pooch.Unzip(['minijinja-cli.exe'])
            else:
                processor = pooch.Untar([member])
            [minijinja_cli] = pooch.retrieve(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                url,
                known_hash,
                processor=processor,
                downloader=_GitHubReleaseDownloader(size),
            )


class _Binary(pydantic_settings.BaseSettings):
    platform: Literal[
        'linux-64',
        'osx-64',
        'osx-arm64',
        'win-64',
    ] | None = None
    musl: bool = False

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
        cli_settings = pydantic_settings.CliSettingsSource[Any](
            settings_cls,
            cli_hide_none_type=True,
            cli_parse_args=True,
            cli_parse_none_str='auto',
        )
        return (cli_settings,)

    @pydantic.model_validator(mode='after')
    def _post_processing(self):
        if self.musl:
            match self.platform:
                case 'linux-64':
                    pass
                case None:
                    self.platform = 'linux-64'
                case p:
                    raise ValueError('--musl conflicts with --platform='+p)
        elif not self.platform:
            ext_suffix: str = sysconfig.get_config_var('EXT_SUFFIX')
            if ext_suffix.endswith('-win_amd64.pyd'):
                self.platform = 'win-64'
            elif ext_suffix.endswith('-x86_64-linux-gnu.so'):
                self.platform = 'linux-64'
            elif ext_suffix.endswith('-x86_64-linux-musl.so'):
                self.platform = 'linux-64'
                self.musl = True
            else:
                if ext_suffix.endswith('-darwin.so'):
                    match platform.machine():
                        case 'arm64':
                            self.platform = 'osx-arm64'
                        case 'x86_64':
                            self.platform = 'osx-64'
                        case _:
                            pass
                raise RuntimeError(
                    'minijinja-cli binary is unavailable on your platform')
        return self


class _Downloader(Protocol):
    def __call__(
        self,
        url: str,
        output_file: str | BinaryIO,
        pooch: pooch.Pooch,
    ) -> object: ...


def _extract(path: str, asset: str):
    with open(path, encoding='ascii') as f:
        sha256 = f.read(64)
        if not (
            re.fullmatch(r'[0-9a-f]{64}', sha256)
            and f.read(2) == ' *'
            and f.read(len(asset)) == asset
            and f.read() == '\n'
        ):
            f.seek(0)
            try:
                raise ValueError(f.read())
            finally:
                f.close()
                os.unlink(path)
    return sha256


class _GitHubReleaseAsset(NamedTuple):
    name: str
    size: int
    url: str


class _GitHubReleaseBase(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(extra='ignore')

    if TYPE_CHECKING:
        assets: list[_GitHubReleaseAsset] = []
    else:
        assets: list[_GitHubReleaseAsset]

    @classmethod
    @abc.abstractmethod
    def repodata(cls) -> tuple[str, str, str]:
        raise NotImplementedError()

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
        appname, appauthor, since = cls.repodata()
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        json_file = pooch.create(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            path=platformdirs.user_cache_dir(appname, appauthor, since),
            base_url=f'https://api.github.com/repos/{appauthor}/{appname}/releases/',
            registry={'latest': None},
        ).fetch(
            'latest',
            downloader=pooch.HTTPDownloader(headers=headers),
        )
        json_settings = pydantic_settings.JsonConfigSettingsSource(
            settings_cls,
            json_file,  # pyright: ignore[reportUnknownArgumentType]
        )
        return (json_settings,)


class _GitHubRelease(_GitHubReleaseBase):
    @override
    @classmethod
    def repodata(cls) -> tuple[str, str, str]:
        appname = 'minijinja'
        appauthor = 'mitsuhiko'
        since = pd.Timestamp.now().floor('7D').strftime('%Y%m%d')
        return (appname, appauthor, since)


@dataclasses.dataclass(eq=False, match_args=False, repr=False)
class _GitHubReleaseDownloader(_Downloader):
    size: int
    _: dataclasses.KW_ONLY
    retries: int = 42
    sub_downloader: Callable[..., _Downloader] = pooch.HTTPDownloader

    def __call__(
        self,
        url: str,
        output_file: str | BinaryIO,
        pooch: pooch.Pooch,
    ):
        headers: _Headers = {
            'Accept': 'application/octet-stream',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        last_exc = None
        with self._open(output_file) as f:
            for _ in range(self.retries + 1):
                if n := f.tell():
                    headers['Range'] = f'bytes={n}-'
                downloader = self.sub_downloader(self, headers=headers)
                try:
                    return downloader(url, f, pooch)
                except requests.RequestException as e:
                    e.__context__ = last_exc
                    if r := e.response:
                        if r.headers.get('Accept-Ranges', 'none') == 'none':
                            raise
                    last_exc = e
                except BaseException as e:
                    e.__context__ = last_exc
                    raise
        assert last_exc
        raise last_exc

    def close(self):
        pass

    @contextlib.contextmanager
    def _open(self, output_file: str | BinaryIO):
        with contextlib.ExitStack() as stack:
            if isinstance(output_file, str):
                output_file = stack.enter_context(open(output_file, 'w+b'))
            prog_osc = tqdm.tqdm(
                bar_format='\x1b]9;4;1;{percentage:.0f}\a',
                total=self.size,
            )
            stack.callback(
                print,
                end='\x1b]9;4;0\a',
                file=prog_osc.fp,
                flush=True,
            )
            stack.enter_context(prog_osc)
            with warnings.catch_warnings(
                action='ignore',
                category=tqdm.TqdmExperimentalWarning,
            ):
                prog_rich = tqdm.rich.tqdm(
                    total=self.size,
                    unit='B',
                    unit_scale=True,
                )
            stack.enter_context(prog_rich)
            self._progs = (prog_osc, prog_rich)
            yield output_file

    def reset(self):
        for prog in self._progs:
            prog.n = self._initial

    @property().setter
    def total(self, value: int):
        for prog in self._progs:
            if value != prog.total - prog.n:
                raise ValueError(
                    f'Expected {prog.total - prog.n} bytes left, '
                    f'got {value} from the Content-Length header',
                )
            self._initial = prog.n

    def update(self, n: int):
        for prog in self._progs:
            prog.update(n)


class _Headers(TypedDict('Headers', {'X-GitHub-Api-Version': str})):
    Accept: str
    Range: NotRequired[str]


def _parse_args():
    binary = _Binary()
    match binary.platform:
        case 'linux-64':
            if binary.musl:
                asset = 'minijinja-cli-x86_64-unknown-linux-musl.tar.xz'
            else:
                asset = 'minijinja-cli-x86_64-unknown-linux-gnu.tar.xz'
        case 'osx-64':
            asset = 'minijinja-cli-x86_64-apple-darwin.tar.xz'
        case 'osx-arm64':
            asset = 'minijinja-cli-aarch64-apple-darwin.tar.xz'
        case 'win-64':
            asset = 'minijinja-cli-x86_64-pc-windows-msvc.zip'
        case _:
            assert False, 'unreachable'
    return asset


if __name__ == '__main__':
    main()
