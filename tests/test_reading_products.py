import copy

import pytest
from pydantic import ValidationError

from videosummarizer.checkpoints import Checkpoints
from videosummarizer.reading_products import (
    SummarySection, MapSection, generate_products, visible_products,
)
from videosummarizer.outline import render_outline


def test_distinct_generation_caching_citations_and_invalidation(tmp_path):
    state = {'segments': [{'id': 's1', 'text': '背景介绍。建议每周备份，以免磁盘损坏造成资料丢失。', 'start': 0, 'end': 10}], 'glossary': [], 'blocks': []}
    calls = []

    class Writer:
        def _chat_model(self, schema, prompt):
            calls.append(schema)
            if schema is SummarySection:
                return schema(heading='备份建议', takeaway='每周备份降低资料丢失风险。', points=[{'text': '建议每周备份。', 'segment_ids': ['s1', 'invented', 's1']}])
            return schema(topic='资料保护', branches=[{'label': '方法', 'children': [{'label': '每周备份', 'segment_ids': ['s1']}]}, {'label': '风险', 'children': [{'label': '磁盘损坏', 'segment_ids': ['invented']}]}])

    cache = Checkpoints(tmp_path)
    state['reading_products'] = generate_products(state, Writer(), cache, {}, lambda: None, lambda _: None)
    assert calls == [SummarySection, MapSection]
    products = visible_products(state)
    assert products['summary'][0]['points'][0]['segment_ids'] == ['s1']
    assert products['mindmap'][0]['branches'][1]['children'][0]['segment_ids'] == []
    outline = render_outline(state, '备份')
    assert '  - 每周备份' in outline and state['segments'][0]['text'] not in outline
    assert generate_products(state, Writer(), cache, {}, lambda: None, lambda _: None) == state['reading_products']
    assert len(calls) == 2
    edited = copy.deepcopy(state)
    edited['segments'][0]['text'] = '不要每周备份。'
    assert visible_products(edited) == {'summary': [], 'mindmap': []}
    assert '原文已修改' in render_outline(edited, '备份')


def test_old_lecture_is_not_disguised_as_summary_or_map():
    assert visible_products({'segments': [], 'blocks': [{'paragraphs': [{'text': '旧讲义'}]}]}) == {'summary': [], 'mindmap': []}


def test_map_rejects_paragraph_sized_nodes():
    with pytest.raises(ValidationError):
        MapSection(topic='主题', branches=[{'label': '方法', 'children': [{'label': '原话' * 50}]}])
