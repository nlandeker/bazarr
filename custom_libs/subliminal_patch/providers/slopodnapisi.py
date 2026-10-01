# -*- coding: utf-8 -*-
from __future__ import absolute_import
import io
import logging
import os
import re

from random import randint
from zipfile import ZipFile, is_zipfile

from subzero.language import Language

from subliminal.exceptions import ProviderError
from subliminal.providers import ParserBeautifulSoup, Provider
from subliminal.subtitle import SUBTITLE_EXTENSIONS, Subtitle, fix_line_ending
from subliminal.utils import sanitize
from subliminal.video import Movie
from .utils import FIRST_THOUSAND_OR_SO_USER_AGENTS as AGENT_LIST

try:
    from subliminal_patch.http import RetryingCFSession
except ImportError:
    from requests import Session as RetryingCFSession

logger = logging.getLogger(__name__)

# Result rows carry a flag image named after the subtitle's language, e.g.
# https://www.slo-podnapisi.net/nastavitve/slike/slo.png. Only Slovenian is
# supported for now; hrv/en flags exist on the site but are skipped.
_LANGUAGE_FLAGS = {
    'slo': Language('slv'),
}

_TITLE_YEAR_RE = re.compile(r'^(?P<title>.*)\((?P<year>\d{4})\)\s*$')
_SUBTITLE_ID_RE = re.compile(r'/info/p/(\d+)/')


class SlopodnapisiSubtitle(Subtitle):
    """Slo-Podnapisi Subtitle."""
    provider_name = 'slopodnapisi'
    hash_verifiable = False
    hearing_impaired_verifiable = False

    def __init__(self, language, page_link, subtitle_id, title, year):
        super(SlopodnapisiSubtitle, self).__init__(language, page_link=page_link)
        self.subtitle_id = subtitle_id
        self.title = title
        self.year = year
        self.release_info = title

    @property
    def id(self):
        return str(self.subtitle_id)

    def get_matches(self, video):
        matches = set()
        if isinstance(video, Movie):
            if video.title and sanitize(self.title) == sanitize(video.title):
                matches.add('title')
            if video.year and self.year and video.year == self.year:
                matches.add('year')
        return matches


class SlopodnapisiProvider(Provider):
    """Slo-Podnapisi Provider."""
    languages = {Language('slv')}
    video_types = (Movie,)
    server_url = 'https://www.slo-podnapisi.net'
    search_url = server_url + '/podnapisi/'
    subtitle_class = SlopodnapisiSubtitle

    def __init__(self):
        self.session = None

    def initialize(self):
        self.session = RetryingCFSession()
        self.session.headers['User-Agent'] = AGENT_LIST[randint(0, len(AGENT_LIST) - 1)]

    def terminate(self):
        self.session.close()

    def query(self, title):
        r = self.session.get(self.search_url, params={'isci': title}, timeout=10)
        r.raise_for_status()

        soup = ParserBeautifulSoup(r.content.decode('utf-8', 'ignore'), ['html.parser'])

        # The results table is corrupt enough (mismatched tags) that walking
        # row containers drops fields. Title links and language flags are
        # each reliably intact and appear in the same order, one per row, so
        # they're collected separately and paired up positionally instead.
        title_links = soup.select('span.podnapisi_podnapis_text_levo a[href]')
        flags = soup.select('img.podnapisi_jezik_slikca[src]')

        subtitles = []
        for link, flag in zip(title_links, flags):
            language = _LANGUAGE_FLAGS.get(os.path.splitext(os.path.basename(flag['src']))[0])
            if language is None:
                continue

            id_match = _SUBTITLE_ID_RE.search(link['href'])
            if not id_match:
                continue

            text = link.get_text(strip=True)
            year_match = _TITLE_YEAR_RE.match(text)
            if year_match:
                found_title = year_match.group('title').strip()
                year = int(year_match.group('year'))
            else:
                found_title, year = text, None

            subtitles.append(self.subtitle_class(language, link['href'], id_match.group(1), found_title, year))

        return subtitles

    def list_subtitles(self, video, languages):
        if not isinstance(video, Movie):
            return []

        for title in [video.title] + video.alternative_titles:
            subtitles = [s for s in self.query(title) if sanitize(s.title) == sanitize(title)]
            if subtitles:
                return [s for s in subtitles if s.language in languages]

        return []

    def download_subtitle(self, subtitle):
        logger.info('Downloading subtitle %r', subtitle)

        r = self.session.get(subtitle.page_link, timeout=10)
        r.raise_for_status()
        soup = ParserBeautifulSoup(r.content.decode('utf-8', 'ignore'), ['html.parser'])

        link = soup.select_one('a[href*="prenesi-podnapis"]')
        if not link or not link.get('href'):
            raise ProviderError('Could not find download link for subtitle {}'.format(subtitle.id))

        r = self.session.get(link['href'], timeout=30)
        r.raise_for_status()

        archive_stream = io.BytesIO(r.content)
        if not is_zipfile(archive_stream):
            raise ProviderError('Unrecognized archive format for subtitle {}'.format(subtitle.id))

        archive_stream.seek(0)
        with ZipFile(archive_stream) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(SUBTITLE_EXTENSIONS)]
            if not names:
                raise ProviderError('No subtitle file found in zip archive')
            subtitle.content = fix_line_ending(zf.read(names[0]))
