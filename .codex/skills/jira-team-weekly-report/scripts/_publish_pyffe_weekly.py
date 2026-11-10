#!/usr/bin/env python3
"""Create or fill the Android section of the Pyffe weekly Confluence page."""

import argparse
from datetime import datetime, time, timedelta
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "utilities"))
import clone_weekly_pages as clone

TEMPLATE_ID = 1403191574


def inline(text):
    """Render the report's Markdown links and bold text as storage-format HTML."""
    pattern = re.compile(r'\[([^\]]+)\]\((https?://[^\s)]+)\)|\*\*([^*]+)\*\*|\[(DONE|IN PROGRESS)\]')
    result, end = [], 0
    for match in pattern.finditer(text):
        result.append(escape(text[end:match.start()]))
        if match.group(1) is not None:
            result.append('<a href="' + escape(match.group(2), quote=True) + '">' + escape(match.group(1)) + '</a>')
        elif match.group(3) is not None:
            result.append('<strong>' + escape(match.group(3)) + '</strong>')
        else:
            status = match.group(4)
            colour = 'Green' if status == 'DONE' else 'Blue'
            result.append('<ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">' + colour + '</ac:parameter><ac:parameter ac:name="title">' + status + '</ac:parameter></ac:structured-macro>')
        end = match.end()
    return ''.join(result) + escape(text[end:])


def report_html(markdown):
    """Render the report format as a list, including its ticket reference table."""
    lines = markdown.splitlines()
    parts = []
    nested = False
    table = False
    skip_section = False
    for line in lines:
        if not line.strip():
            continue
        if line.startswith('# '):
            continue
        if line.startswith('- '):
            label = re.sub(r'\*\*', '', line[2:]).strip().rstrip(':').casefold()
            skip_section = label in {'referenced jira tickets', 'scope and limitations'}
        if skip_section:
            continue
        if line.startswith('  |'):
            cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
            if all(re.fullmatch(r':?-{3,}:?', cell) for cell in cells):
                continue
            if not table:
                if not nested:
                    raise ValueError('Ticket table must follow a section bullet')
                parts.append('<li><table><tbody>')
                table = True
                tag = 'th'
            else:
                tag = 'td'
            parts.append('<tr>' + ''.join(f'<{tag}><p>{inline(c)}</p></{tag}>' for c in cells) + '</tr>')
            continue
        if table:
            parts.append('</tbody></table></li>')
            table = False
        if line.startswith('- '):
            if nested:
                parts.append('</ul></li>')
            parts.append('<li><p>' + inline(line[2:]) + '</p><ul>')
            nested = True
        elif line.startswith('  - ') and nested:
            parts.append('<li><p>' + inline(line[4:]) + '</p></li>')
        else:
            raise ValueError('Unsupported Markdown line: ' + line[:120])
    if table:
        parts.append('</tbody></table></li>')
    if nested:
        parts.append('</ul></li>')
    if not parts:
        raise ValueError('Report has no content')
    return ''.join(parts)


class AndroidSection(HTMLParser):
    """Locate the Android list in the first progress table without rewriting storage XML."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))
        self.stack = []
        self.table_count = 0
        self.capture = None
        self.matches = []

    def pos(self):
        line, col = self.getpos()
        return self.offsets[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self.pos()
        raw = self.get_starttag_text()
        node = {'tag': tag, 'start': start, 'open_end': start + len(raw), 'text': ''}
        if tag == 'table':
            self.table_count += 1
        if self.table_count == 1 and tag == 'li' and any(n['tag'] == 'table' for n in self.stack):
            node['first_table'] = True
        self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_data(self, data):
        for node in self.stack:
            node['text'] += data

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1]['tag'] != tag:
            return
        node = self.stack.pop()
        if tag == 'ul' and self.stack and self.stack[-1]['tag'] == 'li':
            parent = self.stack[-1]
            if parent.get('first_table') and parent['text'].strip().rstrip(':').strip().lower() == 'android':
                self.matches.append((node['open_end'], node['start'], self.pos(), node['text']))


def fill_android(body, html):
    parser = AndroidSection(body)
    parser.feed(body)
    if len(parser.matches) != 1:
        raise ValueError('Could not uniquely identify the Android section in the first table')
    content_start, _, content_end, text = parser.matches[0]
    current = body[content_start:content_end]
    if text.strip() or not re.fullmatch(r'\s*(?:<li\b[^>]*>\s*<p\b[^>]*/>\s*</li>\s*)*', current):
        raise ValueError('Android section is not empty; refusing to overwrite existing content')
    return body[:content_start] + html + body[content_end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path, help='English Markdown report to publish')
    parser.add_argument('--start', required=True, help='Monday of the report week (YYYY-MM-DD)')
    args = parser.parse_args()
    try:
        monday_date = datetime.strptime(args.start, '%Y-%m-%d').date()
        if monday_date.weekday() != 0:
            raise ValueError('Report start date must be a Monday')
        monday = datetime.combine(monday_date, time.min)
        friday = monday + timedelta(days=4)
        html = report_html(args.report.read_text(encoding='utf-8'))
        email, token = clone.get_credentials()
        info = clone.fetch_page_info(TEMPLATE_ID, email, token, monday.isocalendar()[1], monday, friday)
        endpoint = f"content?spaceKey={quote(info['space_key'])}&title={quote(info['new_title'])}&type=page&expand=body.storage,version"
        found = clone.api_get(endpoint, email, token).get('results', [])
        if len(found) > 1:
            raise ValueError('Multiple pages match the weekly title')
        if found:
            page = found[0]
            new_body = fill_android(page['body']['storage']['value'], html)
            payload = {'id': page['id'], 'type': 'page', 'title': page['title'],
                       'version': {'number': page['version']['number'] + 1},
                       'body': {'storage': {'value': new_body, 'representation': 'storage'}}}
            import requests
            response = requests.put(f"{clone.CONFLUENCE_BASE}/rest/api/content/{page['id']}",
                                    auth=(email, token), json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
        else:
            info['body_html'] = fill_android(info['body_html'], html)
            payload = {'type': 'page', 'title': info['new_title'], 'space': {'key': info['space_key']},
                       'body': {'storage': {'value': info['body_html'], 'representation': 'storage'}}}
            if info['parent_id']:
                payload['ancestors'] = [{'id': str(info['parent_id'])}]
            result = clone.api_post('content', payload, email, token)
        if not result.get('id'):
            raise RuntimeError('Confluence did not return a page ID')
        print(f"{clone.CONFLUENCE_BASE}/spaces/{info['space_key']}/pages/{result['id']}")
    except (ValueError, KeyError, OSError, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
