"""Portable topic outlines derived from saved notes, without another model call."""
from .evidence import _escape_inline, citation, format_timecode


def render_outline(state: dict, title: str, source_url: str = '') -> str:
    from .reading_products import visible_products
    sections = visible_products(state)['mindmap']
    lines = [f'# {_escape_inline(title)}', '', '> AI 主题导图 · 请结合原文核对。', '']
    if not sections:
        return '\n'.join(lines + ['导图尚未生成或原文已修改，请重新生成。'])
    for section in sections:
        lines.extend([f'## {_escape_inline(section["topic"])}', ''])
        for branch in section['branches']:
            lines.append(f'- {_escape_inline(branch["label"])}')
            for leaf in branch['children']:
                ref = citation(leaf['segment_ids'], state['segments'], source_url)
                label = format_timecode(ref['start'])
                source = (f'[{label}]({ref["url"]})' if ref['url'] else label) if ref['quote'] else '来源待确认'
                lines.append(f'  - {_escape_inline(leaf["label"])} — {source}')
        lines.append('')
    return '\n'.join(lines)
