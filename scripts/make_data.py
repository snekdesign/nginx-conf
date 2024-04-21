# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pandas >=1.3.3",
# ]
# ///

import ipaddress
import json
import math
import os

import pandas as pd


def main() -> None:
    os.chdir('build/tmp')
    obj = {
        'github_web': _github_web(),
        'mime_types': _mime_types(),
        'proxy_store': 'F:/var/www',
        'root': 'F:/var/www',
    }
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(obj, f, separators=(',', ':'))


def _github_web() -> dict[str, int]:
    with open('meta.json', encoding='utf-8') as f:
        match json.load(f):
            case {'web': list(addresses)}:
                pass
            case _:
                raise TypeError('Error parsing https://api.github.com/meta')

    networks = list['ipaddress.IPv4Network']()
    for address in addresses:
        try:
            network = ipaddress.IPv4Network(address)
        except ValueError:
            pass
        else:
            networks.append(network)

    max_num_addresses = max([network.num_addresses for network in networks])
    return {
        str(k): v
        for network in networks
        for v in [max_num_addresses // network.num_addresses]
        for k in network.hosts()
    }


def _mime_types() -> dict[str, str]:
    return (
        pd.read_csv('ext_mime.db', sep=r'\s+', header=None, usecols=[0, 1])
          .groupby(1)
          .agg(' '.join)
          .squeeze()
          .to_dict()
    )


if __name__ == '__main__':
    main()
