"""Portable topic outlines derived from saved notes, without another model call."""
from .evidence import _escape_inline, citation, format_timecode


def render_outline(state: dict, title: str, source_url: str = '') -> str:
    if 'reading_products' in state:
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
    lines = [f'# {_escape_inline(title)}', '', '> 结构导图：由现有讲义整理，未额外生成或核实内容。', '']
    if not state['blocks']:
        lines.extend(['尚未生成讲义，请先生成讲义再导出结构导图。', ''])
    for block in state['blocks']:
        suffix = '（待更新）' if block.get('stale') else ''
        lines.extend([f'## {_escape_inline(block["heading"])}{suffix}', ''])
        for paragraph in block['paragraphs']:
            ref = citation(paragraph['segment_ids'], state['segments'], source_url)
            label = format_timecode(ref['start'])
            if not ref['quote']:
                source = '来源待确认'
            elif ref['url']:
                source = f'[{label}]({ref["url"]})'
            else:
                source = label
            uncertainty = '（来源待核实）' if paragraph.get('review') == 'unverified' else ''
            lines.append(f'- {_escape_inline(paragraph["text"])}{uncertainty} — {source}')
        lines.append('')
    return '\n'.join(lines)
