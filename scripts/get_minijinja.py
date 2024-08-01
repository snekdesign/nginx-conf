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

import os
import platform
import sysconfig
from typing import Literal
from typing import NamedTuple
from typing import override
import warnings

import pandas as pd
import pooch
import pydantic
import pydantic_settings
import rich.logging
import tqdm.rich


def main():
    asset = _parse_args()
    pooch.get_logger().handlers[:] = [rich.logging.RichHandler()]
    files = {name: (url, size) for name, size, url in _GitHubRelease().assets}
    sha256 = _retrieve(*files[asset+'.sha256'])
    [minijinja_cli] = _retrieve(
        *files[asset],
        known_hash=_extract(sha256, asset),
        processor=(
            pooch.Untar([asset.replace('.tar.xz', '/minijinja-cli')])
            if asset.endswith('.tar.xz') else
            pooch.Unzip(['minijinja-cli.exe'])
        ),
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
        cls, settings_cls, init_settings, env_settings, dotenv_settings,
        file_secret_settings,
    ):
        cli_settings = pydantic_settings.CliSettingsSource(
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
                raise RuntimeError(
                    'minijinja-cli binary is unavailable on your platform')
        return self


def _extract(path: str, asset: str):
    with open(path, encoding='ascii') as f:
        sha256 = f.read(64)
        if not (
            len(sha256) == 64
            and set(sha256).issubset('0123456789abcdef')
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


class _GitHubRelease(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(extra='ignore')

    assets: list[_GitHubReleaseAsset]

    @override
    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings,
        file_secret_settings,
    ):
        dirname = pooch.os_cache('minijinja-cli')
        basename = pd.Timestamp.now().floor('7D').strftime('%Y%m%d')
        headers = {
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        json_file = pooch.create(
            dirname / basename,
            'https://api.github.com/repos/mitsuhiko/minijinja/releases/',
            registry={'latest': None},
        ).fetch(
            'latest',
            downloader=pooch.HTTPDownloader(headers=headers),
        )
        json_settings = pydantic_settings.JsonConfigSettingsSource(
            settings_cls, json_file)
        return (json_settings,)


class _HTTPDownloader:
    def __init__(self, size):
        self._size = size

    def __call__(self, url, output_file, pooch_):
        with warnings.catch_warnings(action='ignore'):
            progressbar = _tqdm(total=self._size, unit='B', unit_scale=True)
        headers = {
            'Accept': 'application/octet-stream',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        downloader = pooch.HTTPDownloader(progressbar, headers=headers)
        return downloader(url, output_file, pooch_)


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


def _retrieve(url, size, known_hash=None, processor=None):
    return pooch.retrieve(
        url,
        known_hash,
        processor=processor,
        downloader=_HTTPDownloader(size),
    )


# https://github.com/tqdm/tqdm/issues/1378
# https://github.com/tqdm/tqdm/pull/1596
class _tqdm(tqdm.rich.tqdm):
    @override
    def reset(self, total=None):
        if hasattr(self, '_prog'):
            self._prog.reset(self._task_id, total=total)
        super(tqdm.rich.tqdm, self).reset(total=total)

    @property
    def total(self):
        return self._total

    @total.setter
    def total(self, new):
        try:
            old = self._total
        except AttributeError:
            self._total = new
        else:
            if new != old:
                raise RuntimeError(f'asset.size={old}, Content-Length={new}')


if __name__ == '__main__':
    main()
