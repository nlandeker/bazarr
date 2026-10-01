import os
import zipfile

import pytest
import subliminal
from subzero.language import Language
from subliminal_patch.providers.slopodnapisi import SlopodnapisiProvider
from subliminal.subtitle import SUBTITLE_EXTENSIONS, fix_line_ending
from subliminal_patch.core import Movie

BASE_URL = 'https://www.slo-podnapisi.net'
SEARCH_URL = f'{BASE_URL}/podnapisi/'


@pytest.fixture(scope="session")
def region():
    subliminal.region.configure('dogpile.cache.memory', replace_existing_backend=True)


@pytest.fixture(scope="session")
def oppenheimer():
    return Movie(
        "Oppenheimer.2023.1080p.BluRay.x264-SHITBOX.mkv",
        "Oppenheimer",
        year=2023,
        resolution="1080p",
        source="Blu-Ray",
        release_group="SHITBOX",
    )


def test_list_subtitles(region, oppenheimer, requests_mock, data):
    with open(os.path.join(data, 'slopodnapisi_search_oppenheimer.html'), 'rb') as f:
        requests_mock.get(SEARCH_URL, content=f.read())

    with SlopodnapisiProvider() as provider:
        subtitles = provider.list_subtitles(oppenheimer, {Language('slv')})

    # the near-match "To End All War: Oppenheimer & The Atomic Bomb" is filtered out
    assert len(subtitles) == 1
    assert subtitles[0].title == 'Oppenheimer'
    assert subtitles[0].year == 2023
    assert subtitles[0].language == Language('slv')
    assert subtitles[0].subtitle_id == '36439'


def test_list_subtitles_no_results(region, requests_mock, data):
    with open(os.path.join(data, 'slopodnapisi_search_no_results.html'), 'rb') as f:
        requests_mock.get(SEARCH_URL, content=f.read())

    video = Movie(
        "Nonexistent.Movie.2050.720p.BluRay.x264-SPARKS.mkv",
        "Nonexistent Movie",
        year=2050,
    )

    with SlopodnapisiProvider() as provider:
        subtitles = provider.list_subtitles(video, {Language('slv')})

    assert subtitles == []


def test_get_matches(region, oppenheimer, requests_mock, data):
    with open(os.path.join(data, 'slopodnapisi_search_oppenheimer.html'), 'rb') as f:
        requests_mock.get(SEARCH_URL, content=f.read())

    with SlopodnapisiProvider() as provider:
        subtitle = provider.list_subtitles(oppenheimer, {Language('slv')})[0]

    matches = subtitle.get_matches(oppenheimer)
    assert 'title' in matches
    assert 'year' in matches


def test_download_subtitle(region, oppenheimer, requests_mock, data):
    with open(os.path.join(data, 'slopodnapisi_search_oppenheimer.html'), 'rb') as f:
        requests_mock.get(SEARCH_URL, content=f.read())
    with open(os.path.join(data, 'slopodnapisi_detail_36439.html'), 'rb') as f:
        requests_mock.get(f'{BASE_URL}/info/p/36439/l/2023/i/oppenheimer/', content=f.read())
    zip_path = os.path.join(data, 'slopodnapisi_sub_36439.zip')
    with open(zip_path, 'rb') as f:
        zip_content = f.read()
    requests_mock.get(
        f'{BASE_URL}/prenesi-podnapis/prenos/de0493971745f93e3c7cf916a3cc9f6d.zip/',
        content=zip_content,
    )

    with SlopodnapisiProvider() as provider:
        subtitle = provider.list_subtitles(oppenheimer, {Language('slv')})[0]
        provider.download_subtitle(subtitle)

    assert subtitle.content is not None

    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(SUBTITLE_EXTENSIONS)]
        expected = fix_line_ending(zf.read(names[0]))

    assert subtitle.content == expected
