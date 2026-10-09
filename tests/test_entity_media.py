from dataclasses import replace
import pytest
from curio.config import CurioConfig
from curio.media.providers import MediaAsset
from curio.stages.scene_contract import Alias, SemanticScene, VideoContext, VisualRepresentation
from curio.stages.media_contracts import Candidate, CandidateEvaluation, EvaluationBatch
from curio.stages.visual_contracts import SearchQuery
from curio.stages import entity_media, media_semantics, scoring, research


def scene(name='Aristotle', source='https://pt.wikipedia.org/wiki/Arist%C3%B3teles'):
    return SemanticScene(1, 'A entidade e sua trajetória.', subject='Birth',
        primary_entity='Aristóteles', video_context=VideoContext(
            topic='Aristóteles', aliases=[Alias(name, 'wikipedia_langlink', source, True)]),
        representations=(VisualRepresentation('ancient birthplace map'),))


def test_verified_single_word_alias_establishes_topic_but_not_specific_event():
    evidence = scoring.semantic_relevance({'title': 'Aristotle by Jusepe de Ribera'}, scene())
    assert evidence['topic_relevance'] == 100
    assert evidence['scene_relevance'] == 0
    unverified = replace(scene(), video_context=VideoContext(topic='Aristóteles', aliases=[Alias('Aristotle')]))
    assert scoring.semantic_relevance({'title': 'Aristotle by Jusepe de Ribera'}, unverified)['topic_relevance'] == 0


@pytest.mark.parametrize('name,file', [('Aristotle','Aristotle Altemps Inv8575.jpg'),
    ('Mercury (planet)','Mercury globe.jpg'), ('Jaguar','Panthera onca.jpg')])
def test_canonical_source_binding_survives_model_outage(tmp_path, monkeypatch, name, file):
    monkeypatch.setattr(research, '_get_json', lambda *args, **kwargs:
        {'query': {'pages': {'1': {'pageimage': file}}}})
    cfg = CurioConfig(cache_dir=str(tmp_path))
    enriched = entity_media.enrich_entity_media((scene(name),), cfg)[0]
    asset = MediaAsset('wikimedia', '1', title='File:' + file)
    candidate = Candidate(asset, SearchQuery(name, 'topic_contextual'), '1')
    rejected = CandidateEvaluation(candidate, 0, {}, False, 'no scene evidence')
    monkeypatch.setattr(media_semantics.nvidia, 'any_llm_available', lambda: False)
    result = media_semantics.assess_candidates(EvaluationBatch((), (rejected,)), enriched, cfg, 34)
    assert len(result.accepted) == 1
    assert result.accepted[0].evidence['semantic_relation'] == 'contextual'
    assert result.accepted[0].score == 62
    # A same-name object found by the query has no exact source binding.
    wrong = replace(candidate, asset=MediaAsset('wikimedia', '2', title=name + ' automobile.jpg'))
    rejected = replace(rejected, candidate=wrong)
    assert not media_semantics.assess_candidates(EvaluationBatch((), (rejected,)), enriched, cfg, 34).accepted


def test_entity_media_cache_avoids_network_and_unknown_sources(tmp_path, monkeypatch):
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        return {'query': {'pages': {'1': {'pageimage': 'Entity.jpg'}}}}
    monkeypatch.setattr(research, '_get_json', get)
    cfg = CurioConfig(cache_dir=str(tmp_path))
    first = entity_media.enrich_entity_media((scene(),), cfg)
    second = entity_media.enrich_entity_media((scene(),), cfg)
    assert first == second and len(calls) == 1
    unrelated = scene(source='https://wikipedia.org.evil.example/wiki/Entity')
    assert entity_media.enrich_entity_media((unrelated,), cfg) == (unrelated,)
    assert len(calls) == 1


def test_failed_semantic_chain_is_not_retried_per_candidate(tmp_path, monkeypatch):
    cfg = CurioConfig(cache_dir=str(tmp_path))
    calls = []
    monkeypatch.setattr(media_semantics.nvidia, 'any_llm_available', lambda: True)
    def request(*args):
        calls.append(1)
        raise media_semantics.nvidia.NvidiaError('Providers unavailable')
    monkeypatch.setattr(media_semantics, '_request', request)
    assert media_semantics._cached_request('prompt', {'a': 1}, cfg, 'assessment') is None
    assert media_semantics._cached_request('prompt', {'a': 2}, cfg, 'assessment') is None
    assert len(calls) == 1


def test_structured_depiction_uses_identity_not_shared_name(tmp_path, monkeypatch):
    target = scene('Mercury (planet)')
    context = target.video_context.to_dict()
    context['canonical_entity_media'] = [{'entity_id': 'Q308', 'file': 'Mercury.jpg',
                                          'source': target.video_context.aliases[0].evidence}]
    target = replace(target, video_context=VideoContext.from_value(context))
    def get(*args, **kwargs):
        return {'entities': {
            'Q925': {'claims': {}},
            'M11': {'statements': {'P180': [{'mainsnak': {'datavalue': {'value': {'id': 'Q308'}}}}]}},
            'M12': {'statements': {'P180': [{'mainsnak': {'datavalue': {'value': {'id': 'Q925'}}}}]}}}}
    monkeypatch.setattr(research, '_get_json', get)
    monkeypatch.setattr(media_semantics.nvidia, 'any_llm_available', lambda: False)
    items = tuple(CandidateEvaluation(Candidate(
        MediaAsset('wikimedia', key, title=title), SearchQuery('Mercury', 'topic_contextual'), key),
        0, {}, False, 'No scene evidence') for key, title in [('11', 'Mercury surface'), ('12', 'Mercury automobile')])
    cfg = CurioConfig(cache_dir=str(tmp_path))
    result = media_semantics.assess_candidates(EvaluationBatch((), items), target, cfg, 34)
    assert [item.candidate.asset.asset_id for item in result.accepted] == ['11']
    assert result.accepted[0].evidence['entity_media_binding']['entity_ids'] == ('Q308',)
    monkeypatch.setattr(research, '_get_json', lambda *args, **kwargs: pytest.fail('cached identity must work offline'))
    assert media_semantics.assess_candidates(EvaluationBatch((), items), target, cfg, 34).accepted


def test_digitized_historical_artwork_resolves_depicted_entity(tmp_path, monkeypatch):
    target = scene()
    context = target.video_context.to_dict()
    context['canonical_entity_media'] = [{'entity_id': 'Q868', 'file': 'Busto.jpg',
        'source': target.video_context.aliases[0].evidence}]
    target = replace(target, video_context=VideoContext.from_value(context))
    def get(url, **kwargs):
        if 'commons.wikimedia' in url:
            return {'entities': {'M22': {'statements': {'P6243': [
                {'mainsnak': {'datavalue': {'value': {'id': 'Q123'}}}}]}}}}
        return {'entities': {'Q123': {'claims': {'P180': [
            {'mainsnak': {'datavalue': {'value': {'id': 'Q868'}}}}]}}}}
    monkeypatch.setattr(research, '_get_json', get)
    item = CandidateEvaluation(Candidate(MediaAsset('wikimedia', '22', title='Catalog artwork 123'),
        SearchQuery('entity', 'topic_contextual'), '22'), 0, {}, False, 'No lexical identity')
    evidence = entity_media.structured_depiction_evidence((item,), target, CurioConfig(cache_dir=str(tmp_path)))
    assert evidence['22']['via_artworks'] == {'Q123': ['Q868']}
    assert evidence['22']['entity_ids'] == ['Q868']


def test_actual_rejected_ribera_catalog_record_recovers_without_llm(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    data = json.loads(Path('scripts/fixtures/aristotle_catalog_identity.json').read_text())
    folder = tmp_path / 'entity-media/claims'
    folder.mkdir(parents=True)
    for key, claims in data.items():
        (folder / (key + '.json')).write_text(json.dumps(claims))
    target = scene()
    context = target.video_context.to_dict()
    context['canonical_entity_media'] = [{'file': 'Aristotle_Altemps_Inv8575.jpg',
        'entity_id': 'Q868', 'source': target.video_context.aliases[0].evidence}]
    target = replace(target, video_context=VideoContext.from_value(context))
    candidate = Candidate(MediaAsset('wikimedia', '17202196',
        title='File:Aristotle by Jusepe de Ribera.jpg'), SearchQuery('Aristotle', 'topic_contextual'), '17202196')
    item = CandidateEvaluation(candidate, 0, {}, False, 'no topic evidence')
    monkeypatch.setattr(media_semantics.nvidia, 'any_llm_available', lambda: False)
    monkeypatch.setattr(research, '_get_json', lambda *args, **kwargs: pytest.fail('catalog replay is offline'))
    result = media_semantics.assess_candidates(EvaluationBatch((), (item,)), target, CurioConfig(cache_dir=str(tmp_path)), 34)
    assert result.accepted[0].evidence['entity_media_binding']['via_artworks']['Q4791095'] == ('Q868',)


def test_catalog_identity_cannot_leak_between_provider_ids(tmp_path, monkeypatch):
    cfg, target = CurioConfig(cache_dir=str(tmp_path)), scene()
    monkeypatch.setattr(entity_media, 'structured_depiction_evidence', lambda *args: {'22': {'entity_ids': ['Q868']}})
    monkeypatch.setattr(media_semantics.nvidia, 'any_llm_available', lambda: False)
    candidate = Candidate(MediaAsset('pixabay', '22', title='Random airport'),
        SearchQuery('entity', 'topic_contextual'), '22')
    item = CandidateEvaluation(candidate, 0, {}, False, 'no topic evidence')
    assert not media_semantics.assess_candidates(EvaluationBatch((), (item,)), target, cfg, 34).accepted
