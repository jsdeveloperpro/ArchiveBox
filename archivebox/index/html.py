__package__ = 'archivebox.index'

from string import Template
from datetime import datetime
from typing import List, Optional, Iterator, Mapping
from pathlib import Path

from django.utils.html import format_html
from collections import defaultdict

from pathlib import Path

from .schema import Link
from ..system import atomic_write
from ..logging_util import printable_filesize
from ..util import (
    enforce_types,
    ts_to_date,
    urlencode,
    htmlencode,
    urldecode,
)
from ..config import (
    OUTPUT_DIR,
    TEMPLATES_DIR,
    VERSION,
    GIT_SHA,
    FOOTER_INFO,
    ARCHIVE_DIR_NAME,
    HTML_INDEX_FILENAME,
)

MAIN_INDEX_TEMPLATE = str(Path(TEMPLATES_DIR) / 'main_index.html')
MINIMAL_INDEX_TEMPLATE = str(Path(TEMPLATES_DIR) / 'main_index_minimal.html')
MAIN_INDEX_ROW_TEMPLATE = str(Path(TEMPLATES_DIR) / 'main_index_row.html')
LINK_DETAILS_TEMPLATE = str(Path(TEMPLATES_DIR) / 'link_details.html')
TITLE_LOADING_MSG = 'Not yet archived...'


### Main Links Index

@enforce_types
def parse_html_main_index(out_dir: Path=OUTPUT_DIR) -> Iterator[str]:
    """parse an archive index html file and return the list of urls"""

    index_path = Path(out_dir) / HTML_INDEX_FILENAME
    if index_path.exists():
        with open(index_path, 'r', encoding='utf-8') as f:
            for line in f:
                if 'class="link-url"' in line:
                    yield line.split('"')[1]
    return ()


@enforce_types
def main_index_template(links: List[Link], template: str=MAIN_INDEX_TEMPLATE) -> str:
    """render the template for the entire main index"""

    return render_legacy_template(template, {
        'version': VERSION,
        'git_sha': GIT_SHA,
        'num_links': str(len(links)),
        'date_updated': datetime.now().strftime('%Y-%m-%d'),
        'time_updated': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'rows': '\n'.join(
            main_index_row_template(link)
            for link in links
        ),
        'footer_info': FOOTER_INFO,
    })


@enforce_types
def main_index_row_template(link: Link) -> str:
    """render the template for an individual link row of the main index"""

    from ..extractors.wget import wget_output_path

    return render_legacy_template(MAIN_INDEX_ROW_TEMPLATE, {
        **link._asdict(extended=True),
        
        # before pages are finished archiving, show loading msg instead of title
        'title': htmlencode(
            link.title
            or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
        ),

        # before pages are finished archiving, show fallback loading favicon
        'favicon_url': (
            str(Path(ARCHIVE_DIR_NAME) / link.timestamp / 'favicon.ico')
            # if link['is_archived'] else 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs='
        ),

        # before pages are finished archiving, show the details page instead
        'wget_url': urlencode(wget_output_path(link) or 'index.html'),
        
        # replace commas in tags with spaces, or file extension if it's static
        'tags': (link.tags or '') + (' {}'.format(link.extension) if link.is_static else ''),
    })


### Link Details Index

@enforce_types
def write_html_link_details(link: Link, out_dir: Optional[str]=None) -> None:
    out_dir = out_dir or link.link_dir

    rendered_html = link_details_template(link)
    atomic_write(str(Path(out_dir) / HTML_INDEX_FILENAME), rendered_html)


@enforce_types
def link_details_template(link: Link) -> str:

    from ..extractors.wget import wget_output_path

    link_info = link._asdict(extended=True)

    return render_legacy_template(LINK_DETAILS_TEMPLATE, {
        **link_info,
        **link_info['canonical'],
        'title': htmlencode(
            link.title
            or (link.base_url if link.is_archived else TITLE_LOADING_MSG)
        ),
        'url_str': htmlencode(urldecode(link.base_url)),
        'archive_url': urlencode(
            wget_output_path(link)
            or (link.domain if link.is_archived else '')
        ) or 'about:blank',
        'extension': link.extension or 'html',
        'tags': link.tags or 'untagged',
        'size': printable_filesize(link.archive_size) if link.archive_size else 'pending',
        'status': 'archived' if link.is_archived else 'not yet archived',
        'status_color': 'success' if link.is_archived else 'danger',
        'oldest_archive_date': ts_to_date(link.oldest_archive_date),
    })


@enforce_types
def render_legacy_template(template_path: str, context: Mapping[str, str]) -> str:
    """render a given html template string with the given template content"""

    # will be replaced by django templates in the future
    with open(template_path, 'r', encoding='utf-8') as template:
        template_str = template.read()
    return Template(template_str).substitute(**context)




def snapshot_icons(snapshot) -> str:
    from core.models import Snapshot, EXTRACTORS

    archive_results = snapshot.archiveresult_set.filter(status="succeeded")
    link = snapshot.as_link()
    path = link.archive_path
    canon = link.canonical_outputs()
    output = ""
    output_template = '<a href="/{}/{}" class="exists-{}" title="{}">{} </a>'
    icons = {
        "singlefile": "❶",
        "wget": "🆆",
        "dom": "🅷",
        "pdf": "📄",
        "screenshot": "💻",
        "media": "📼",
        "git": "🅶",
        "archive_org": "🏛",
        "readability": "🆁",
        "mercury": "🅼",
        "warc": "📦"
    }
    exclude = ["favicon", "title", "headers", "archive_org"]
    # Missing specific entry for WARC

    extractor_items = defaultdict(lambda: None)
    for extractor, _ in EXTRACTORS:
        for result in archive_results:
            if result.extractor == extractor:
                extractor_items[extractor] = result

    for extractor, _ in EXTRACTORS:
        if extractor not in exclude:
            exists = extractor_items[extractor] is not None
            output += output_template.format(path, canon[f"{extractor}_path"], str(exists),
                                             extractor, icons.get(extractor, "?"))
        if extractor == "wget":
            # warc isn't technically it's own extractor, so we have to add it after wget
            exists = list((Path(path) / canon["warc_path"]).glob("*.warc.gz"))
            output += output_template.format(exists[0] if exists else '#', canon["warc_path"], str(bool(exists)), "warc", icons.get("warc", "?"))

        if extractor == "archive_org":
            # The check for archive_org is different, so it has to be handled separately
            target_path = Path(path) / "archive.org.txt"
            exists = target_path.exists()
            output += '<a href="{}" class="exists-{}" title="{}">{}</a> '.format(canon["archive_org_path"], str(exists),
                                                                                        "archive_org", icons.get("archive_org", "?"))

    return format_html(f'<span class="files-icons" style="font-size: 1.1em; opacity: 0.8">{output}<span>')
