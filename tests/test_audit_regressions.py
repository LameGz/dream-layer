"""Regressions for night windows, immutable dream identities and ingestion."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from dreamlayer import journal, reflux
from dreamlayer.collectors.read_disk import read_md_file
from dreamlayer.contract import build_material
from dreamlayer.engine import FakeEngine
from dreamlayer.pool import Pool
from dreamlayer.scheduler import collect_phase, dream_phase, wake_phase


def test_night_pairs_previous_day_material(cfg, tmp_project):
    cfg.rhythm.quiet_cycle = {'mode': 'off'}
    now = datetime(2026, 10, 16, 3)
    pool = Pool(cfg.weights)
    for i in range(20):
        material = build_material({'id': f'item-{i}', 'content': f'fragment {i}',
                                   'time': '2026-10-15T18:00:00', 'tag': 'rejected'}, {}, 2000).material
        pool.add(material)
    dream_phase(cfg, FakeEngine(), tmp_project['data'], now=now, pool=pool)
    meta, dreams = journal.read_dreams(tmp_project['data'] / 'dreams/2026-10-16.jsonl')
    assert meta['pairs'] == 10
    assert len(dreams) == 10
    assert len({key for d in dreams for key in d['pair']}) == 20


def test_same_day_rerun_preserves_confirmed_identity(tmp_path):
    day = date(2026, 10, 16)
    def dream(pair):
        return {'pair': pair, 'raw': 'synthetic', 'persona': 'test', 'verdict': 'cross_time'}
    journal.write_dreams(day, [dream(['a', 'b'])], {'pairs': 1}, tmp_path / 'dreams')
    _, records = journal.read_dreams(tmp_path / 'dreams/2026-10-16.jsonl')
    first = records[0]
    reflux.append_confirm(tmp_path, first['dream_id'], 'cross_time', first)
    reflux.mark_confirmed(tmp_path, first['dream_id'])
    journal.write_dreams(day, [dream(['c', 'd'])], {'pairs': 1}, tmp_path / 'dreams')
    _, records = journal.read_dreams(tmp_path / 'dreams/2026-10-16.jsonl')
    second = records[0]
    assert second['dream_id'] != first['dream_id']
    assert reflux.find_dream(tmp_path, first['dream_id'])['pair'] == ['a', 'b']
    assert reflux.find_dream(tmp_path, second['dream_id'])['pair'] == ['c', 'd']
    assert not reflux.already_confirmed(reflux.load_log(tmp_path), second['dream_id'])
    reflux.mark_confirmed(tmp_path, first['dream_id'])
    assert not reflux.find_dream(tmp_path, second['dream_id']).get('confirmed')


def test_legacy_dream_still_found_after_new_attempt(tmp_path):
    day = date(2026, 10, 16)
    old = {'dream_id': '2026-10-16-01', 'pair': ['a', 'b'], 'raw': 'legacy'}
    journal.write_dreams(day, [old], {}, tmp_path / 'dreams')
    journal.write_dreams(day, [{'pair': ['c', 'd'], 'raw': 'new'}], {}, tmp_path / 'dreams')
    assert reflux.find_dream(tmp_path, old['dream_id'])['pair'] == ['a', 'b']


def test_wake_update_keeps_identity_and_confirmation(tmp_path):
    day = date(2026, 10, 16)
    journal.write_dreams(day, [{'pair': ['a', 'b'], 'raw': 'one'}], {}, tmp_path / 'dreams')
    path = tmp_path / 'dreams/2026-10-16.jsonl'
    meta, records = journal.read_dreams(path)
    ident = records[0]['dream_id']
    reflux.mark_confirmed(tmp_path, ident)
    records[0]['verdict'] = 'noise'
    journal.write_dreams(day, records, meta, tmp_path / 'dreams')
    current = reflux.find_dream(tmp_path, ident)
    assert current['verdict'] == 'noise'
    assert current.get('confirmed') is True


def test_expired_source_is_not_reingested(cfg, tmp_project):
    old = {'id': 'expired', 'content': 'old source', 'time': '2025-01-01', 'tag': 'selected'}
    collector = SimpleNamespace(collect=lambda: [old], tag_map={})
    for now in [datetime(2026, 10, 16), datetime(2026, 10, 17)]:
        pool, meta = collect_phase(cfg, [collector], tmp_project['data'], now=now)
        assert len(pool) == 0
        assert meta['dropped'] == 1


def test_unclosed_frontmatter_uses_mtime(tmp_path):
    path = tmp_path / 'unfinished.md'
    path.write_text('---\ntitle: unfinished\nbody', encoding='utf-8')
    record = read_md_file(path, 'selected', 'test')[0]
    assert record['content'].startswith('---')
    assert datetime.fromisoformat(record['time']) == datetime.fromtimestamp(path.stat().st_mtime)


def test_empty_attempt_does_not_replay_prior_dreams(cfg, tmp_project):
    cfg.rhythm.quiet_cycle = {'mode': 'off'}
    now = datetime(2026, 10, 16, 3)
    data = tmp_project['data']
    journal.write_dreams(now.date(), [{'pair': ['a', 'b'], 'raw': 'old'}], {'pairs': 1}, data / 'dreams')
    dream_phase(cfg, FakeEngine(), data, now=now, pool=Pool(cfg.weights))
    meta, current = journal.read_dreams(data / 'dreams/2026-10-16.jsonl')
    assert current == []
    observations, morning = wake_phase(cfg, FakeEngine(), data, now=now, pool=Pool(cfg.weights))
    assert observations == []
    assert journal.REASON_NO_MATERIAL in morning.read_text(encoding='utf-8')
