from zipfile import ZipFile
from xml.etree import ElementTree as ET

import pytest

from videosummarizer.evidence import make_workspace, time_link, render_markdown
from videosummarizer.exports import export_workspace
from videosummarizer.outline import render_outline


def state():
    return make_workspace({'segments': [{'start': 37.8, 'end': 40, 'text': '原文 <内容> & [链接]'}]})


@pytest.mark.parametrize('url,expected', [
    ('https://youtu.be/abcdefghijk?t=9', 'https://www.youtube.com/watch?v=abcdefghijk&t=37s'),
    ('https://www.youtube.com/shorts/abcdefghijk', 'https://www.youtube.com/watch?v=abcdefghijk&t=37s'),
    ('https://www.bilibili.com/video/BV1xx411c7mD?p=2&tracking=discard', 'https://www.bilibili.com/video/BV1xx411c7mD?t=37&p=2'),
    ('https://www.bilibili.com/video/av123?p=3', 'https://www.bilibili.com/video/av123?t=37&p=3'),
    ('https://www.bilibili.com/video/av123?p=2&p=3', ''),
    ('https://www.bilibili.com/video/av123?p=', ''),
    ('https://www.bilibili.com/video/av123?p=0', ''),
    ('https://www.bilibili.com/video/av123?p=<script>', ''),
    ('https://youtube.com.evil.test/watch?v=abcdefghijk', ''),
    ('https://user:password@youtube.com/watch?v=abcdefghijk', ''),
    ('javascript:alert(1)', ''),
    ('https://[::1]/watch?v=abcdefghijk', ''),
    ('https://example.org/movie.mp4', ''),
])
def test_time_navigation(url, expected):
    assert time_link(url, 37.8) == expected


def test_unknown_and_invalid_time():
    assert time_link('https://youtu.be/abcdefghijk', float('nan')).endswith('t=0s')
    assert time_link('https://youtu.be/abcdefghijk', None).endswith('t=0s')


@pytest.mark.parametrize('source,linked', [('https://youtu.be/abcdefghijk', True), ('https://example.org/movie.mp4', False), ('', False)])
def test_transcript_timestamp_exports(tmp_path, source, linked):
    data = state()
    md = render_markdown(data, '材料', source)
    assert ('[00:00:37](https://www.youtube.com/' in md) == linked
    assert '&lt;内容&gt;' in md
    path = export_workspace(data, {'job_dir': str(tmp_path), 'title': '材料', 'url': source}, 'docx')
    with ZipFile(path) as archive:
        rels = ET.fromstring(archive.read('word/_rels/document.xml.rels'))
        targets = [item.attrib['Target'] for item in rels if item.attrib['Type'].endswith('/hyperlink')]
        assert bool(targets) == linked
        if linked:
            assert targets == ['https://www.youtube.com/watch?v=abcdefghijk&t=37s']


def test_outline_preserves_text_stale_and_unknown_citations(tmp_path):
    data = state()
    data['blocks'] = [{'heading': '<script>主题', 'stale': True, 'paragraphs': [
        {'text': '有效 ![图片](https://evil.test/pixel)', 'segment_ids': ['s000001']},
        {'text': '无出处内容', 'segment_ids': ['missing']},
    ]}]
    from videosummarizer.reading_products import source_key
    data['reading_products'] = {'source_key': source_key(data), 'mindmap': [{'topic':'<script>主题', 'branches':[{'label':'方法','children':[{'label':'有效 ![图片](https://evil.test/pixel)','segment_ids':['s000001']},{'label':'无出处内容','segment_ids':['missing']}]}]}]}
    text = render_outline(data, '材料', 'https://youtu.be/abcdefghijk')
    assert '来源待确认' in text
    assert '[00:00:37](https://www.youtube.com/watch?v=abcdefghijk&t=37s)' in text
    assert '<script>' not in text and '![图片](' not in text
    path = export_workspace(data, {'job_dir': str(tmp_path), 'title': '材料'}, 'outline')
    assert path.name.endswith('_导图.md') and '无出处内容' in path.read_text(encoding='utf-8')
    path = export_workspace(data, {'job_dir': str(tmp_path), 'title': '材料'}, 'docx')
    with ZipFile(path) as archive:
        doc = archive.read('word/document.xml').decode()
        assert '来源待确认' in doc and '来源 00:00:00–00:00:00' not in doc


def test_empty_outline_is_explicit():
    assert '导图尚未生成' in render_outline(state(), '材料')
